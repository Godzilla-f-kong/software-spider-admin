import hashlib
import base64
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import httpx
from pathlib import Path

from app.core.enums import JobStatus, JobType
from app.db.base import Base
from app.jobs import automatic_downloads
from app.jobs import download_runner
from app.models import Job
from app.api.v1 import RESOURCES, serialize
from app.services import crawl_link_download
from app.downloader.base import DownloadResult
from app.core.config import settings
from app.spider.errors import SpiderError


@compiles(BigInteger, "sqlite")
def sqlite_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


def make_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def test_completed_crawl_enqueues_each_distinct_artifact_and_share_once(monkeypatch):
    engine = make_db()
    enqueued = []
    monkeypatch.setattr("app.jobs.download_runner.enqueue", lambda job_id: enqueued.append(job_id) or True)
    with Session(engine) as db:
        crawl = Job(job_type=JobType.CRAWL, target_type="candidate_auto_search", target_id=19,
                    status=JobStatus.SUCCESS, result={"matches": [{
                        "candidate_name": "Example App", "page_url": "https://example.test/downloads",
                        "artifacts": [{"url": "https://cdn.example.test/app.exe", "filename": "app.exe"}],
                        "links": [
                            {"url": "https://cdn.example.test/app.exe", "provider": "OTHER",
                             "link_type": "DIRECT_FILE"},
                            {"url": "https://pan.example.test/s/abc", "provider": "OTHER",
                             "link_type": "PAN_SHARE", "access_code": "1234"},
                        ],
                    }]})
        db.add(crawl)
        db.commit()

        assert automatic_downloads.schedule_completed_crawl_downloads(db, [crawl.id]) == 2
        children = db.scalars(select(Job).where(Job.target_type == "crawl_link_download").order_by(Job.id)).all()
        assert crawl.auto_download_processed is True
        assert [child.payload["url"] for child in children] == [
            "https://cdn.example.test/app.exe", "https://pan.example.test/s/abc"]
        assert children[1].payload["access_code"] == "1234"
        assert enqueued == [child.id for child in children]

        assert automatic_downloads.schedule_completed_crawl_downloads(db, [crawl.id]) == 0
        assert len(db.scalars(select(Job).where(Job.target_type == "crawl_link_download")).all()) == 2


def test_download_worker_concurrency_is_capped_at_five(monkeypatch):
    monkeypatch.setattr(download_runner, "_configured_concurrency", None)
    monkeypatch.setattr(download_runner.settings, "download_max_concurrency", 20)

    assert download_runner.worker_concurrency() == 5


def test_share_page_second_pass_extracts_all_direct_package_links(monkeypatch):
    class FakeSpiderHttpClient:
        def request(self, method, url, **_kwargs):
            if method == "GET":
                return httpx.Response(200, headers={"content-type": "text/html"},
                    text='<a href="https://cdn.example.test/a.exe">Windows</a>'
                         '<a href="https://cdn.example.test/b.zip">Portable</a>'), url
            raise SpiderError("NETWORK_ERROR", "HEAD is unavailable")

        def close(self):
            pass

    monkeypatch.setattr(crawl_link_download, "SpiderHttpClient", FakeSpiderHttpClient)
    job = Job(payload={"url": "https://share.example.test/s/abc", "filename": "Example"})

    assert crawl_link_download._resolve_links(job.payload["url"], job) == [
        ("https://cdn.example.test/a.exe", "a.exe"),
        ("https://cdn.example.test/b.zip", "b.zip"),
    ]


def test_423down_base64_wrapper_is_unwrapped_and_validated():
    target = "https://files.example.test/tool.exe"
    encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")

    class Validator:
        def validate(self, url):
            assert url == target
            return url

    class FakeHttp:
        validator = Validator()

    wrapper = f"https://www.423down.com/go.php?url={encoded}"
    assert crawl_link_download._unwrap_download_wrapper(wrapper, FakeHttp()) == target


def test_direct_crawl_link_download_is_archived_under_backup_root(tmp_path, monkeypatch):
    engine = make_db()
    monkeypatch.setattr(settings, "data_root", str(tmp_path))

    def fake_download(self, request, _progress, cancelled):
        assert not cancelled()
        content = b"installer bytes"
        request.part_path.write_bytes(content)
        return DownloadResult(request.part_path, request.expected_filename, len(content),
                              "application/octet-stream", request.url, 0.1, 200)

    monkeypatch.setattr(crawl_link_download.HttpDownloader, "download", fake_download)
    with Session(engine) as db:
        job = Job(job_type=JobType.DOWNLOAD, target_type="crawl_link_download", target_id=44,
                  status=JobStatus.RUNNING, payload={
                      "url": "https://cdn.example.test/example.exe", "filename": "example.exe",
                      "kind": "DIRECT_FILE", "candidate_name": "Example", "crawl_job_id": 44,
                  })
        db.add(job)
        db.commit()

        crawl_link_download.CrawlLinkDownloadService().download(db, job)

        saved = job.result["files"][0]
        assert saved["local_path"].startswith("archive/_crawl-backups/Example/crawl-44/")
        assert Path(settings.data_path, saved["local_path"]).read_bytes() == b"installer bytes"
        assert saved["sha256"] == hashlib.sha256(b"installer bytes").hexdigest()


def test_download_job_serialization_includes_candidate_software_name():
    engine = make_db()
    with Session(engine) as db:
        job = Job(job_type=JobType.DOWNLOAD, target_type="crawl_link_download", target_id=44,
                  status=JobStatus.PENDING, payload={"candidate_name": "Example App"})
        db.add(job)
        db.commit()

        data = serialize(next(resource for resource in RESOURCES if resource.path == "jobs"), job, db)

        assert data["target_id"] == 44
        assert data["target_label"] == "Example App"
