import logging
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from threading import BoundedSemaphore, Lock

from sqlalchemy import select

from app.core.config import settings
from app.core.enums import DownloadStatus, JobStatus, JobType
from app.db.base import beijing_now
from app.db.session import SessionLocal
from app.downloader.errors import DownloadError
from app.models import Job, SoftwareArtifact
from app.services.download_service import DownloadService

logger = logging.getLogger(__name__)
_executor: ThreadPoolExecutor | None = None
_slots: BoundedSemaphore | None = None
_configured_concurrency: int | None = None
_lock = Lock()
_queued_ids: set[int] = set()
_MAX_WORKERS = 5


def worker_concurrency() -> int:
    return _configured_concurrency or max(1, min(_MAX_WORKERS, settings.download_max_concurrency))


def enqueue(job_id: int) -> bool:
    global _executor, _slots, _configured_concurrency
    with _lock:
        if job_id in _queued_ids:
            return True
        if _executor is None:
            _configured_concurrency = max(1, min(_MAX_WORKERS, settings.download_max_concurrency))
            _executor = ThreadPoolExecutor(max_workers=_configured_concurrency, thread_name_prefix="download")
            _slots = BoundedSemaphore(_configured_concurrency)
        assert _slots is not None
        if not _slots.acquire(blocking=False):
            return False
        _queued_ids.add(job_id)
        try:
            _executor.submit(_run, job_id)
            return True
        except RuntimeError:
            _queued_ids.discard(job_id)
            _slots.release()
            return False


def recover_interrupted() -> None:
    pending: list[int] = []
    with SessionLocal() as db:
        retired_verifications = db.scalars(select(Job).where(
            Job.job_type == JobType.VERIFY,
            Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
        )).all()
        for job in retired_verifications:
            job.status = JobStatus.CANCELLED
            job.message = "Verification workflow retired"
            job.error_message = None
            job.finished_at = beijing_now()
        jobs = db.scalars(select(Job).where(Job.job_type == JobType.DOWNLOAD,
                                               Job.status == JobStatus.RUNNING)).all()
        for job in jobs:
            if job.target_type == "crawl_link_download":
                job.status = JobStatus.PENDING
                job.error_message = None
                job.message = "Backend restarted; resuming automatic link download"
                job.started_at = None
            else:
                job.status = JobStatus.FAILED
                job.error_message = "INTERRUPTED: Backend stopped while this job was running; retry to resume"
                job.finished_at = beijing_now()
            artifact = db.get(SoftwareArtifact, job.target_id) if job.target_type == "artifact" else None
            if artifact and job.job_type is JobType.DOWNLOAD:
                artifact.download_status = DownloadStatus.DOWNLOADED if artifact.local_path else DownloadStatus.FAILED
        db.commit()
        pending = list(db.scalars(select(Job.id).where(Job.job_type == JobType.DOWNLOAD,
                                                  Job.status == JobStatus.PENDING)))
    for job_id in pending:
        enqueue(job_id)
def _run(job_id: int) -> None:
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None or job.status is not JobStatus.PENDING:
                return
            if job.job_type is JobType.DOWNLOAD and job.target_type == "crawl_link_download":
                job.status = JobStatus.RUNNING
                job.started_at = beijing_now()
                job.message = "Resolving and downloading discovered link"
                db.commit()
                try:
                    from app.services.crawl_link_download import CrawlLinkDownloadService
                    CrawlLinkDownloadService().download(db, job)
                    job.status = JobStatus.SUCCESS
                    job.progress = 100
                    job.finished_at = beijing_now()
                    db.commit()
                    try:
                        from app.services.automatic_catalog import import_successful_crawl_download
                        import_successful_crawl_download(db, job)
                    except Exception:
                        db.rollback()
                        logger.exception("Downloaded crawl files could not be linked to catalog job_id=%s", job_id)
                except DownloadError as exc:
                    db.rollback()
                    _fail(db, job_id, exc)
                except Exception:
                    db.rollback()
                    logger.exception("Crawl link download failed job_id=%s", job_id)
                    _fail(db, job_id, DownloadError("UNKNOWN_ERROR", "Unexpected worker error; inspect server log"))
                return
            artifact = db.get(SoftwareArtifact, job.target_id)
            if artifact is None:
                _fail(db, job_id, DownloadError("ARTIFACT_NOT_FOUND", "Artifact no longer exists"))
                return
            logger.info("Artifact job started job_id=%s artifact_id=%s type=%s host=%s",
                        job.id, artifact.id, job.job_type.value, urlsplit(artifact.source_url or "").hostname)
            job.status = JobStatus.RUNNING
            job.started_at = beijing_now()
            job.message = "Starting download"
            if job.job_type is JobType.DOWNLOAD:
                artifact.download_status = DownloadStatus.DOWNLOADING
            db.commit()
            try:
                if job.job_type is JobType.DOWNLOAD:
                    DownloadService().download(db, job, artifact)
                job.status = JobStatus.SUCCESS
                job.progress = 100
                job.message = "Complete"
                job.finished_at = beijing_now()
                db.commit()
                logger.info("Artifact job completed job_id=%s artifact_id=%s type=%s",
                            job.id, artifact.id, job.job_type.value)
            except DownloadError as exc:
                db.rollback()
                _fail(db, job_id, exc)
            except Exception:
                db.rollback()
                logger.exception("Download job failed job_id=%s artifact_id=%s", job_id, artifact.id)
                _fail(db, job_id, DownloadError("UNKNOWN_ERROR", "Unexpected worker error; inspect server log"))
    finally:
        if _slots:
            _slots.release()
        with _lock:
            _queued_ids.discard(job_id)
        _dispatch_pending_jobs()


def _dispatch_pending_jobs() -> None:
    with SessionLocal() as db:
        pending = db.scalars(select(Job.id).where(
            Job.job_type == JobType.DOWNLOAD,
            Job.status == JobStatus.PENDING,
        ).order_by(Job.id).limit(1002)).all()
    for job_id in pending:
        if not enqueue(job_id):
            break


def _fail(db, job_id: int, exc: DownloadError) -> None:
    job = db.get(Job, job_id)
    if job is None:
        return
    artifact = db.get(SoftwareArtifact, job.target_id) if job.target_type == "artifact" else None
    job.status = JobStatus.CANCELLED if exc.code == "CANCELLED" else JobStatus.FAILED
    job.error_message = f"{exc.code}: {exc.message}"[:2000]
    job.message = "Cancelled" if exc.code == "CANCELLED" else "Failed"
    job.finished_at = beijing_now()
    if artifact and job.job_type is JobType.DOWNLOAD:
        artifact.download_status = DownloadStatus.DOWNLOADED if artifact.local_path else DownloadStatus.FAILED
    db.commit()
    logger.warning("Artifact job ended job_id=%s artifact_id=%s error_type=%s", job.id, job.target_id, exc.code)
