from sqlalchemy import BigInteger, create_engine, func, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.core.enums import CandidateStatus, JobStatus, JobType
from app.core import enums as e
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.jobs.automatic_catalog import backfill_successful_candidate_crawls, register_successful_candidate_crawl
from app.models import (ArtifactStorage, DownloadLink, Job, Software, SoftwareArtifact,
                        SoftwareCandidate, SoftwareRelease, SoftwareSource, SoftwareVariant)
from app.main import app
from app.services.catalog import ensure_candidate_software
from app.services.automatic_catalog import import_successful_crawl_download


@compiles(BigInteger, "sqlite")
def sqlite_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


def make_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def test_ensure_candidate_software_creates_and_links_idempotently():
    engine = make_db()
    with Session(engine) as db:
        candidate = SoftwareCandidate(name="Axialis IconW", normalized_name="axialis iconw",
                                      category="Design", status=CandidateStatus.DISCOVERED)
        db.add(candidate)
        db.commit()

        software = ensure_candidate_software(db, candidate.id)
        again = ensure_candidate_software(db, candidate.id)

        assert again.id == software.id
        assert candidate.status is CandidateStatus.ACCEPTED
        assert candidate.software_id == software.id
        assert software.slug == "axialis-iconw"
        assert db.scalar(select(func.count()).select_from(Software)) == 1


def test_successful_crawl_registers_software_and_backfill_is_idempotent():
    engine = make_db()
    with Session(engine) as db:
        candidate = SoftwareCandidate(name="Historical Tool", normalized_name="historical tool",
                                      status=CandidateStatus.REVIEWING)
        db.add(candidate)
        db.flush()
        first = Job(job_type=JobType.CRAWL, target_type="candidate_auto_search", target_id=candidate.id,
                    status=JobStatus.SUCCESS, result={"matches": [{"candidate_name": candidate.name}]})
        second = Job(job_type=JobType.CRAWL, target_type="candidate_auto_search", target_id=candidate.id,
                     status=JobStatus.SUCCESS, result={"matches": []})
        db.add_all([first, second])
        db.commit()

        register_successful_candidate_crawl(db, first)
        assert first.result["software_name"] == "Historical Tool"
        assert first.result["software_id"] == candidate.software_id
        assert backfill_successful_candidate_crawls(db) == 0

        legacy = SoftwareCandidate(name="Legacy Tool", normalized_name="legacy tool",
                                   status=CandidateStatus.DISCOVERED)
        db.add(legacy)
        db.flush()
        db.add(Job(job_type=JobType.CRAWL, target_type="candidate_auto_search", target_id=legacy.id,
                   status=JobStatus.SUCCESS, result={"matches": []}))
        db.commit()

        assert backfill_successful_candidate_crawls(db) == 1
        assert legacy.status is CandidateStatus.ACCEPTED
        assert legacy.software_id is not None
        assert backfill_successful_candidate_crawls(db) == 0
        assert db.scalar(select(func.count()).select_from(Software)) == 2


def test_backfill_does_not_accept_rejected_candidates():
    engine = make_db()
    with Session(engine) as db:
        candidate = SoftwareCandidate(name="Rejected Tool", normalized_name="rejected tool",
                                      status=CandidateStatus.REJECTED)
        db.add(candidate)
        db.flush()
        db.add(Job(job_type=JobType.CRAWL, target_type="candidate_auto_search", target_id=candidate.id,
                   status=JobStatus.SUCCESS))
        db.commit()

        assert backfill_successful_candidate_crawls(db) == 0
        assert candidate.status is CandidateStatus.REJECTED
        assert db.scalar(select(func.count()).select_from(Software)) == 0


def test_successful_download_is_imported_as_local_installer_and_source(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    local_path = "archive/_crawl-backups/Axialis/crawl-8/link-9/IconWorkshop-Pro.exe"
    archived_file = tmp_path / local_path
    archived_file.parent.mkdir(parents=True)
    archived_file.write_bytes(b"installer")
    engine = make_db()
    with Session(engine) as db:
        candidate = SoftwareCandidate(name="Axialis IconWorkshop Professional",
                                      normalized_name="axialis iconworkshop professional",
                                      status=CandidateStatus.DISCOVERED)
        db.add(candidate)
        db.flush()
        crawl = Job(job_type=JobType.CRAWL, target_type="candidate_auto_search", target_id=candidate.id,
                    status=JobStatus.SUCCESS, result={"matches": [{
                        "candidate_name": candidate.name,
                        "page_url": "https://mirror.example/axialis",
                        "versions": ["6.91"],
                        "links": [{"url": "https://downloads.example/IconWorkshop-Pro.exe",
                                   "provider": "OTHER", "link_type": "DIRECT_FILE", "label": "Installer"}],
                    }]})
        db.add(crawl)
        db.flush()
        download = Job(job_type=JobType.DOWNLOAD, target_type="crawl_link_download", target_id=crawl.id,
                       status=JobStatus.SUCCESS,
                       payload={"crawl_job_id": crawl.id, "candidate_name": candidate.name,
                                "page_url": "https://mirror.example/axialis",
                                "url": "https://downloads.example/IconWorkshop-Pro.exe"},
                       result={"files": [{"filename": "IconWorkshop-Pro.exe", "file_size": 9,
                                          "local_path": local_path, "source_url": "https://downloads.example/IconWorkshop-Pro.exe",
                                          "resolved_url": "https://downloads.example/IconWorkshop-Pro.exe",
                                          "sha256": "a" * 64}]})
        db.add(download)
        db.commit()

        assert import_successful_crawl_download(db, download) == 1
        assert import_successful_crawl_download(db, download) == 0

        software = db.scalar(select(Software).where(Software.name == candidate.name))
        release = db.scalar(select(SoftwareRelease).where(SoftwareRelease.software_id == software.id))
        source = db.scalar(select(SoftwareSource).where(SoftwareSource.software_id == software.id))
        variant = db.scalar(select(SoftwareVariant).where(SoftwareVariant.release_id == release.id))
        artifact = db.scalar(select(SoftwareArtifact).where(SoftwareArtifact.variant_id == variant.id))
        storage = db.scalar(select(ArtifactStorage).where(ArtifactStorage.artifact_id == artifact.id))
        link = db.scalar(select(DownloadLink).where(DownloadLink.software_id == software.id))

        assert candidate.status is CandidateStatus.ACCEPTED
        assert release.version == "6.91"
        assert source.source_url == "https://mirror.example/axialis"
        assert variant.os is e.OperatingSystem.WINDOWS
        assert variant.architecture is e.Architecture.UNKNOWN
        assert artifact.package_type is e.PackageType.EXE
        assert artifact.download_status is e.DownloadStatus.DOWNLOADED
        assert artifact.verification_status is e.VerificationStatus.PENDING
        assert artifact.local_path == local_path
        assert storage.provider is e.StorageProviderType.LOCAL
        assert storage.status is e.StorageStatus.AVAILABLE
        assert link.link_url == "https://downloads.example/IconWorkshop-Pro.exe"


def test_software_detail_api_reports_catalog_overview_counts():
    engine = make_db()
    with Session(engine) as db:
        software = Software(name="Detail App", slug="detail-app")
        db.add(software)
        db.flush()
        release = SoftwareRelease(software_id=software.id, version="1.0")
        db.add(release)
        db.flush()
        variant = SoftwareVariant(release_id=release.id, os=e.OperatingSystem.WINDOWS,
                                  architecture=e.Architecture.UNKNOWN)
        db.add(variant)
        db.flush()
        artifact = SoftwareArtifact(variant_id=variant.id, filename="detail.exe", package_type=e.PackageType.EXE,
                                    local_path="archive/detail/1.0/detail.exe")
        db.add(artifact)
        db.flush()
        db.add(ArtifactStorage(artifact_id=artifact.id, provider=e.StorageProviderType.LOCAL,
                               status=e.StorageStatus.AVAILABLE))
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        try:
            response = TestClient(app).get(f"/api/v1/software/{software.id}")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["catalog_overview"] == {
            "source_count": 0, "release_count": 1, "artifact_count": 1, "local_archive_count": 1,
        }
