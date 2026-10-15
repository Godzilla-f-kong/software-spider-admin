import hashlib

from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import v1
from app.core.enums import CandidateStatus, JobStatus
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlPool, SoftwareCandidate


@compiles(BigInteger, "sqlite")
def sqlite_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


def test_cross_site_target_jobs_and_pause_resume(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(v1, "enqueue", lambda _job_id: True)
    with Session(engine) as db:
        candidate = SoftwareCandidate(name="FusionTestTool", normalized_name="fusiontesttool",
                                      target_version="3.2", status=CandidateStatus.DISCOVERED)
        db.add(candidate)
        for base in ("https://one.example/", "https://two.example/"):
            db.add(CrawlPool(base_url=base, url_hash=hashlib.sha256(base.encode()).hexdigest(), enabled=True))
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        try:
            client = TestClient(app)
            response = client.post(f"/api/v1/candidates/{candidate.id}/search")
            assert response.status_code == 202, response.text
            jobs = response.json()["jobs"]
            assert len(jobs) == 2 and all(job["payload"]["candidate_ids"] == [candidate.id] for job in jobs)
            job_id = jobs[0]["id"]
            paused = client.post(f"/api/v1/crawl-pools/scans/{job_id}/pause")
            assert paused.status_code == 200 and paused.json()["status"] == "PAUSED"
            resumed = client.post(f"/api/v1/crawl-pools/scans/{job_id}/resume")
            assert resumed.status_code == 202 and resumed.json()["status"] == "PENDING"
            assert client.post(f"/api/v1/crawl-pools/scans/{job_id}/resume").status_code == 409
            assert db.get(v1.Job, job_id).status is JobStatus.PENDING
            running = db.get(v1.Job, job_id)
            running.status = JobStatus.RUNNING
            db.commit()
            assert client.post(f"/api/v1/crawl-pools/scans/{job_id}/pause").status_code == 200
            assert client.post(f"/api/v1/crawl-pools/scans/{job_id}/resume").status_code == 409
            running.message = "Paused (PAUSED); 0 matches"
            db.commit()
            assert client.post(f"/api/v1/crawl-pools/scans/{job_id}/resume").status_code == 202
            running.status = JobStatus.FAILED
            running.error_message = "TIMEOUT: Source request timed out"
            db.commit()
            retried = client.post(f"/api/v1/crawl-pools/scans/{job_id}/retry")
            assert retried.status_code == 202 and retried.json()["error_message"] is None
        finally:
            app.dependency_overrides.clear()
