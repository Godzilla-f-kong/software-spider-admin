import logging
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from threading import BoundedSemaphore, Lock

from sqlalchemy import select

from app.core.config import settings
from app.core.enums import DownloadStatus, JobStatus, JobType, VerificationStatus
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


def worker_concurrency() -> int:
    return _configured_concurrency or settings.download_max_concurrency


def enqueue(job_id: int) -> bool:
    global _executor, _slots, _configured_concurrency
    with _lock:
        if _executor is None:
            _configured_concurrency = max(1, settings.download_max_concurrency)
            _executor = ThreadPoolExecutor(max_workers=_configured_concurrency, thread_name_prefix="download")
            _slots = BoundedSemaphore(1002)
    assert _slots is not None
    if not _slots.acquire(blocking=False):
        return False
    try:
        _executor.submit(_run, job_id)
        return True
    except RuntimeError:
        _slots.release()
        return False


def recover_interrupted() -> None:
    pending: list[int] = []
    with SessionLocal() as db:
        jobs = db.scalars(select(Job).where(Job.job_type.in_([JobType.DOWNLOAD, JobType.VERIFY]),
                                               Job.status == JobStatus.RUNNING)).all()
        for job in jobs:
            job.status = JobStatus.FAILED
            job.error_message = "INTERRUPTED: Backend stopped while this job was running; retry to resume"
            job.finished_at = beijing_now()
            artifact = db.get(SoftwareArtifact, job.target_id)
            if artifact and job.job_type is JobType.DOWNLOAD:
                artifact.download_status = DownloadStatus.DOWNLOADED if artifact.local_path else DownloadStatus.FAILED
            if artifact and job.job_type is JobType.VERIFY:
                artifact.verification_status = VerificationStatus.MANUAL_REVIEW
        db.commit()
        pending = list(db.scalars(select(Job.id).where(Job.job_type.in_([JobType.DOWNLOAD, JobType.VERIFY]),
                                                  Job.status == JobStatus.PENDING)))
    for job_id in pending:
        enqueue(job_id)


def _run(job_id: int) -> None:
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None or job.status is not JobStatus.PENDING:
                return
            artifact = db.get(SoftwareArtifact, job.target_id)
            if artifact is None:
                _fail(db, job_id, DownloadError("VERIFICATION_FAILED", "Artifact no longer exists"))
                return
            logger.info("Artifact job started job_id=%s artifact_id=%s type=%s host=%s",
                        job.id, artifact.id, job.job_type.value, urlsplit(artifact.source_url or "").hostname)
            job.status = JobStatus.RUNNING
            job.started_at = beijing_now()
            job.message = "Starting download" if job.job_type is JobType.DOWNLOAD else "Verifying file"
            if job.job_type is JobType.DOWNLOAD:
                artifact.download_status = DownloadStatus.DOWNLOADING
            else:
                artifact.verification_status = VerificationStatus.VERIFYING
            db.commit()
            try:
                if job.job_type is JobType.DOWNLOAD:
                    DownloadService(enqueue).download(db, job, artifact)
                elif job.job_type is JobType.VERIFY:
                    DownloadService(enqueue).verify(db, job, artifact)
                job.status = JobStatus.SUCCESS
                job.progress = 100
                job.message = "Complete"
                job.finished_at = beijing_now()
                db.commit()
                logger.info("Artifact job completed job_id=%s artifact_id=%s type=%s result=%s",
                            job.id, artifact.id, job.job_type.value, artifact.verification_status.value)
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


def _fail(db, job_id: int, exc: DownloadError) -> None:
    job = db.get(Job, job_id)
    if job is None:
        return
    artifact = db.get(SoftwareArtifact, job.target_id)
    job.status = JobStatus.CANCELLED if exc.code == "CANCELLED" else JobStatus.FAILED
    job.error_message = f"{exc.code}: {exc.message}"[:2000]
    job.message = "Cancelled" if exc.code == "CANCELLED" else "Failed"
    job.finished_at = beijing_now()
    if artifact and job.job_type is JobType.DOWNLOAD:
        artifact.download_status = DownloadStatus.DOWNLOADED if artifact.local_path else DownloadStatus.FAILED
    if artifact and job.job_type is JobType.VERIFY:
        artifact.verification_status = VerificationStatus.MANUAL_REVIEW
    db.commit()
    logger.warning("Artifact job ended job_id=%s artifact_id=%s error_type=%s", job.id, job.target_id, exc.code)

