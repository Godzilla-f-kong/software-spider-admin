"""Prepare and queue public cloud-share links for the cloud's permanent-link API."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import enums as e
from app.core.config import settings
from app.db.base import beijing_now
from app.models import DownloadLink, Job, ShareLinkSubmission, Software, SoftwareCandidate
from app.storage.self_hosted_categories import SELF_HOSTED_FILE_ARCH_CATEGORIES

SHARE_CODE = re.compile(r"^[A-Za-z0-9]{4}$")


def _fingerprint(url: str, code: str | None) -> str:
    # The cloud service reuses by the exact external URL and share code.
    return hashlib.sha256(f"{url.strip()}\x1f{(code or '').strip()}".encode("utf-8")).hexdigest()


def validate_share_data(name: str, url: str, code: str | None) -> list[str]:
    errors: list[str] = []
    if not name.strip():
        errors.append("缺少软件名称")
    if len(name.strip()) > 255:
        errors.append("软件名称超过 255 个字符")
    try:
        parsed = urlsplit(url.strip())
        if (len(url.strip()) > 2048 or parsed.scheme.lower() not in {"http", "https"}
                or not parsed.hostname or parsed.username or parsed.password):
            raise ValueError
    except ValueError:
        errors.append("外链必须是无账号密码的绝对 HTTP/HTTPS URL，且不超过 2048 个字符")
    if not code or not SHARE_CODE.fullmatch(code.strip()):
        errors.append("分享码必须是 4 位字母或数字")
    return errors


def _category(value: str | None) -> str | None:
    return value if value in SELF_HOSTED_FILE_ARCH_CATEGORIES else None


def _upsert(db: Session, *, name: str, url: str, code: str | None,
            provider: str | None = None, source_page_url: str | None = None,
            download_link_id: int | None = None, crawl_job_id: int | None = None,
            candidate_id: int | None = None, software_id: int | None = None,
            filename: str | None = None, file_arch: str | None = None,
            os: str | None = None, architecture: str | None = None,
            md5: str | None = None, install_type: int | None = None,
            filesize: int | None = None, filetype: int = 5) -> ShareLinkSubmission:
    normalized_url = url.strip()
    clean_code = code.strip() if code and code.strip() else None
    fingerprint = _fingerprint(normalized_url, clean_code)
    row = next((pending for pending in db.new
                if isinstance(pending, ShareLinkSubmission)
                and (pending.fingerprint == fingerprint
                     or (download_link_id is not None and pending.download_link_id == download_link_id))), None)
    if row is None:
        row = db.scalar(select(ShareLinkSubmission).where(
            ShareLinkSubmission.fingerprint == fingerprint).with_for_update())
    if row is None and download_link_id is not None:
        row = db.scalar(select(ShareLinkSubmission).where(
            ShareLinkSubmission.download_link_id == download_link_id).with_for_update())
    errors = validate_share_data(name, normalized_url, clean_code)
    if row is None:
        row = ShareLinkSubmission(fingerprint=fingerprint, software_name=name.strip()[:255],
                                  external_url=normalized_url[:2048], extract_code=clean_code,
                                  filetype=filetype)
        db.add(row)
    row.fingerprint = fingerprint
    row.software_name = name.strip()[:255]
    row.external_url = normalized_url[:2048]
    row.extract_code = clean_code
    row.provider = provider or row.provider
    row.source_page_url = source_page_url or row.source_page_url
    row.download_link_id = download_link_id or row.download_link_id
    row.crawl_job_id = crawl_job_id or row.crawl_job_id
    row.candidate_id = candidate_id or row.candidate_id
    row.software_id = software_id or row.software_id
    row.filename = (filename or row.filename or None)
    row.file_arch = _category(file_arch) or row.file_arch
    row.os = os or row.os
    row.architecture = architecture or row.architecture
    row.md5 = md5 or row.md5
    row.install_type = install_type if install_type is not None else row.install_type
    row.filesize = filesize if filesize is not None else row.filesize
    row.filetype = filetype
    row.validation_errors = errors
    if row.status not in {e.ShareLinkSubmissionStatus.SUCCESS, e.ShareLinkSubmissionStatus.RUNNING,
                          e.ShareLinkSubmissionStatus.QUEUED}:
        row.status = e.ShareLinkSubmissionStatus.INCOMPLETE if errors else e.ShareLinkSubmissionStatus.READY
        row.error_message = None
    return row


def prepare_download_link(db: Session, link: DownloadLink) -> ShareLinkSubmission | None:
    if link.link_type != e.DownloadLinkType.PAN_SHARE:
        return None
    software = db.get(Software, link.software_id)
    if software is None:
        return None
    return _upsert(db, name=software.name, url=link.link_url, code=link.access_code,
                   provider=link.provider.value, source_page_url=link.source_page_url,
                   download_link_id=link.id, software_id=software.id,
                   file_arch=_category(software.category))


def prepare_crawl_job(db: Session, crawl_job: Job) -> int:
    result = crawl_job.result or {}
    links: list[dict] = []
    matches = list(result.get("matches", []))
    for pool_result in result.get("pool_results", []):
        matches.extend(pool_result.get("matches", []))
    for match in matches:
        for link in match.get("links", []):
            if link.get("link_type") == e.DownloadLinkType.PAN_SHARE.value:
                links.append({**link, "software_name": match.get("candidate_name"),
                              "source_page_url": match.get("page_url"),
                              "candidate_id": match.get("candidate_id"),
                              "target_os": match.get("target_os"),
                              "target_architecture": match.get("target_architecture")})
    count = 0
    for link in links:
        name, url = link.get("software_name"), link.get("url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        candidate = db.get(SoftwareCandidate, link.get("candidate_id")) if link.get("candidate_id") else None
        software_id = (crawl_job.result or {}).get("software_id")
        software = db.get(Software, software_id) if software_id else None
        _upsert(db, name=name, url=url, code=link.get("access_code"),
                provider=link.get("provider"), source_page_url=link.get("source_page_url"),
                crawl_job_id=crawl_job.id,
                candidate_id=link.get("candidate_id"),
                software_id=software_id,
                file_arch=_category((software.category if software else None)
                                    or (candidate.category if candidate else None)),
                os=_api_os(link.get("target_os")),
                architecture=_api_architecture(link.get("target_architecture")))
        count += 1
    return count


def scan_existing_links(db: Session) -> dict[str, int]:
    scanned = prepared = incomplete = 0
    for link in db.scalars(select(DownloadLink).order_by(DownloadLink.id)).yield_per(500):
        row = prepare_download_link(db, link)
        if row is None:
            continue
        scanned += 1
        prepared += row.status != e.ShareLinkSubmissionStatus.INCOMPLETE
        incomplete += row.status == e.ShareLinkSubmissionStatus.INCOMPLETE
    # Job results preserve candidate-pool discoveries that have not been imported as catalog links.
    jobs = db.scalars(select(Job).where(Job.job_type == e.JobType.CRAWL,
        Job.target_type.in_(["candidate_auto_search", "crawl_pool"]), Job.result.is_not(None))
        .order_by(Job.id)).yield_per(100)
    for job in jobs:
        count = prepare_crawl_job(db, job)
        scanned += count
    db.flush()
    prepared = db.scalar(select(func.count()).select_from(ShareLinkSubmission).where(
        ShareLinkSubmission.status == e.ShareLinkSubmissionStatus.READY)) or 0
    incomplete = db.scalar(select(func.count()).select_from(ShareLinkSubmission).where(
        ShareLinkSubmission.status == e.ShareLinkSubmissionStatus.INCOMPLETE)) or 0
    db.commit()
    return {"scanned": scanned, "ready": prepared, "incomplete": incomplete}


def _api_os(value: str | None) -> str | None:
    return {"WINDOWS": "Windows", "LINUX": "Linux", "MACOS": "macOS", "ANDROID": "Android",
            "OTHER": "Other"}.get(value or "", value)


def _api_architecture(value: str | None) -> str | None:
    return {"X86": "x86", "X64": "x64", "ARM": "ARM", "ARM64": "ARM64",
            "UNIVERSAL": "Universal", "OTHER": "Other"}.get(value or "", value)


def queue_submission(db: Session, submission: ShareLinkSubmission) -> Job:
    if submission.status not in {e.ShareLinkSubmissionStatus.READY, e.ShareLinkSubmissionStatus.FAILED,
                                  e.ShareLinkSubmissionStatus.UNKNOWN}:
        raise ValueError("Share link is not ready for registration")
    errors = validate_share_data(submission.software_name, submission.external_url, submission.extract_code)
    if errors:
        submission.status = e.ShareLinkSubmissionStatus.INCOMPLETE
        submission.validation_errors = errors
        raise ValueError("Share link is incomplete")
    active = db.scalar(select(Job.id).where(Job.job_type == e.JobType.REGISTER_SHARE_LINK,
        Job.target_type == "share_link_submission", Job.target_id == submission.id,
        Job.status.in_([e.JobStatus.PENDING, e.JobStatus.RUNNING])).limit(1))
    if active:
        return db.get(Job, active)
    job = Job(job_type=e.JobType.REGISTER_SHARE_LINK, target_type="share_link_submission",
              target_id=submission.id, status=e.JobStatus.PENDING, progress=0,
              message="Waiting to register cloud share link", payload={"submission_id": submission.id})
    db.add(job)
    submission.status = e.ShareLinkSubmissionStatus.QUEUED
    submission.error_message = None
    db.flush()
    return job


def update_submission(db: Session, submission: ShareLinkSubmission, changes: dict) -> ShareLinkSubmission:
    if submission.status in {e.ShareLinkSubmissionStatus.QUEUED, e.ShareLinkSubmissionStatus.RUNNING,
                             e.ShareLinkSubmissionStatus.SUCCESS}:
        raise ValueError("Queued or registered share links cannot be edited")
    name = str(changes.get("software_name", submission.software_name) or "").strip()
    url = str(changes.get("external_url", submission.external_url) or "").strip()
    raw_code = changes.get("extract_code", submission.extract_code)
    code = raw_code.strip() if isinstance(raw_code, str) and raw_code.strip() else None
    if len(name) > 255 or len(url) > 2048:
        raise ValueError("Name or URL exceeds the cloud service limit")
    fingerprint = _fingerprint(url, code)
    duplicate = db.scalar(select(ShareLinkSubmission.id).where(
        ShareLinkSubmission.fingerprint == fingerprint,
        ShareLinkSubmission.id != submission.id).limit(1))
    if duplicate:
        raise ValueError(f"Duplicate of registration record #{duplicate}")
    submission.software_name = name
    submission.external_url = url
    submission.extract_code = code
    for field in ("filename", "file_arch", "os", "architecture"):
        if field in changes:
            setattr(submission, field, changes[field])
    if submission.file_arch and submission.file_arch not in SELF_HOSTED_FILE_ARCH_CATEGORIES:
        raise ValueError("Invalid cloud file category")
    submission.fingerprint = fingerprint
    errors = validate_share_data(name, url, code)
    submission.validation_errors = errors
    submission.status = (e.ShareLinkSubmissionStatus.INCOMPLETE if errors
                         else e.ShareLinkSubmissionStatus.READY)
    submission.error_message = None
    db.commit()
    db.refresh(submission)
    return submission


def request_payload(row: ShareLinkSubmission) -> dict:
    data: dict[str, object] = {
        "softwareName": row.software_name,
        "external_url": row.external_url,
        "extractCode": row.extract_code,
        "filetype": row.filetype,
    }
    for key, value in (("filename", row.filename), ("file_arch", row.file_arch),
                       ("os", row.os), ("architecture", row.architecture),
                       ("md5", row.md5), ("install_type", row.install_type),
                       ("filesize", row.filesize)):
        if value is not None:
            data[key] = value
    return data


def mark_job_running(db: Session, job: Job, row: ShareLinkSubmission) -> None:
    job.status = e.JobStatus.RUNNING
    job.started_at = beijing_now()
    job.progress = 20
    job.message = "Registering permanent cloud share link"
    row.status = e.ShareLinkSubmissionStatus.RUNNING
    db.commit()


def save_success(db: Session, job: Job, row: ShareLinkSubmission, response: dict) -> None:
    row.status = e.ShareLinkSubmissionStatus.SUCCESS
    row.cloud_record_id = response.get("id")
    row.cloud_token = response.get("token")
    row.cloud_link = response.get("link")
    row.cloud_reused = bool(response.get("reused", False))
    row.cloud_response = response
    row.error_message = None
    job.status = e.JobStatus.SUCCESS
    job.progress = 100
    job.message = "Cloud share link registered" if not row.cloud_reused else "Existing cloud share link reused"
    job.result = {"submission_id": row.id, "cloud_record_id": row.cloud_record_id,
                  "cloud_link": row.cloud_link, "reused": row.cloud_reused}
    job.finished_at = beijing_now()
    db.commit()


def save_failure(db: Session, job: Job, row: ShareLinkSubmission, code: str, message: str,
                 unknown: bool = False) -> None:
    row.status = e.ShareLinkSubmissionStatus.UNKNOWN if unknown else e.ShareLinkSubmissionStatus.FAILED
    row.error_message = f"{code}: {message}"[:2000]
    job.status = e.JobStatus.FAILED
    job.error_message = row.error_message
    job.message = "Cloud share link registration outcome unknown" if unknown else "Cloud share link registration failed"
    job.finished_at = beijing_now()
    db.commit()


def enqueue_ready(db: Session) -> list[Job]:
    jobs: list[Job] = []
    rows = db.scalars(select(ShareLinkSubmission).where(
        ShareLinkSubmission.status == e.ShareLinkSubmissionStatus.READY).order_by(ShareLinkSubmission.id))
    for row in rows:
        try:
            jobs.append(queue_submission(db, row))
        except ValueError:
            continue
    db.commit()
    return jobs
