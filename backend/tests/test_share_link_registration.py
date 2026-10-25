import httpx
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.core import enums as e
from app.core.config import settings
from app.db.base import Base
from app.models import DownloadLink, Job, ShareLinkSubmission, Software, SoftwareSource
from app.storage.share_link_registry import (prepare_crawl_job, prepare_download_link,
                                             queue_submission, request_payload, scan_existing_links,
                                             update_submission, validate_share_data)


@compiles(BigInteger, "sqlite")
def sqlite_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


def _engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def test_share_link_completeness_and_payload():
    assert validate_share_data("Demo", "https://pan.example/s/abcd", "A1b2") == []
    assert "分享码必须是 4 位字母或数字" in validate_share_data(
        "Demo", "https://pan.example/s/abcd", "no-code")
    assert validate_share_data("Demo", "file:///tmp/a", "A1b2")
    assert validate_share_data("Demo", "https://user:pass@pan.example/s/a", "A1b2")

    row = ShareLinkSubmission(fingerprint="f" * 64, software_name="Demo",
        external_url="https://pan.example/s/abcd", extract_code="A1b2",
        file_arch="办公教育", os="Windows", architecture="x64", filetype=5)
    payload = request_payload(row)
    assert payload == {"softwareName": "Demo", "external_url": "https://pan.example/s/abcd",
                       "extractCode": "A1b2", "filetype": 5, "file_arch": "办公教育",
                       "os": "Windows", "architecture": "x64"}


def test_scan_existing_download_links_is_idempotent_and_tracks_missing_code():
    engine = _engine()
    with Session(engine) as db:
        software = Software(name="Demo", slug="demo", category="办公教育")
        db.add(software)
        db.flush()
        source = SoftwareSource(software_id=software.id, source_type=e.SourceType.OTHER,
                                source_url="https://publisher.example", adapter_type=e.AdapterType.MANUAL)
        db.add(source)
        db.flush()
        db.add_all([
            DownloadLink(software_id=software.id, source_id=source.id, provider=e.DownloadLinkProvider.QUARK,
                         link_type=e.DownloadLinkType.PAN_SHARE, link_url="https://pan.example/s/abcd",
                         access_code="A1b2"),
            DownloadLink(software_id=software.id, source_id=source.id, provider=e.DownloadLinkProvider.XUNLEI,
                         link_type=e.DownloadLinkType.PAN_SHARE, link_url="https://pan.example/s/efgh",
                         access_code=None),
        ])
        db.add(Job(job_type=e.JobType.CRAWL, target_type="candidate_auto_search", target_id=41,
            status=e.JobStatus.SUCCESS, result={"matches": [{"candidate_id": 41,
                "candidate_name": "Demo", "page_url": "https://publisher.example/demo",
                "links": [{"url": "https://pan.example/s/abcd", "access_code": "A1b2",
                           "provider": "QUARK", "link_type": "PAN_SHARE"}]}]}))
        db.commit()
        first = scan_existing_links(db)
        second = scan_existing_links(db)
        records = db.scalars(select(ShareLinkSubmission).order_by(ShareLinkSubmission.external_url)).all()
        assert first["scanned"] == 3 and first["ready"] == 1 and first["incomplete"] == 1
        assert second["scanned"] == 3
        assert len(records) == 2
        assert records[0].status is e.ShareLinkSubmissionStatus.READY
        assert records[0].file_arch == "办公教育"
        assert records[1].status is e.ShareLinkSubmissionStatus.INCOMPLETE
        job = queue_submission(db, records[0])
        db.commit()
        assert job.job_type is e.JobType.REGISTER_SHARE_LINK
        assert records[0].status is e.ShareLinkSubmissionStatus.QUEUED
    engine.dispose()


def test_candidate_crawl_links_are_prepared_without_artifact_download():
    engine = _engine()
    with Session(engine) as db:
        candidate_job = Job(job_type=e.JobType.CRAWL, target_type="candidate_auto_search", target_id=42,
            status=e.JobStatus.SUCCESS, result={"software_id": 7, "matches": [{
                "candidate_id": 42, "candidate_name": "Demo", "page_url": "https://site.example/demo",
                "target_os": "WINDOWS", "target_architecture": "X64",
                "links": [{"url": "https://pan.example/share", "access_code": "X9a2",
                           "provider": "QUARK", "link_type": "PAN_SHARE", "label": "Cloud"}],
            }]})
        db.add(candidate_job)
        db.flush()
        assert prepare_crawl_job(db, candidate_job) == 1
        db.flush()
        row = db.scalar(select(ShareLinkSubmission))
        assert row is not None
        assert row.status is e.ShareLinkSubmissionStatus.READY
        assert row.crawl_job_id == candidate_job.id
        assert row.os == "Windows" and row.architecture == "x64"
        assert not db.scalar(select(Job.id).where(Job.job_type == e.JobType.DOWNLOAD))
    engine.dispose()


def test_incomplete_submission_can_be_completed():
    engine = _engine()
    with Session(engine) as db:
        row = ShareLinkSubmission(fingerprint="b" * 64, software_name="Demo",
            external_url="https://pan.example/s/abcd", extract_code=None,
            status=e.ShareLinkSubmissionStatus.INCOMPLETE)
        db.add(row)
        db.commit()
        update_submission(db, row, {"extract_code": "A1b2"})
        assert row.status is e.ShareLinkSubmissionStatus.READY
        assert row.validation_errors == []
    engine.dispose()


def test_registration_worker_uses_mocked_cloud_api(monkeypatch):
    from app.jobs import share_link_runner as runner

    engine = _engine()
    factory = sessionmaker(engine)
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["X-Integration-Key"] == "integration-secret"
        body = __import__("json").loads(request.content)
        assert body["softwareName"] == "Demo" and body["extractCode"] == "A1b2"
        return httpx.Response(200, json={"code": 200, "message": "OK", "data": {
            "id": 123, "token": "safe-share-token", "link": "https://share.example/#/s/token",
            "reused": True, "extractCode": "A1b2"}})

    real_client = httpx.Client
    monkeypatch.setattr(runner, "SessionLocal", factory)
    monkeypatch.setattr(settings, "cloud_integration_api_key", "integration-secret")
    monkeypatch.setattr(settings, "self_hosted_base_url", "http://cloud.example:9000")
    monkeypatch.setattr(settings, "cloud_sharelink_path", "/api/sharelink/create-online")
    def mock_client(**kwargs):
        assert kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(runner.httpx, "Client", mock_client)

    with Session(engine) as db:
        row = ShareLinkSubmission(fingerprint="a" * 64, software_name="Demo",
            external_url="https://pan.example/s/abcd", extract_code="A1b2",
            status=e.ShareLinkSubmissionStatus.READY)
        db.add(row)
        db.flush()
        job = queue_submission(db, row)
        db.commit()
        job_id, row_id = job.id, row.id

    runner._run(job_id)
    with Session(engine) as db:
        row = db.get(ShareLinkSubmission, row_id)
        job = db.get(Job, job_id)
        assert row.status is e.ShareLinkSubmissionStatus.SUCCESS
        assert row.cloud_record_id == 123 and row.cloud_reused is True
        assert row.cloud_link == "https://share.example/#/s/token"
        assert job.status is e.JobStatus.SUCCESS and len(calls) == 1
    engine.dispose()
