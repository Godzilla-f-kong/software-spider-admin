"""Real public HTTP download through isolated Phase 3 Jobs and a temporary SQLite DB.

Run from project root: .venv\Scripts\python.exe scripts\probe_download_pipeline.py
No records are written to MySQL or the configured data root.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.enums import Architecture, JobStatus, JobType, OperatingSystem, PackageType, VerificationStatus
from app.db.base import Base
from app.jobs import download_runner
from app.models import Job, Software, SoftwareArtifact, SoftwareRelease, SoftwareVariant
from app.storage.archive import ArchiveManager
from app.downloader.staging import StagingManager


@compiles(BigInteger, "sqlite")
def sqlite_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


def main() -> None:
    staging = ROOT / "data" / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="phase3-probe-", dir=staging) as folder:
        temporary = Path(folder)
        settings.data_root = str(temporary / "data")
        settings.download_max_file_size = 3_000_000
        settings.download_min_free_space = 0
        engine = create_engine(f"sqlite:///{(temporary / 'probe.sqlite').as_posix()}")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        download_runner.SessionLocal = session_factory
        download_runner.enqueue = lambda _job_id: True  # Run each queued stage explicitly below.
        with session_factory() as db:
            software = Software(name="7-Zip Phase 3 Probe", slug="7-zip-phase3-probe")
            db.add(software)
            db.flush()
            release = SoftwareRelease(software_id=software.id, version="26.04")
            db.add(release)
            db.flush()
            variant = SoftwareVariant(release_id=release.id, os=OperatingSystem.WINDOWS,
                                      architecture=Architecture.X86)
            db.add(variant)
            db.flush()
            artifact = SoftwareArtifact(variant_id=variant.id, package_type=PackageType.EXE,
                filename="7zr.exe", source_url="https://github.com/ip7z/7zip/releases/download/26.04/7zr.exe")
            db.add(artifact)
            db.flush()
            artifact_id = artifact.id
            job = Job(job_type=JobType.DOWNLOAD, target_type="artifact", target_id=artifact_id,
                      status=JobStatus.PENDING, progress=0)
            db.add(job)
            db.commit()
            download_job_id = job.id
        download_runner._run(download_job_id)
        with session_factory() as db:
            verify = db.scalar(select(Job).where(Job.job_type == JobType.VERIFY,
                                                Job.target_id == artifact_id))
            if verify is None:
                download_job = db.get(Job, download_job_id)
                raise RuntimeError(f"Download did not queue verification: {download_job.error_message}")
            verify_job_id = verify.id
        download_runner._run(verify_job_id)
        with session_factory() as db:
            artifact = db.get(SoftwareArtifact, artifact_id)
            download_job = db.get(Job, download_job_id)
            verify_job = db.get(Job, verify_job_id)
            local = ArchiveManager().resolve_relative(artifact.local_path) if artifact.local_path else None
            print({"download_job": download_job.status.value, "verify_job": verify_job.status.value,
                   "verification": artifact.verification_status.value,
                   "size": artifact.file_size, "sha256": artifact.sha256,
                   "archive_exists": bool(local and local.is_file()), "relative_path": artifact.local_path})
            if not local or not local.is_file() or artifact.verification_status.value != "VERIFIED":
                raise RuntimeError("Pipeline did not create a verified archive")
            original_hash = artifact.sha256
            original_path = artifact.local_path
            second = Job(job_type=JobType.DOWNLOAD, target_type="artifact", target_id=artifact_id,
                         status=JobStatus.PENDING, progress=0, payload={"redownload": True})
            db.add(second)
            db.commit()
            second_id = second.id
        download_runner._run(second_id)
        with session_factory() as db:
            second_verify_id = db.scalar(select(Job.id).where(Job.job_type == JobType.VERIFY,
                Job.target_id == artifact_id).order_by(Job.id.desc()))
        download_runner._run(second_verify_id)
        with session_factory() as db:
            artifact = db.get(SoftwareArtifact, artifact_id)
            assert artifact.sha256 == original_hash and artifact.local_path == original_path
            assert len(list((temporary / "data" / "archive").rglob("7zr.exe"))) == 1
            print("repeat_download=reused_existing_archive")
            staged = StagingManager().complete(artifact_id)
            staged.parent.mkdir(parents=True, exist_ok=True)
            changed = bytearray(local.read_bytes())
            changed[-1] ^= 1
            staged.write_bytes(changed)
            changed_job = Job(job_type=JobType.VERIFY, target_type="artifact", target_id=artifact_id,
                              status=JobStatus.PENDING, progress=0,
                              payload={"redownload": True, "filename": "7zr.exe"})
            db.add(changed_job)
            db.commit()
            changed_job_id = changed_job.id
        download_runner._run(changed_job_id)
        with session_factory() as db:
            artifact = db.get(SoftwareArtifact, artifact_id)
            assert artifact.verification_status is VerificationStatus.MANUAL_REVIEW
            assert artifact.sha256 == original_hash and local.is_file()
            print("changed_hash=manual_review_original_archive_preserved")
        engine.dispose()


if __name__ == "__main__":
    main()
