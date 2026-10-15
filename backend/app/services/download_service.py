"""Download and verification orchestration independent of HTTP routes and Job scheduling."""
import time
import logging
from typing import Callable
from urllib.parse import urlsplit
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.enums import DownloadStatus, JobStatus, JobType, VerificationStatus, StorageProviderType, StorageStatus
from app.db.base import beijing_now
from app.downloader.base import DownloadProgress, DownloadRequest
from app.downloader.errors import DownloadError
from app.downloader.http_downloader import HttpDownloader
from app.downloader.staging import StagingManager
from app.models import ArtifactStorage, Job, SoftwareArtifact
from app.storage.archive import ArchiveManager
from app.verification.service import VerificationService

logger = logging.getLogger(__name__)


class DownloadService:
    def __init__(self, enqueue_verify: Callable[[int], bool]):
        self.enqueue_verify = enqueue_verify

    def download(self, db: Session, job: Job, artifact: SoftwareArtifact) -> None:
        if not artifact.source_url:
            raise DownloadError("UNSUPPORTED_PROTOCOL", "Artifact has no direct HTTP download URL")
        staging = StagingManager()
        part = staging.part(artifact.id)
        last_write = 0.0
        last_cancel = 0.0
        cancelled_flag = False

        def cancelled() -> bool:
            nonlocal last_cancel, cancelled_flag
            if time.monotonic() - last_cancel > .25:
                db.rollback()  # Start a fresh transaction so MySQL REPEATABLE READ sees cancellation.
                db.refresh(job)
                cancelled_flag = job.status is JobStatus.CANCELLED
                last_cancel = time.monotonic()
            return cancelled_flag

        def progress(value: DownloadProgress) -> None:
            nonlocal last_write
            if time.monotonic() - last_write < .5:
                return
            job.progress = min(99, round(value.downloaded * 100 / value.total)) if value.total else 0
            job.message = f"{value.downloaded} / {value.total or '?'} bytes"
            job.result = {"bytes_downloaded": value.downloaded, "total_bytes": value.total,
                          "speed_bytes_per_second": round(value.speed)}
            db.commit()
            last_write = time.monotonic()

        result = HttpDownloader().download(DownloadRequest(artifact.id, artifact.source_url, artifact.filename,
                                                            part, artifact.file_size), progress, cancelled)
        if cancelled():
            raise DownloadError("CANCELLED", "Download cancelled")
        complete = staging.complete(artifact.id)
        part.replace(complete)
        artifact.download_status = DownloadStatus.DOWNLOADED
        artifact.downloaded_at = beijing_now()
        artifact.resolved_url = result.resolved_url
        job.result = {"bytes_downloaded": result.file_size, "total_bytes": result.file_size,
                  "speed_bytes_per_second": round(result.file_size / max(result.elapsed_seconds, .001)),
                  "resolved_url": result.resolved_url, "content_type": result.content_type,
                  "filename": result.filename, "elapsed_seconds": result.elapsed_seconds,
                  "http_status": result.http_status}
        db.commit()
        logger.info("Download completed job_id=%s artifact_id=%s host=%s http_status=%s bytes=%s duration=%.2f",
                    job.id, artifact.id, urlsplit(result.resolved_url).hostname, result.http_status,
                    result.file_size, result.elapsed_seconds)
        verify = Job(job_type=JobType.VERIFY, target_type="artifact", target_id=artifact.id,
                     status=JobStatus.PENDING, progress=0, message="Awaiting verification",
                     payload={"download_job_id": job.id, "content_type": result.content_type,
                              "filename": result.filename, "redownload": bool((job.payload or {}).get("redownload"))})
        db.add(verify)
        db.commit()
        if not self.enqueue_verify(verify.id):
            verify.status = JobStatus.FAILED
            verify.error_message = "Verification queue is full; run Verify manually"
            verify.finished_at = beijing_now()
            db.commit()
        job.result = {**(job.result or {}), "verification_job_id": verify.id}


    def verify(self, db: Session, job: Job, artifact: SoftwareArtifact) -> None:
        manager = ArchiveManager()
        complete = StagingManager().complete(artifact.id)
        try:
            archived = manager.resolve_relative(artifact.local_path) if artifact.local_path else None
        except ValueError as exc:
            raise DownloadError("VERIFICATION_FAILED", "Unsafe local archive path") from exc
        path = complete if complete.exists() else archived
        if path is None or not path.is_file():
            raise DownloadError("VERIFICATION_FAILED", "Local file is missing")
        variant = artifact.variant
        release = variant.release
        software = release.software
        previous_hash = artifact.sha256
        details = VerificationService().verify(path, package_type=artifact.package_type,
            expected_architecture=variant.architecture, expected_version=release.version,
            filename=(job.payload or {}).get("filename") or artifact.filename,
            content_type=(job.payload or {}).get("content_type"),
            expected_sha256=previous_hash if not (job.payload or {}).get("redownload") else None)
        if artifact.file_size is not None and artifact.file_size != details.file_size and not previous_hash:
            details.warnings.append(f"FILE_SIZE: expected {artifact.file_size} bytes, got {details.file_size}")
            if details.status is VerificationStatus.VERIFIED:
                details.status = VerificationStatus.MANUAL_REVIEW
        details.metadata["download_filename"] = (job.payload or {}).get("filename") or artifact.filename
        if previous_hash and complete.exists() and details.sha256 != previous_hash:
            details.status = VerificationStatus.MANUAL_REVIEW
            details.warnings.append("ARTIFACT_CHANGED: downloaded SHA256 differs from previous archive")
        duplicate_id = db.scalar(select(SoftwareArtifact.id).where(SoftwareArtifact.id != artifact.id,
            SoftwareArtifact.sha256 == details.sha256, SoftwareArtifact.local_path.is_not(None)).limit(1))
        if duplicate_id:
            details.warnings.append(f"DUPLICATE_OF_ARTIFACT_ID={duplicate_id}")
        artifact.verification_details = details.as_dict()
        artifact.verification_status = details.status
        artifact.signature_status = details.signature_status
        artifact.verified_at = beijing_now()
        if not previous_hash:
            artifact.sha256, artifact.md5, artifact.file_size = details.sha256, details.md5, details.file_size
        job.result = details.as_dict()
        if details.status is VerificationStatus.REJECTED:
            if complete.exists():
                manager.fail(complete, artifact.id)
            artifact.download_status = DownloadStatus.DOWNLOADED
        elif details.status is VerificationStatus.VERIFIED:
            if complete.exists():
                if previous_hash and archived and archived.exists() and previous_hash == details.sha256:
                    complete.unlink()
                else:
                    relative = manager.archive_relative(software.slug, release.version, variant.os.value,
                                                        variant.architecture.value, details.metadata["download_filename"])
                    try:
                        manager.archive(complete, relative)
                    except FileExistsError:
                        relative = relative.with_name(f"{relative.stem}-{details.sha256[:8]}{relative.suffix}")
                        manager.archive(complete, relative)
                    artifact.local_path = relative.as_posix()
                    artifact.filename = details.metadata["download_filename"]
            artifact.sha256, artifact.md5, artifact.file_size = details.sha256, details.md5, details.file_size
            if artifact.local_path:
                local = db.scalar(select(ArtifactStorage).where(ArtifactStorage.artifact_id == artifact.id,
                    ArtifactStorage.provider == StorageProviderType.LOCAL).limit(1))
                if local is None:
                    local = ArtifactStorage(artifact_id=artifact.id, provider=StorageProviderType.LOCAL)
                    db.add(local)
                local.remote_path = artifact.local_path
                local.status = StorageStatus.AVAILABLE
        db.commit()
        logger.info("Verification completed job_id=%s artifact_id=%s status=%s sha256=%s size=%s",
                    job.id, artifact.id, details.status.value, details.sha256, details.file_size)
