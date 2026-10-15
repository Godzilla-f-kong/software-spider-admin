import hashlib

from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.api import v1
from app.core.enums import CandidateStatus, JobStatus, JobType
from app.db.base import Base
from app.db.session import get_db
from app.jobs import spider_runner
from app.main import app
from app.spider.normalizers import URLSafetyValidator
from app.models import CrawlPool, Job, SoftwareCandidate


@compiles(BigInteger, "sqlite")
def sqlite_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


def make_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def add_pool(db: Session, url: str) -> CrawlPool:
    pool = CrawlPool(base_url=url, url_hash=hashlib.sha256(url.encode()).hexdigest(), enabled=True)
    db.add(pool)
    db.flush()
    return pool


def test_candidate_is_automatically_queued_for_all_enabled_pools(monkeypatch):
    engine = make_db()
    queued = []
    monkeypatch.setattr(spider_runner, "enqueue", lambda job_id: queued.append(job_id) or True)
    with Session(engine) as db:
        first = add_pool(db, "https://one.example/")
        second = add_pool(db, "https://two.example/")
        candidate = SoftwareCandidate(name="AutoTool", normalized_name="autotool",
                                      status=CandidateStatus.DISCOVERED, priority_score=80)
        db.add(candidate)
        db.commit()

        jobs = spider_runner.schedule_automatic_candidate_searches(db, candidate_ids=[candidate.id])
        assert len(jobs) == 1
        assert jobs[0].job_type is JobType.CRAWL
        assert jobs[0].target_type == "candidate_auto_search"
        assert jobs[0].payload["candidate"]["id"] == candidate.id
        assert jobs[0].payload["pool_ids"] == [first.id, second.id]
        assert queued == [jobs[0].id]

        assert spider_runner.schedule_automatic_candidate_searches(db, candidate_ids=[candidate.id]) == []
        assert len(db.scalars(select(Job).where(Job.target_type == "candidate_auto_search")).all()) == 1


def test_admin_candidate_and_url_pool_creation_auto_queue_without_start_action(monkeypatch):
    engine = make_db()
    monkeypatch.setattr(spider_runner, "enqueue", lambda _job_id: True)
    monkeypatch.setattr(spider_runner.settings, "spider_enabled", True)
    monkeypatch.setattr(URLSafetyValidator, "validate", lambda _self, url: url)
    with Session(engine) as db:
        app.dependency_overrides[get_db] = lambda: db
        try:
            client = TestClient(app)
            candidate_response = client.post("/api/v1/candidates", json={"name": "AutoTool"})
            assert candidate_response.status_code == 201, candidate_response.text
            candidate = candidate_response.json()
            assert candidate["automatic_crawl_status"] == "WAITING_FOR_URL_POOL"
            assert candidate["automatic_crawl_job_id"] is None

            pool_response = client.post("/api/v1/crawl-pools", json={"base_url": "https://auto.example/"})
            assert pool_response.status_code == 201, pool_response.text
            job = db.scalar(select(Job).where(Job.target_type == "candidate_auto_search"))
            assert job is not None
            assert job.target_id == candidate["id"]
            assert job.payload["pool_ids"] == [pool_response.json()["id"]]
        finally:
            app.dependency_overrides.clear()


def test_new_url_pool_is_queued_for_unmatched_candidate_only(monkeypatch):
    engine = make_db()
    monkeypatch.setattr(spider_runner, "enqueue", lambda _job_id: True)
    with Session(engine) as db:
        old_pool = add_pool(db, "https://old.example/")
        candidate = SoftwareCandidate(name="AutoTool", normalized_name="autotool",
                                      status=CandidateStatus.DISCOVERED)
        db.add(candidate)
        db.commit()
        first = spider_runner.schedule_automatic_candidate_searches(db, candidate_ids=[candidate.id])
        first[0].status = JobStatus.SUCCESS
        first[0].result = {"stop_reason": "ALL_ENABLED_WEBSITES_CHECKED"}
        db.commit()

        new_pool = add_pool(db, "https://new.example/")
        db.commit()
        added = spider_runner.schedule_automatic_candidate_searches(db, pool_ids=[new_pool.id])
        assert len(added) == 1
        assert added[0].payload["pool_ids"] == [new_pool.id]

        added[0].status = JobStatus.SUCCESS
        added[0].result = {"stop_reason": "MATCH_FOUND"}
        db.commit()
        third_pool = add_pool(db, "https://third.example/")
        db.commit()
        assert spider_runner.schedule_automatic_candidate_searches(db, pool_ids=[third_pool.id]) == []


def test_automatic_search_stops_after_first_matching_website(monkeypatch):
    engine = make_db()
    calls = []

    class FakeCrawler:
        def scan(self, pool, candidates, progress, checkpoint=None, should_pause=None, stop_on_match=False):
            calls.append(pool.id)
            assert len(candidates) == 1
            assert stop_on_match is True
            match = {"candidate_id": candidates[0].id, "candidate_name": candidates[0].name,
                     "match_status": "MATCHED", "page_url": pool.base_url + "tool"}
            matches = [match] if pool.id == 2 else []
            result = {"pool_url": pool.base_url, "visited_pages": 3, "matches": matches,
                      "warnings": [], "strategies": {"SITE_SEARCH": 1},
                      "stop_reason": "MATCH_FOUND" if matches else "FRONTIER_EMPTY", "checkpoint": None}
            progress(result)
            return result

    monkeypatch.setattr(spider_runner, "PoolCrawler", FakeCrawler)
    with Session(engine) as db:
        first = add_pool(db, "https://one.example/")
        second = add_pool(db, "https://two.example/")
        third = add_pool(db, "https://three.example/")
        candidate = SoftwareCandidate(name="AutoTool", normalized_name="autotool",
                                      status=CandidateStatus.DISCOVERED)
        db.add(candidate)
        db.flush()
        job = Job(job_type=JobType.CRAWL, target_type="candidate_auto_search", target_id=candidate.id,
            status=JobStatus.RUNNING, payload={"workflow": "automatic_candidate_search",
                "candidate": {"id": candidate.id, "name": candidate.name,
                    "normalized_name": candidate.normalized_name, "status": candidate.status.value},
                "pool_ids": [first.id, second.id, third.id]})
        db.add(job)
        db.commit()

        spider_runner._run_automatic_candidate_search(db, job)

        assert calls == [first.id, second.id]
        assert job.result["stop_reason"] == "MATCH_FOUND"
        assert job.result["matches"][0]["crawl_pool_id"] == second.id


def test_spider_worker_is_globally_serial_within_admin_process():
    assert spider_runner.worker_concurrency() == 1
    assert spider_runner._configure()._max_workers == 1
