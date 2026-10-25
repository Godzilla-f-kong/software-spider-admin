"""Download orchestration independent of HTTP routes and job scheduling."""
import time
import logging
from urllib.parse import urlsplit
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.enums import DownloadStatus, JobStatus, StorageProviderType, StorageStatus
from app.db.base import beijing_now
from app.downloader.base import DownloadProgress, DownloadRequest
from app.downloader.errors import DownloadError
from app.downloader.http_downloader import HttpDownloader
from app.downloader.staging import StagingManager
from app.models import ArtifactStorage, Job, SoftwareArtifact
from app.storage.archive import ArchiveManager
from app.storage.providers.self_hosted_provider import SelfHostedPanProvider

logger = logging.getLogger(__name__)


class DownloadService:
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
        variant = artifact.variant
        release = variant.release
        software = release.software
        manager = ArchiveManager()
        filename = result.filename or artifact.filename
        relative = manager.archive_relative(software.slug, release.version, variant.os.value,
                                            variant.architecture.value, filename)
        try:
            manager.archive(complete, relative)
        except FileExistsError:
            relative = relative.with_name(f"{relative.stem}-{time.time_ns()}{relative.suffix}")
            manager.archive(complete, relative)
        artifact.local_path = relative.as_posix()
        artifact.filename = filename
        artifact.file_size = result.file_size
        artifact.download_status = DownloadStatus.DOWNLOADED
        artifact.downloaded_at = beijing_now()
        artifact.resolved_url = result.resolved_url
        artifact.md5 = SelfHostedPanProvider._md5(manager.root / relative)
        local = db.scalar(select(ArtifactStorage).where(ArtifactStorage.artifact_id == artifact.id,
            ArtifactStorage.provider == StorageProviderType.LOCAL).limit(1))
        if local is None:
            local = ArtifactStorage(artifact_id=artifact.id, provider=StorageProviderType.LOCAL)
            db.add(local)
        local.remote_path = relative.as_posix()
        local.status = StorageStatus.AVAILABLE
        job.result = {"bytes_downloaded": result.file_size, "total_bytes": result.file_size,
                  "speed_bytes_per_second": round(result.file_size / max(result.elapsed_seconds, .001)),
                  "resolved_url": result.resolved_url, "content_type": result.content_type,
                  "filename": result.filename, "elapsed_seconds": result.elapsed_seconds,
                  "http_status": result.http_status}
        db.commit()
        logger.info("Download completed job_id=%s artifact_id=%s host=%s http_status=%s bytes=%s duration=%.2f",
                    job.id, artifact.id, urlsplit(result.resolved_url).hostname, result.http_status,
                    result.file_size, result.elapsed_seconds)
