"""Serial worker for registering scraped share links with the self-hosted cloud."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.enums import JobStatus, JobType, ShareLinkSubmissionStatus
from app.db.base import beijing_now
from app.db.session import SessionLocal
from app.models import Job, ShareLinkSubmission
from app.storage.share_link_registry import (mark_job_running, request_payload, save_failure,
                                              save_success)

_executor: ThreadPoolExecutor | None = None
_lock = Lock()


def enqueue(job_id: int) -> bool:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="share-link")
        try:
            _executor.submit(_run, job_id)
            return True
        except RuntimeError:
            return False


def recover_interrupted() -> None:
    pending: list[int] = []
    with SessionLocal() as db:
        for job in db.scalars(select(Job).where(Job.job_type == JobType.REGISTER_SHARE_LINK,
                                                Job.status == JobStatus.RUNNING)):
            job.status = JobStatus.FAILED
            job.error_message = "INTERRUPTED: registration outcome must be checked before retry"
            job.message = "Registration interrupted; cloud may already have accepted the link"
            job.finished_at = beijing_now()
            row = db.get(ShareLinkSubmission, job.target_id)
            if row:
                row.status = ShareLinkSubmissionStatus.UNKNOWN
                row.error_message = job.error_message
        db.commit()
        pending = list(db.scalars(select(Job.id).where(Job.job_type == JobType.REGISTER_SHARE_LINK,
            Job.status == JobStatus.PENDING).order_by(Job.id)))
    for job_id in pending:
        enqueue(job_id)


def _run(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        row = db.get(ShareLinkSubmission, job.target_id) if job else None
        if not job or not row or job.status != JobStatus.PENDING:
            return
        if not settings.cloud_integration_api_key:
            save_failure(db, job, row, "NOT_CONFIGURED", "Set CLOUD_INTEGRATION_API_KEY in .env")
            return
        if not settings.self_hosted_base_url:
            save_failure(db, job, row, "NOT_CONFIGURED", "Set SELF_HOSTED_BASE_URL in .env")
            return
        path = settings.cloud_sharelink_path.strip()
        if not path.startswith("/") or path.startswith("//"):
            save_failure(db, job, row, "INVALID_ENDPOINT", "Cloud sharelink path must be an absolute local path")
            return
        mark_job_running(db, job, row)
        url = settings.self_hosted_base_url.rstrip("/") + path
        try:
            # This service is commonly hosted on the local network. Bypass machine-wide
            # proxy settings so private cloud addresses are reached directly.
            with httpx.Client(timeout=settings.self_hosted_timeout, follow_redirects=False,
                              trust_env=False) as client:
                response = client.post(url, headers={
                    "X-Integration-Key": settings.cloud_integration_api_key,
                    "Content-Type": "application/json",
                }, json=request_payload(row))
            if response.status_code < 200 or response.status_code >= 300:
                # Never follow a redirect with the integration key.
                body = ""
                try:
                    payload = response.json()
                    body = str(payload.get("message") or payload.get("error") or "")[:500]
                except ValueError:
                    body = response.text[:300]
                save_failure(db, job, row, f"HTTP_{response.status_code}", body or "Cloud API rejected request")
                return
            envelope = response.json()
            if envelope.get("code") != 200 or not isinstance(envelope.get("data"), dict):
                save_failure(db, job, row, "INVALID_RESPONSE", str(envelope.get("message", "Invalid cloud response"))[:500])
                return
            data = envelope["data"]
            if not data.get("id") or not data.get("link"):
                save_failure(db, job, row, "INVALID_RESPONSE", "Cloud response lacks record id or share link")
                return
            # Persist only the documented response fields; do not retain arbitrary server payloads.
            safe_response = {key: data.get(key) for key in (
                "id", "token", "extractCode", "filename", "filetype", "file_arch", "os",
                "architecture", "md5", "install_type", "filesize", "external_url", "source",
                "durationDays", "expireTime", "allowDownload", "allowPreview", "visitLimit", "link", "reused")}
            save_success(db, job, row, safe_response)
        except httpx.TimeoutException:
            db.rollback()
            row = db.get(ShareLinkSubmission, job.target_id)
            job = db.get(Job, job_id)
            if row and job:
                save_failure(db, job, row, "TIMEOUT", "Cloud response timed out; check the cloud before retrying", unknown=True)
        except httpx.HTTPError as exc:
            db.rollback()
            row = db.get(ShareLinkSubmission, job.target_id)
            job = db.get(Job, job_id)
            if row and job:
                save_failure(db, job, row, "NETWORK_ERROR", type(exc).__name__, unknown=True)
        except Exception:
            db.rollback()
            row = db.get(ShareLinkSubmission, job.target_id)
            job = db.get(Job, job_id)
            if row and job:
                save_failure(db, job, row, "UNKNOWN_ERROR", "Unexpected cloud registration worker error", unknown=True)
