"""Small bounded storage worker, replaceable with a durable queue later."""
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock

from sqlalchemy import select

from app.core.enums import JobStatus, JobType, StorageStatus, UploadStatus
from app.db.base import beijing_now
from app.db.session import SessionLocal
from app.models import ArtifactStorage, Job
from app.storage.exceptions import StorageError
from app.storage.providers.baidu_provider import BaiduPanProvider
from app.storage.providers.self_hosted_provider import SelfHostedPanProvider
from app.storage.service import run_self_hosted_upload, run_upload

logger = logging.getLogger(__name__)
_executor: ThreadPoolExecutor | None = None
_slots = BoundedSemaphore(100)
_lock = Lock()


def enqueue(job_id: int) -> bool:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="storage")
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
        for job in db.scalars(select(Job).where(Job.job_type == JobType.UPLOAD_STORAGE,
                                                Job.status == JobStatus.RUNNING)):
            job.status = JobStatus.FAILED
            job.error_message = "INTERRUPTED: backend restarted during upload; retry is available"
            job.finished_at = beijing_now()
            storage = db.get(ArtifactStorage, (job.payload or {}).get("storage_id"))
            if storage:
                storage.upload_status = UploadStatus.FAILED
                storage.status = StorageStatus.FAILED
        db.commit()
        pending = list(db.scalars(select(Job.id).where(Job.job_type == JobType.UPLOAD_STORAGE,
                                                    Job.status == JobStatus.PENDING)))
    for job_id in pending:
        enqueue(job_id)


def _run(job_id: int) -> None:
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if not job or job.status != JobStatus.PENDING:
                return
            job.status = JobStatus.RUNNING
            job.started_at = beijing_now()
            provider_type = (job.payload or {}).get("provider", "BAIDU")
            job.message = "Uploading to self-hosted cloud drive" if provider_type == "SELF_HOSTED" else "Uploading to Baidu Pan"
            db.commit()
            provider = None
            try:
                if provider_type == "SELF_HOSTED":
                    provider = SelfHostedPanProvider()
                    run_self_hosted_upload(db, job, provider)
                elif provider_type == "BAIDU":
                    provider = BaiduPanProvider()
                    run_upload(db, job, provider)
                else:
                    raise StorageError("UNSUPPORTED_PROVIDER", f"Unsupported storage provider: {provider_type}")
                job.status = JobStatus.SUCCESS
                job.progress = 100
                job.message = "Upload complete"
                job.finished_at = beijing_now()
                db.commit()
            except StorageError as exc:
                db.rollback()
                logger.warning("Storage job failed job_id=%s artifact_id=%s provider=%s code=%s",
                               job_id, job.target_id, provider_type, exc.code, exc_info=True)
                _fail(db, job_id, exc.code, exc.message)
            except Exception:
                db.rollback()
                logger.exception("Storage job failed job_id=%s", job_id)
                _fail(db, job_id, "UNKNOWN_ERROR", "Unexpected storage worker error")
            finally:
                if provider is not None:
                    provider.close()
    finally:
        _slots.release()


def _fail(db, job_id: int, code: str, message: str) -> None:
    job = db.get(Job, job_id)
    if not job:
        return
    job.status = JobStatus.FAILED
    job.error_message = f"{code}: {message}"[:2000]
    job.message = "Upload failed"
    job.finished_at = beijing_now()
    storage = db.get(ArtifactStorage, (job.payload or {}).get("storage_id"))
    if storage:
        storage.upload_status = UploadStatus.FAILED
        storage.status = StorageStatus.FAILED
    db.commit()
