from dataclasses import dataclass
from typing import Any
import hashlib
import secrets
import time

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
import ipaddress
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core import enums as e
from app.db.session import get_db
from app.models import (ArtifactStorage, CommerceListing, CrawlPool, DownloadLink, GeneratedContent, Job, Software, StorageAccount,
                        SoftwareArtifact, SoftwareCandidate, SoftwareRelease, SoftwareSource, SoftwareVariant)
from app.repositories.crud import Repository
from app.schemas import entities as s
from app.services.catalog import accept_candidate, create_artifact_job, set_latest_release
from app.services.transitions import validate_artifact_state, validate_transition
from app.services.validation import ensure_relations
from app.services.lookups import LOOKUP_MODELS, find_lookups
from app.db.base import beijing_now
from app.jobs.spider_runner import enqueue, schedule_automatic_candidate_searches, worker_concurrency
from app.jobs.download_runner import enqueue as enqueue_download, worker_concurrency as download_worker_concurrency
from app.jobs.storage_runner import enqueue as enqueue_storage
from app.storage.exceptions import StorageError
from app.storage.providers.baidu_provider import BaiduPanProvider
from app.storage.service import (queue_upload, queue_self_hosted_upload, save_oauth_account,
                                 create_share as storage_create_share, disable_share as storage_disable_share)
from app.storage.self_hosted_categories import SELF_HOSTED_FILE_ARCH_CATEGORIES
from app.storage.archive import ArchiveManager
from app.storage.local_directory import archived_file_for_storage, open_local_directory
from app.downloader.staging import StagingManager
from app.downloader.errors import DownloadError
from app.services.system_settings import SettingsPatch, effective_data_path, save_overrides
from app.spider.normalizers import URLNormalizer, URLSafetyValidator


router = APIRouter(prefix="/api/v1")
_oauth_states: dict[str, float] = {}


def storage_http_error(exc: StorageError) -> HTTPException:
    return HTTPException(501 if exc.code == "NOT_SUPPORTED_BY_OPEN_API" else
                         409 if exc.code in {"ALREADY_UPLOADED", "UPLOAD_IN_PROGRESS", "NOT_VERIFIED", "REDISTRIBUTION_NOT_ALLOWED", "ALREADY_SHARED", "NOT_SHARED"} else 422,
                         f"{exc.code}: {exc.message}")


@dataclass(frozen=True)
class Resource:
    path: str
    model: type
    write: type
    read: type
    search: tuple[str, ...]
    filters: tuple[str, ...]
    sort: tuple[str, ...] = ("id", "created_at", "updated_at")


RESOURCES = [
    Resource("candidates", SoftwareCandidate, s.CandidateWrite, s.CandidateRead, ("name", "normalized_name"), ("status", "category"), ("id", "name", "priority_score", "created_at", "updated_at")),
    Resource("software", Software, s.SoftwareWrite, s.SoftwareRead, ("name", "slug", "developer"), ("status", "category"), ("id", "name", "created_at", "updated_at")),
    Resource("sources", SoftwareSource, s.SourceWrite, s.SourceRead, (), ("software_id", "source_type", "status", "enabled")),
    Resource("releases", SoftwareRelease, s.ReleaseWrite, s.ReleaseRead, ("version",), ("software_id", "status")),
    Resource("variants", SoftwareVariant, s.VariantWrite, s.VariantRead, (), ("release_id", "os", "architecture")),
    Resource("artifacts", SoftwareArtifact, s.ArtifactWrite, s.ArtifactRead, ("filename",), ("variant_id", "download_status", "verification_status")),
    Resource("links", DownloadLink, s.DownloadLinkWrite, s.DownloadLinkRead, ("link_url", "label"), ("software_id", "source_id", "release_id", "provider", "link_type", "review_status")),
    Resource("storage", ArtifactStorage, s.StorageWrite, s.StorageRead, (), ("artifact_id", "provider", "status")),
    Resource("content", GeneratedContent, s.ContentWrite, s.ContentRead, ("title",), ("software_id", "release_id", "content_type", "status")),
    Resource("listings", CommerceListing, s.ListingWrite, s.ListingRead, ("title",), ("software_id", "release_id", "platform", "status")),
    Resource("crawl-pools", CrawlPool, s.CrawlPoolWrite, s.CrawlPoolRead, ("base_url",), ("enabled", "status")),
    Resource("jobs", Job, s.JobWrite, s.JobRead, ("message",), ("job_type", "status", "target_type", "target_id")),
]


def fail_validation(exc: ValidationError) -> None:
    raise HTTPException(422, [{"field": ".".join(str(x) for x in error["loc"]), "message": error["msg"]} for error in exc.errors()])


def serialize(resource: Resource, item: Any, db: Session) -> dict[str, Any]:
    data = resource.read.model_validate(item).model_dump(mode="json")
    if resource.model is Software:
        latest = db.scalar(select(SoftwareRelease.version).where(
            SoftwareRelease.software_id == item.id, SoftwareRelease.is_latest.is_(True)).limit(1))
        data["latest_release"] = latest
    if resource.model is SoftwareArtifact:
        try:
            path = ArchiveManager().resolve_relative(item.local_path) if item.local_path else None
        except ValueError:
            path = None
            data["local_path"] = None
        data["local_exists"] = bool(path and path.is_file())
        data["staging_exists"] = StagingManager().complete(item.id).is_file()
    if resource.model is ArtifactStorage:
        data["local_exists"] = archived_file_for_storage(item) is not None
    if resource.model is Job:
        result = item.result or {}
        data["bytes_downloaded"] = result.get("bytes_downloaded")
        data["total_bytes"] = result.get("total_bytes")
        data["speed_bytes_per_second"] = result.get("speed_bytes_per_second")
        if item.target_type == "candidate_auto_search":
            data["target_label"] = (item.payload or {}).get("candidate", {}).get("name") or f"Candidate #{item.target_id}"
    if resource.model is SoftwareCandidate:
        data.update(automatic_crawl_job_id=None, automatic_crawl_status="WAITING_FOR_URL_POOL",
                    automatic_crawl_message=None)
    return data


def attach_automatic_crawl_status(data: dict[str, Any], candidate_id: int,
                                  db: Session) -> dict[str, Any]:
    latest = db.execute(select(Job.id, Job.status, Job.message).where(
        Job.job_type == e.JobType.CRAWL, Job.target_type == "candidate_auto_search",
        Job.target_id == candidate_id).order_by(Job.id.desc()).limit(1)).first()
    if latest:
        data.update(automatic_crawl_job_id=latest.id, automatic_crawl_status=latest.status.value,
                    automatic_crawl_message=latest.message)
    return data


def create_resource_routes(resource: Resource) -> None:
    path = f"/{resource.path}"

    def list_items(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   search: str | None = None, sort: str = "-created_at",
                   status: str | None = None, category: str | None = None,
                   software_id: int | None = None, release_id: int | None = None,
                   variant_id: int | None = None, artifact_id: int | None = None,
                   source_id: int | None = None, link_type: str | None = None,
                   review_status: str | None = None,
                   content_type: str | None = None, platform: str | None = None,
                   provider: str | None = None, source_type: str | None = None,
                   os: str | None = None, architecture: str | None = None,
                   download_status: str | None = None, verification_status: str | None = None,
                   job_type: str | None = None, target_type: str | None = None,
                   target_id: int | None = None, enabled: bool | None = None,
                   db: Session = Depends(get_db)) -> dict[str, Any]:
        if sort.lstrip("-") not in resource.sort:
            raise HTTPException(422, "Invalid sort field")
        supplied = locals()
        filters = {key: supplied[key] for key in resource.filters if supplied[key] is not None}
        rows, total = Repository(db, resource.model).list(page=page, page_size=page_size,
                search=search, search_fields=resource.search, filters=filters, sort=sort)
        items = [serialize(resource, row, db) for row in rows]
        if resource.model is SoftwareCandidate and rows:
            latest_jobs = db.execute(select(Job.target_id, Job.id, Job.status, Job.message).where(
                Job.job_type == e.JobType.CRAWL, Job.target_type == "candidate_auto_search",
                Job.target_id.in_([row.id for row in rows])).order_by(Job.id.desc())).all()
            by_candidate = {}
            for latest in latest_jobs:
                by_candidate.setdefault(latest.target_id, latest)
            for row, data in zip(rows, items):
                latest = by_candidate.get(row.id)
                if latest:
                    data.update(automatic_crawl_job_id=latest.id, automatic_crawl_status=latest.status.value,
                                automatic_crawl_message=latest.message)
        return {"items": items, "total": total,
                "page": page, "page_size": page_size}

    def create_item(payload: dict[str, Any] = Body(...), db: Session = Depends(get_db)) -> dict[str, Any]:
        if resource.model is Job:
            if payload.get("job_type") in {"DOWNLOAD", "VERIFY", "UPLOAD_STORAGE", "UPLOAD_BAIDU"}:
                raise HTTPException(422, "Use the Artifact Download or Verify action")
            payload = {key: value for key, value in payload.items() if key in s.JobWrite.model_fields}
        if resource.model is ArtifactStorage and payload.get("provider") in {"LOCAL", "BAIDU"}:
            raise HTTPException(422, "LOCAL and BAIDU storage are managed by workers")
        try:
            parsed = resource.write.model_validate(payload)
        except ValidationError as exc:
            fail_validation(exc)
        data = parsed.model_dump(exclude_unset=True)
        if resource.model is SoftwareArtifact:
            if data.get("download_status") not in {None, e.DownloadStatus.NOT_DOWNLOADED} or data.get("verification_status") not in {None, e.VerificationStatus.PENDING} or any(data.get(key) for key in ("local_path", "sha256", "md5")):
                raise HTTPException(422, "New artifacts must begin undownloaded and unverified")
        if resource.model is SoftwareCandidate:
            data["normalized_name"] = (data.get("normalized_name") or data["name"]).strip().casefold()
            if data.get("status") == e.CandidateStatus.ACCEPTED:
                raise HTTPException(422, "Use the accept action")
        if resource.model is CrawlPool:
            try:
                data["base_url"] = URLSafetyValidator(settings.allow_private_source_urls).validate(data["base_url"])
            except Exception as exc:
                raise HTTPException(422, "Invalid or unsafe website URL") from exc
            data["url_hash"] = hashlib.sha256(data["base_url"].encode()).hexdigest()
        ensure_relations(db, resource.model, data)
        try:
            item = Repository(db, resource.model).create(data)
            if resource.model is SoftwareRelease:
                set_latest_release(db, item)
            db.commit()
            db.refresh(item)
            if resource.model is SoftwareCandidate:
                schedule_automatic_candidate_searches(db, candidate_ids=[item.id])
            elif resource.model is CrawlPool and item.enabled:
                schedule_automatic_candidate_searches(db, pool_ids=[item.id])
            response = serialize(resource, item, db)
            if resource.model is SoftwareCandidate:
                attach_automatic_crawl_status(response, item.id, db)
            return response
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "Duplicate or referenced record") from exc

    def get_item(item_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
        item = Repository(db, resource.model).get(item_id)
        if item is None:
            raise HTTPException(404, f"{resource.path} item not found")
        data = serialize(resource, item, db)
        if resource.model is SoftwareCandidate:
            attach_automatic_crawl_status(data, item.id, db)
        return data

    def update_item(item_id: int, payload: dict[str, Any] = Body(...), db: Session = Depends(get_db)) -> dict[str, Any]:
        if resource.model is Job:
            raise HTTPException(405, "Jobs are managed by workers")
        item = Repository(db, resource.model).get(item_id)
        if item is None:
            raise HTTPException(404, f"{resource.path} item not found")
        if resource.model is ArtifactStorage and item.provider in {e.StorageProviderType.LOCAL, e.StorageProviderType.BAIDU}:
            raise HTTPException(409, "LOCAL and BAIDU storage are managed by workers")
        if resource.model is SoftwareCandidate and item.status == e.CandidateStatus.ACCEPTED:
            raise HTTPException(409, "Accepted candidates are read-only")
        if resource.model is SoftwareCandidate and payload.get("status") == "ACCEPTED":
            raise HTTPException(422, "Use the accept action")
        if resource.model is Software and payload.get("status") == "ARCHIVED":
            raise HTTPException(422, "Use the archive action")
        try:
            full = resource.write.model_validate({**resource.write.model_validate(item, from_attributes=True).model_dump(), **payload})
        except ValidationError as exc:
            fail_validation(exc)
        data = full.model_dump(include=set(payload))
        if "status" in data:
            validate_transition(resource.model, getattr(item, "status"), data["status"])
        if resource.model is SoftwareArtifact:
            validate_artifact_state(item, data)
        if resource.model is SoftwareCandidate and "name" in data and "normalized_name" not in data:
            data["normalized_name"] = data["name"].strip().casefold()
        if resource.model is CrawlPool and "base_url" in data:
            try:
                data["base_url"] = URLSafetyValidator(settings.allow_private_source_urls).validate(data["base_url"])
            except Exception as exc:
                raise HTTPException(422, "Invalid or unsafe website URL") from exc
            data["url_hash"] = hashlib.sha256(data["base_url"].encode()).hexdigest()
        merged = {**resource.write.model_validate(item, from_attributes=True).model_dump(), **data, "id": item.id}
        ensure_relations(db, resource.model, merged)
        try:
            Repository(db, resource.model).update(item, data)
            if resource.model is SoftwareRelease:
                set_latest_release(db, item)
            db.commit()
            db.refresh(item)
            if resource.model is CrawlPool and item.enabled and ("enabled" in data or "base_url" in data):
                schedule_automatic_candidate_searches(db, pool_ids=[item.id])
            data = serialize(resource, item, db)
            if resource.model is SoftwareCandidate:
                attach_automatic_crawl_status(data, item.id, db)
            return data
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "Duplicate or referenced record") from exc

    router.add_api_route(path, list_items, methods=["GET"], name=f"list_{resource.path}")
    router.add_api_route(path, create_item, methods=["POST"], name=f"create_{resource.path}", status_code=201)
    router.add_api_route(f"{path}/{{item_id}}", get_item, methods=["GET"], name=f"get_{resource.path}")
    router.add_api_route(f"{path}/{{item_id}}", update_item, methods=["PATCH"], name=f"update_{resource.path}")


class PoolScanRequest(BaseModel):
    candidate_ids: list[int] | None = Field(default=None, max_length=50)


def _queue_pool_scan(db: Session, pool_id: int, ids: list[int] | None) -> Job:
    target_query = select(SoftwareCandidate).where(SoftwareCandidate.status.in_([
        e.CandidateStatus.DISCOVERED, e.CandidateStatus.REVIEWING, e.CandidateStatus.ACCEPTED]))
    if ids:
        target_query = target_query.where(SoftwareCandidate.id.in_(ids))
    targets = [{"id": item.id, "name": item.name, "normalized_name": item.normalized_name,
                "status": item.status.value, "target_version": item.target_version,
                "target_os": item.target_os.value if item.target_os else None,
                "target_architecture": item.target_architecture.value if item.target_architecture else None}
               for item in db.scalars(target_query.order_by(SoftwareCandidate.id))]
    job = Job(job_type=e.JobType.CRAWL, target_type="crawl_pool", target_id=pool_id,
              status=e.JobStatus.PENDING, progress=0, message="Awaiting targeted website search",
              payload={"candidate_ids": ids, "targets": targets})
    db.add(job)
    db.commit()
    db.refresh(job)
    if not enqueue(job.id):
        job.status = e.JobStatus.FAILED
        job.error_message = "Spider queue is full"
        job.finished_at = beijing_now()
        db.commit()
    return job


@router.post("/crawl-pools/{pool_id}/scan", status_code=202)
def scan_crawl_pool(pool_id: int, request: PoolScanRequest | None = Body(None),
                    db: Session = Depends(get_db)) -> dict[str, Any]:
    pool = db.get(CrawlPool, pool_id)
    if pool is None:
        raise HTTPException(404, "Crawl pool entry not found")
    if not pool.enabled:
        raise HTTPException(409, "Crawl pool entry is disabled")
    if not settings.spider_enabled:
        raise HTTPException(503, "Spider is disabled")
    ids = list(dict.fromkeys((request.candidate_ids or []))) if request else []
    if ids and (len(ids) > 50 or any(item <= 0 for item in ids)):
        raise HTTPException(422, "Select up to 50 valid candidates")
    candidate_query = select(func.count()).select_from(SoftwareCandidate).where(
        SoftwareCandidate.status.in_([e.CandidateStatus.DISCOVERED, e.CandidateStatus.REVIEWING, e.CandidateStatus.ACCEPTED]))
    if ids:
        candidate_query = candidate_query.where(SoftwareCandidate.id.in_(ids))
    count = db.scalar(candidate_query) or 0
    if not count or (ids and count != len(ids)):
        raise HTTPException(422, "No active candidates matched the selected IDs")
    if count > 50:
        raise HTTPException(422, "Select up to 50 candidates for one targeted scan")
    job = _queue_pool_scan(db, pool_id, ids or None)
    if job.status is e.JobStatus.FAILED:
        db.commit()
        raise HTTPException(503, "Spider queue is full")
    return serialize(RESOURCES[-1], job, db)


@router.post("/candidates/{candidate_id}/search", status_code=202)
def search_candidate_across_pools(candidate_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    candidate = db.get(SoftwareCandidate, candidate_id)
    if candidate is None or candidate.status not in {e.CandidateStatus.DISCOVERED, e.CandidateStatus.REVIEWING, e.CandidateStatus.ACCEPTED}:
        raise HTTPException(409, "Candidate must be active to search")
    if not settings.spider_enabled:
        raise HTTPException(503, "Spider is disabled")
    pool_ids = db.scalars(select(CrawlPool.id).where(CrawlPool.enabled.is_(True)).order_by(CrawlPool.id).limit(51)).all()
    if not pool_ids:
        raise HTTPException(422, "Add an enabled website to the URL crawl pool first")
    if len(pool_ids) > 50:
        raise HTTPException(422, "Search at most 50 websites per batch")
    jobs = [_queue_pool_scan(db, pool_id, [candidate_id]) for pool_id in pool_ids]
    return {"jobs": [serialize(RESOURCES[-1], job, db) for job in jobs],
            "queued": sum(job.status is e.JobStatus.PENDING for job in jobs)}


@router.post("/crawl-pools/scans/{job_id}/pause")
def pause_pool_scan(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None or job.target_type not in {"crawl_pool", "candidate_auto_search"}:
        raise HTTPException(404, "Pool scan not found")
    if job.status not in {e.JobStatus.PENDING, e.JobStatus.RUNNING}:
        raise HTTPException(409, "Only pending or running scans can be paused")
    was_running = job.status is e.JobStatus.RUNNING
    job.status = e.JobStatus.PAUSED
    job.message = "Pause requested" if was_running else "Paused before start"
    db.commit()
    return serialize(RESOURCES[-1], job, db)


@router.post("/crawl-pools/scans/{job_id}/resume", status_code=202)
def resume_pool_scan(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None or job.target_type not in {"crawl_pool", "candidate_auto_search"}:
        raise HTTPException(404, "Pool scan not found")
    if job.status is not e.JobStatus.PAUSED:
        raise HTTPException(409, "Only paused scans can be resumed")
    if job.message == "Pause requested":
        raise HTTPException(409, "Wait for the running scan to save its checkpoint")
    job.status = e.JobStatus.PENDING
    job.message = "Waiting to resume targeted search"
    db.commit()
    if not enqueue(job.id):
        job.status = e.JobStatus.PAUSED
        job.message = "Spider queue is full; retry resume"
        db.commit()
        raise HTTPException(503, "Spider queue is full")
    return serialize(RESOURCES[-1], job, db)


@router.post("/crawl-pools/scans/{job_id}/retry", status_code=202)
def retry_pool_scan(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None or job.target_type not in {"crawl_pool", "candidate_auto_search"}:
        raise HTTPException(404, "Pool scan not found")
    if job.status is not e.JobStatus.FAILED:
        raise HTTPException(409, "Only failed scans can be retried")
    pool = db.get(CrawlPool, job.target_id)
    if pool is None or not pool.enabled:
        raise HTTPException(409, "Crawl pool entry is missing or disabled")
    job.status = e.JobStatus.PENDING
    job.error_message = None
    job.message = "Waiting to retry targeted search"
    job.finished_at = None
    db.commit()
    if not enqueue(job.id):
        job.status = e.JobStatus.FAILED
        job.error_message = "Spider queue is full"
        db.commit()
        raise HTTPException(503, "Spider queue is full")
    return serialize(RESOURCES[-1], job, db)


class PromotePoolMatch(BaseModel):
    candidate_id: int = Field(gt=0)
    page_url: str


@router.post("/crawl-pools/{pool_id}/scans/{job_id}/create-source")
def create_source_from_pool_match(pool_id: int, job_id: int, request: PromotePoolMatch,
                                  db: Session = Depends(get_db)) -> dict[str, Any]:
    job = db.get(Job, job_id)
    pool = db.get(CrawlPool, pool_id)
    if pool is None or job is None or job.target_type != "crawl_pool" or job.target_id != pool_id or job.status not in {e.JobStatus.SUCCESS, e.JobStatus.PAUSED}:
        raise HTTPException(404, "Successful pool scan not found")
    if (job.result or {}).get("pool_url") != pool.base_url:
        raise HTTPException(409, "Website URL changed; run a new scan")
    match = next((item for item in (job.result or {}).get("matches", [])
                  if item.get("candidate_id") == request.candidate_id and item.get("page_url") == request.page_url), None)
    if match is None:
        raise HTTPException(409, "Candidate and page were not matched in this scan")
    candidate = db.get(SoftwareCandidate, request.candidate_id)
    if candidate is None or candidate.status is not e.CandidateStatus.ACCEPTED or not candidate.software_id:
        raise HTTPException(409, "Accept the candidate before creating a software source")
    if candidate.name != match.get("candidate_name"):
        raise HTTPException(409, "Candidate name changed since this scan; scan the website again")
    source = db.scalar(select(SoftwareSource).where(SoftwareSource.software_id == candidate.software_id,
                                                    SoftwareSource.source_url == request.page_url).limit(1))
    if source is None:
        source = SoftwareSource(software_id=candidate.software_id, source_type=e.SourceType.OTHER,
                                source_url=request.page_url, adapter_type=e.AdapterType.GENERIC_HTML,
                                enabled=True)
        db.add(source)
        db.commit()
        db.refresh(source)
    return serialize(next(item for item in RESOURCES if item.path == "sources"), source, db)


@router.post("/storage/{storage_id}/open-local-directory")
def open_storage_directory(storage_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, bool]:
    try:
        local_request = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local_request = False
    if not local_request:
        raise HTTPException(403, "Opening a local directory is only available from the backend host")
    storage = db.get(ArtifactStorage, storage_id)
    if storage is None:
        raise HTTPException(404, "Storage record not found")
    if storage.provider is not e.StorageProviderType.LOCAL:
        raise HTTPException(409, "Only LOCAL storage has a local directory")
    path = archived_file_for_storage(storage)
    if path is None:
        raise HTTPException(404, "Archived local file is missing")
    try:
        open_local_directory(path)
    except OSError as exc:
        raise HTTPException(503, "Could not open Windows Explorer on the backend host") from exc
    return {"opened": True}


@router.get("/storage/providers")
def storage_providers() -> dict[str, list[dict[str, object]]]:
    return {"items": [
        {"provider": "LOCAL", "available": True, "configured": True},
        {"provider": "BAIDU", "available": True, "configured": bool(settings.baidu_app_key and settings.baidu_app_secret and settings.baidu_token_encryption_key),
         "share_configured": bool(settings.baidu_app_id), "disable_share_supported": False},
        {"provider": "SELF_HOSTED", "available": True,
         "configured": bool(settings.self_hosted_base_url and settings.self_hosted_api_key and settings.self_hosted_username),
         "base_url": settings.self_hosted_base_url, "category_count": len(SELF_HOSTED_FILE_ARCH_CATEGORIES)},
        {"provider": "PAN123", "available": False, "configured": False},
        {"provider": "S3", "available": False, "configured": False},
    ]}


@router.get("/storage/accounts")
def storage_accounts(db: Session = Depends(get_db)) -> dict[str, list[dict[str, object]]]:
    accounts = db.scalars(select(StorageAccount).order_by(StorageAccount.id)).all()
    return {"items": [{"id": a.id, "provider": a.provider.value, "name": a.name,
                        "expires_at": s.beijing_iso(a.expires_at), "status": a.status.value}
                       for a in accounts]}


@router.get("/storage/accounts/baidu/oauth/start")
def start_baidu_oauth() -> dict[str, str]:
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = time.monotonic() + 600
    for key, expiry in list(_oauth_states.items()):
        if expiry < time.monotonic():
            _oauth_states.pop(key, None)
    try:
        return {"authorization_url": BaiduPanProvider.authorization_url(state)}
    except StorageError as exc:
        _oauth_states.pop(state, None)
        raise storage_http_error(exc) from exc


@router.get("/storage/accounts/baidu/oauth/callback", response_class=HTMLResponse)
def finish_baidu_oauth(code: str, state: str, db: Session = Depends(get_db)) -> str:
    expiry = _oauth_states.pop(state, None)
    if expiry is None or expiry < time.monotonic():
        raise HTTPException(400, "OAuth state is invalid or expired")
    provider = BaiduPanProvider()
    try:
        tokens = provider.exchange_code(code)
        account = save_oauth_account(db, "Default Baidu", tokens)
        return f"<html><meta charset='utf-8'><body><h2>Baidu Pan connected</h2><p>Account #{account.id}. Return to Settings and refresh.</p></body></html>"
    except StorageError as exc:
        raise storage_http_error(exc) from exc
    finally:
        provider.close()


class RedistributionUpdate(BaseModel):
    status: e.RedistributionStatus


@router.post("/artifacts/{artifact_id}/redistribution")
def update_redistribution(artifact_id: int, request: RedistributionUpdate,
                          db: Session = Depends(get_db)) -> dict[str, Any]:
    artifact = db.get(SoftwareArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, "Artifact not found")
    artifact.redistribution_status = request.status
    db.commit()
    return serialize(RESOURCES[5], artifact, db)


class UploadStorageRequest(BaseModel):
    provider: e.StorageProviderType = e.StorageProviderType.BAIDU
    account_id: int | None = None
    file_arch: str | None = None


@router.post("/artifacts/{artifact_id}/upload", status_code=202)
def upload_artifact(artifact_id: int, request: UploadStorageRequest,
                    db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        if request.provider == e.StorageProviderType.SELF_HOSTED:
            if not request.file_arch:
                raise StorageError("INVALID_CATEGORY", "Choose a cloud-drive file category")
            job = queue_self_hosted_upload(db, artifact_id, request.file_arch)
        elif request.provider == e.StorageProviderType.BAIDU:
            job = queue_upload(db, artifact_id, request.account_id)
        else:
            raise HTTPException(422, "This storage provider does not support uploads")
    except StorageError as exc:
        raise storage_http_error(exc) from exc
    if not enqueue_storage(job.id):
        job.status = e.JobStatus.FAILED
        job.error_message = "Storage queue is full"
        job.finished_at = beijing_now()
        storage = db.get(ArtifactStorage, job.payload["storage_id"])
        storage.upload_status = e.UploadStatus.FAILED
        storage.status = e.StorageStatus.FAILED
        db.commit()
        raise HTTPException(503, "Storage queue is full")
    return serialize(RESOURCES[-1], job, db)


@router.get("/storage/self-hosted/categories")
def self_hosted_categories() -> dict[str, list[str]]:
    return {"items": list(SELF_HOSTED_FILE_ARCH_CATEGORIES)}


@router.get("/artifacts/{artifact_id}/storage")
def artifact_storage_locations(artifact_id: int, db: Session = Depends(get_db)) -> dict[str, list[dict[str, Any]]]:
    if db.get(SoftwareArtifact, artifact_id) is None:
        raise HTTPException(404, "Artifact not found")
    rows = db.scalars(select(ArtifactStorage).where(ArtifactStorage.artifact_id == artifact_id)).all()
    return {"items": [serialize(RESOURCES[7], row, db) for row in rows]}


class ShareRequest(BaseModel):
    password: str | None = Field(default=None, min_length=4, max_length=4)


@router.post("/storage/{storage_id}/share")
def create_storage_share(storage_id: int, request: ShareRequest,
                         db: Session = Depends(get_db)) -> dict[str, Any]:
    storage = db.get(ArtifactStorage, storage_id)
    if storage is None:
        raise HTTPException(404, "Storage location not found")
    try:
        storage_create_share(db, storage, request.password)
    except StorageError as exc:
        raise storage_http_error(exc) from exc
    return serialize(RESOURCES[7], storage, db)


@router.post("/storage/{storage_id}/disable-share")
def disable_storage_share(storage_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    storage = db.get(ArtifactStorage, storage_id)
    if storage is None:
        raise HTTPException(404, "Storage location not found")
    try:
        storage_disable_share(db, storage)
    except StorageError as exc:
        raise storage_http_error(exc) from exc
    return serialize(RESOURCES[7], storage, db)


@router.get("/lookups/{kind}")
def lookup_options(kind: str, q: str = "", selected_id: int | None = Query(None, gt=0),
                   software_id: int | None = Query(None, gt=0), release_id: int | None = Query(None, gt=0),
                   variant_id: int | None = Query(None, gt=0), limit: int = Query(20, ge=1, le=50),
                   db: Session = Depends(get_db)) -> dict[str, list[dict[str, object]]]:
    if kind not in LOOKUP_MODELS:
        raise HTTPException(404, "Unknown lookup resource")
    return {"items": find_lookups(db, kind, query=q, selected_id=selected_id,
                                  software_id=software_id, release_id=release_id,
                                  variant_id=variant_id, limit=limit)}


@router.post("/candidates/{candidate_id}/accept")
def accept(candidate_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    software = accept_candidate(db, candidate_id)
    return serialize(RESOURCES[1], software, db)


@router.post("/software/{software_id}/archive")
def archive(software_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    software = db.get(Software, software_id)
    if software is None:
        raise HTTPException(404, "Software not found")
    software.status = e.SoftwareStatus.ARCHIVED
    db.commit()
    db.refresh(software)
    return serialize(RESOURCES[1], software, db)


@router.get("/software/{software_id}/releases")
def software_releases(software_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)) -> dict[str, Any]:
    if db.get(Software, software_id) is None:
        raise HTTPException(404, "Software not found")
    rows, total = Repository(db, SoftwareRelease).list(page=page, page_size=page_size, filters={"software_id": software_id})
    return {"items": [serialize(RESOURCES[3], row, db) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/software/{software_id}/sources")
def software_sources(software_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)) -> dict[str, Any]:
    if db.get(Software, software_id) is None:
        raise HTTPException(404, "Software not found")
    rows, total = Repository(db, SoftwareSource).list(page=page, page_size=page_size, filters={"software_id": software_id})
    return {"items": [serialize(RESOURCES[2], row, db) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/artifacts/{artifact_id}/download")
def download(artifact_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = create_artifact_job(db, artifact_id, e.JobType.DOWNLOAD)
    if job.status is e.JobStatus.PENDING and not enqueue_download(job.id):
        job.status = e.JobStatus.FAILED
        job.error_message = "Download queue is full"
        job.finished_at = beijing_now()
        db.commit()
        raise HTTPException(503, "Download queue is full")
    return serialize(RESOURCES[-1], job, db)


@router.post("/artifacts/{artifact_id}/redownload")
def redownload(artifact_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = create_artifact_job(db, artifact_id, e.JobType.DOWNLOAD, redownload=True)
    if job.status is e.JobStatus.PENDING and not enqueue_download(job.id):
        job.status = e.JobStatus.FAILED
        job.error_message = "Download queue is full"
        job.finished_at = beijing_now()
        db.commit()
        raise HTTPException(503, "Download queue is full")
    return serialize(RESOURCES[-1], job, db)


@router.post("/artifacts/{artifact_id}/verify")
def verify(artifact_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = create_artifact_job(db, artifact_id, e.JobType.VERIFY)
    if job.status is e.JobStatus.PENDING and not enqueue_download(job.id):
        job.status = e.JobStatus.FAILED
        job.error_message = "Verification queue is full"
        job.finished_at = beijing_now()
        db.commit()
        raise HTTPException(503, "Verification queue is full")
    return serialize(RESOURCES[-1], job, db)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None or job.job_type is not e.JobType.DOWNLOAD:
        raise HTTPException(404, "Download job not found")
    if job.status not in {e.JobStatus.PENDING, e.JobStatus.RUNNING}:
        raise HTTPException(409, "Job cannot be cancelled")
    job.status = e.JobStatus.CANCELLED
    job.message = "Cancellation requested"
    if job.started_at is None:
        job.finished_at = beijing_now()
        artifact = db.get(SoftwareArtifact, job.target_id)
        if artifact:
            artifact.download_status = e.DownloadStatus.DOWNLOADED if artifact.local_path else e.DownloadStatus.FAILED
    db.commit()
    return serialize(RESOURCES[-1], job, db)


@router.post("/downloads/bulk")
def bulk_download(artifact_ids: list[int] = Body(...), db: Session = Depends(get_db)) -> dict[str, Any]:
    if not 1 <= len(artifact_ids) <= 100:
        raise HTTPException(422, "Select between 1 and 100 artifacts")
    jobs = []
    for artifact_id in dict.fromkeys(artifact_ids):
        try:
            job = create_artifact_job(db, artifact_id, e.JobType.DOWNLOAD)
            if enqueue_download(job.id):
                jobs.append(serialize(RESOURCES[-1], job, db))
            else:
                job.status = e.JobStatus.FAILED
                job.error_message = "Download queue is full"
                job.finished_at = beijing_now()
                db.commit()
        except HTTPException:
            continue
    return {"jobs": jobs}


@router.post("/artifacts/{artifact_id}/review/{decision}")
def review_artifact(artifact_id: int, decision: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    if decision not in {"approve", "reject"}:
        raise HTTPException(404, "Unknown review decision")
    artifact = db.get(SoftwareArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, "Artifact not found")
    if artifact.verification_status is not e.VerificationStatus.MANUAL_REVIEW:
        raise HTTPException(409, "Artifact is not awaiting manual review")
    from app.verification.service import hashes
    manager = ArchiveManager()
    staged = StagingManager().complete(artifact.id)
    if decision == "reject":
        if staged.exists():
            manager.fail(staged, artifact.id)
        previous = manager.resolve_relative(artifact.local_path) if artifact.local_path else None
        artifact.verification_status = e.VerificationStatus.VERIFIED if previous and previous.is_file() else e.VerificationStatus.REJECTED
    else:
        if staged.exists():
            sha, md5, size = hashes(staged)
            variant, release = artifact.variant, artifact.variant.release
            filename = (artifact.verification_details or {}).get("metadata", {}).get("download_filename") or artifact.filename
            relative = manager.archive_relative(release.software.slug, release.version, variant.os.value,
                                                variant.architecture.value, filename)
            if (manager.root / relative).exists():
                relative = relative.with_name(f"{relative.stem}-{sha[:8]}{relative.suffix}")
            manager.archive(staged, relative)
            artifact.local_path = relative.as_posix()
            artifact.filename = filename
            artifact.sha256, artifact.md5, artifact.file_size = sha, md5, size
        elif not artifact.local_path or not manager.resolve_relative(artifact.local_path).is_file():
            raise HTTPException(409, "No local file is available for approval")
        artifact.verification_status = e.VerificationStatus.VERIFIED
        local = db.scalar(select(ArtifactStorage).where(ArtifactStorage.artifact_id == artifact.id,
            ArtifactStorage.provider == e.StorageProviderType.LOCAL).limit(1))
        if local is None:
            local = ArtifactStorage(artifact_id=artifact.id, provider=e.StorageProviderType.LOCAL)
            db.add(local)
        local.remote_path = artifact.local_path
        local.status = e.StorageStatus.AVAILABLE
    artifact.manual_reviewed_at = beijing_now()
    db.commit()
    db.refresh(artifact)
    return serialize(RESOURCES[5], artifact, db)


def _spider_job(db: Session, source: SoftwareSource, job_type: e.JobType,
                payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not settings.spider_enabled:
        raise HTTPException(503, "Spider is disabled")
    if not source.enabled or source.automation_status in {e.AutomationStatus.DISABLED, e.AutomationStatus.MANUAL_REQUIRED}:
        raise HTTPException(409, "Source is disabled or requires manual review")
    job = Job(job_type=job_type, target_type="source", target_id=source.id,
              status=e.JobStatus.PENDING, progress=0, message="Awaiting spider worker", payload=payload)
    db.add(job)
    db.commit()
    db.refresh(job)
    if not enqueue(job.id):
        job.status = e.JobStatus.FAILED
        job.error_message = "Spider queue is full"
        job.finished_at = beijing_now()
        db.commit()
        raise HTTPException(503, "Spider queue is full")
    return serialize(RESOURCES[-1], job, db)


class DiscoveryImportRequest(BaseModel):
    preview_job_id: int = Field(gt=0)
    version_overrides: dict[int, str] = Field(default_factory=dict)


@router.post("/sources/{source_id}/discover/preview", status_code=202)
def preview_source(source_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    source = db.get(SoftwareSource, source_id)
    if source is None:
        raise HTTPException(404, "Source not found")
    return _spider_job(db, source, e.JobType.CRAWL)


@router.post("/sources/{source_id}/discover/import", status_code=202)
def import_discovery(source_id: int, request: "DiscoveryImportRequest",
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    source = db.get(SoftwareSource, source_id)
    if source is None:
        raise HTTPException(404, "Source not found")
    preview = db.get(Job, request.preview_job_id)
    if preview is None or preview.job_type is not e.JobType.CRAWL or preview.status is not e.JobStatus.SUCCESS or preview.target_type != "source" or preview.target_id != source_id or not (preview.result or {}).get("discovery"):
        raise HTTPException(409, "A successful preview for this source is required")
    return _spider_job(db, source, e.JobType.CRAWL, {"operation": "import", "preview_job_id": request.preview_job_id,
                                                     "version_overrides": request.version_overrides})


@router.post("/sources/{source_id}/check-release", status_code=202)
def check_source_release(source_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    source = db.get(SoftwareSource, source_id)
    if source is None:
        raise HTTPException(404, "Source not found")
    return _spider_job(db, source, e.JobType.CHECK_RELEASE)


def _primary_source(db: Session, software_id: int) -> SoftwareSource:
    software = db.get(Software, software_id)
    if software is None:
        raise HTTPException(404, "Software not found")
    if software.status is not e.SoftwareStatus.ACTIVE:
        raise HTTPException(409, "Software is not active")
    source = db.scalar(select(SoftwareSource).where(
        SoftwareSource.software_id == software_id, SoftwareSource.enabled.is_(True),
        SoftwareSource.automation_status.notin_([e.AutomationStatus.DISABLED, e.AutomationStatus.MANUAL_REQUIRED]),
        SoftwareSource.adapter_type.notin_([e.AdapterType.BROWSER, e.AdapterType.MANUAL]))
        .order_by(SoftwareSource.priority.asc(), SoftwareSource.id.asc()).limit(1))
    if source is None:
        raise HTTPException(409, "No automated source available for this software")
    return source


@router.post("/software/{software_id}/check-release", status_code=202)
def check_software_release(software_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _spider_job(db, _primary_source(db, software_id), e.JobType.CHECK_RELEASE)


@router.post("/software/check-releases", status_code=202)
def bulk_check_releases(software_ids: list[int] = Body(..., embed=True),
                        db: Session = Depends(get_db)) -> dict[str, Any]:
    if not software_ids or len(software_ids) > 50:
        raise HTTPException(422, "Select between 1 and 50 software records")
    sources = [_primary_source(db, software_id) for software_id in dict.fromkeys(software_ids)]
    jobs = [_spider_job(db, source, e.JobType.CHECK_RELEASE) for source in sources]
    return {"jobs": jobs}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict[str, Any]:
    counts = {name: db.scalar(select(func.count()).select_from(model)) or 0 for name, model in [
        ("candidates", SoftwareCandidate), ("software", Software), ("releases", SoftwareRelease), ("artifacts", SoftwareArtifact)]}
    counts["pending_downloads"] = db.scalar(select(func.count()).select_from(SoftwareArtifact).where(SoftwareArtifact.download_status == e.DownloadStatus.QUEUED)) or 0
    counts["failed_jobs"] = db.scalar(select(func.count()).select_from(Job).where(Job.status == e.JobStatus.FAILED)) or 0
    counts["pending_review_content"] = db.scalar(select(func.count()).select_from(GeneratedContent).where(GeneratedContent.status.in_([e.ContentStatus.DRAFT, e.ContentStatus.REVIEWED]))) or 0
    jobs = db.scalars(select(Job).order_by(Job.created_at.desc()).limit(10)).all()
    return {**counts, "recent_jobs": [serialize(RESOURCES[-1], job, db) for job in jobs]}


@router.get("/settings")
def settings_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        connected = True
    except Exception:
        connected = False
    return {"database": "CONNECTED" if connected else "DISCONNECTED", "database_host": settings.db_host,
            "database_name": settings.db_name, "data_root": settings.data_root,
            "local_storage": effective_data_path(), "timezone": "Asia/Shanghai",
            "current_time": beijing_now().isoformat() + "+08:00",
            "downloader": "DIRECT_HTTP_READY", "download_concurrency": settings.download_max_concurrency,
            "download_timeout": settings.download_timeout, "download_max_file_size": settings.download_max_file_size,
            "download_worker_restart_required": download_worker_concurrency() != settings.download_max_concurrency,
            "ai": "NOT_CONFIGURED", "baidu_pan": "CONNECTED" if db.scalar(select(StorageAccount.id).where(
                StorageAccount.provider == e.StorageProviderType.BAIDU,
                StorageAccount.status == e.StorageAccountStatus.ACTIVE).limit(1)) else "NOT_CONFIGURED",
            "spider_enabled": settings.spider_enabled, "spider_timeout": settings.spider_timeout,
            "spider_retries": settings.spider_max_retries, "spider_concurrency": worker_concurrency(),
            "spider_max_retries": settings.spider_max_retries,
            "spider_max_concurrency": worker_concurrency(),
            "spider_request_delay": settings.spider_request_delay,
            "spider_user_agent": settings.spider_user_agent,
            "spider_restart_required": False,
            "github_api": "CONFIGURED" if settings.github_token else "NOT_CONFIGURED",
            "external_search": "CONFIGURED" if settings.google_cse_api_key and settings.google_cse_cx else "NOT_CONFIGURED",
            "ai_page_recognition": "CONFIGURED" if settings.ai_page_recognition_enabled and settings.openai_api_key and settings.ai_page_model else "NOT_CONFIGURED"}


@router.patch("/settings")
def update_settings(patch: SettingsPatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    save_overrides(db, patch)
    if settings.spider_enabled:
        schedule_automatic_candidate_searches(db)
    return settings_status(db)


# Register generic /{id} resources after named storage endpoints such as
# /storage/providers and /storage/accounts so they cannot shadow them.
for definition in RESOURCES:
    create_resource_routes(definition)
