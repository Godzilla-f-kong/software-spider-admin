import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import enums as e
from app.core.config import settings
from app.core.enums import AutomationStatus, CandidateStatus, JobStatus, JobType, SourceStatus
from app.db.base import beijing_now
from app.db.session import SessionLocal
from app.models import CrawlPool, Job, SoftwareCandidate, SoftwareSource
from app.spider.pool_crawler import CandidateTarget, PoolCrawler
from app.spider.errors import SpiderError
from app.spider.result import DiscoveryResult
from app.spider.service import DiscoveryPersistenceService, SpiderService, compare_latest

logger = logging.getLogger(__name__)
_executor: ThreadPoolExecutor | None = None
_configure_lock = Lock()


def worker_concurrency() -> int:
    return 1


def _configure() -> ThreadPoolExecutor:
    global _executor
    with _configure_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="spider")
        return _executor


def enqueue(job_id: int) -> bool:
    executor = _configure()
    try:
        executor.submit(_run, job_id)
        return True
    except RuntimeError:
        return False


def schedule_automatic_candidate_searches(db: Session, candidate_ids: list[int] | None = None,
                                          pool_ids: list[int] | None = None) -> list[Job]:
    """Persist one serial search job per eligible candidate and enqueue it after commit."""
    if not settings.spider_enabled:
        return []
    selected_pools = pool_ids or db.scalars(select(CrawlPool.id).where(CrawlPool.enabled.is_(True))
                                            .order_by(CrawlPool.id)).all()
    selected_pools = list(dict.fromkeys(selected_pools))
    if not selected_pools:
        return []

    query = select(SoftwareCandidate).where(SoftwareCandidate.status.in_([
        CandidateStatus.DISCOVERED, CandidateStatus.REVIEWING, CandidateStatus.ACCEPTED]))
    if candidate_ids is not None:
        query = query.where(SoftwareCandidate.id.in_(candidate_ids))
    candidates = db.scalars(query.order_by(SoftwareCandidate.priority_score.desc().nullslast(),
                                           SoftwareCandidate.id)).all()
    candidate_id_set = [item.id for item in candidates]
    history = db.scalars(select(Job).where(Job.job_type == JobType.CRAWL,
        Job.target_type == "candidate_auto_search", Job.target_id.in_(candidate_id_set))).all() if candidates else []
    history_by_candidate: dict[int, list[Job]] = {}
    for previous in history:
        history_by_candidate.setdefault(previous.target_id, []).append(previous)
    existing_jobs = db.scalars(select(Job).where(Job.job_type == JobType.CRAWL,
        Job.target_type == "candidate_auto_search", Job.target_id.in_([item.id for item in candidates]),
        Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING, JobStatus.PAUSED]))).all() if candidates else []
    active_by_candidate: dict[int, list[Job]] = {}
    for existing in existing_jobs:
        active_by_candidate.setdefault(existing.target_id, []).append(existing)

    created: list[Job] = []
    for candidate in candidates:
        previous_jobs = history_by_candidate.get(candidate.id, [])
        if candidate_ids is None and pool_ids is None and previous_jobs:
            continue
        found_before = any((job.result or {}).get("stop_reason") == "MATCH_FOUND" for job in previous_jobs)
        if pool_ids is not None and found_before:
            continue
        searched_pools = {int(pool_id) for job in previous_jobs
                          for pool_id in (job.payload or {}).get("pool_ids", [])}
        already_covered = set().union(*(set((job.payload or {}).get("pool_ids", []))
                                        for job in active_by_candidate.get(candidate.id, []))) \
                          if active_by_candidate.get(candidate.id) else set()
        requested = set(selected_pools) - searched_pools - already_covered
        if not requested:
            continue
        candidate_pools = sorted(requested)
        target = {"id": candidate.id, "name": candidate.name,
                  "normalized_name": candidate.normalized_name, "status": candidate.status.value,
                  "target_version": candidate.target_version,
                  "target_os": candidate.target_os.value if candidate.target_os else None,
                  "target_architecture": candidate.target_architecture.value if candidate.target_architecture else None}
        job = Job(job_type=JobType.CRAWL, target_type="candidate_auto_search", target_id=candidate.id,
                  status=JobStatus.PENDING, progress=0, message="Waiting for automatic website search",
                  payload={"workflow": "automatic_candidate_search", "candidate": target,
                           "pool_ids": candidate_pools})
        db.add(job)
        created.append(job)
        active_by_candidate.setdefault(candidate.id, []).append(job)
    if not created:
        return []
    db.commit()
    for job in created:
        db.refresh(job)
        if not enqueue(job.id):
            job.status = JobStatus.FAILED
            job.error_message = "Could not enqueue automatic search"
            job.message = "Automatic search could not be queued"
            job.finished_at = beijing_now()
    db.commit()
    return created


def enqueue_pending_spider_jobs() -> None:
    with SessionLocal() as db:
        pending = db.scalars(select(Job.id).where(Job.job_type.in_([JobType.CRAWL, JobType.CHECK_RELEASE]),
                                                 Job.status == JobStatus.PENDING).order_by(Job.id)).all()
    for job_id in pending:
        enqueue(job_id)


def _progress(db: Session, job: Job, value: int, message: str) -> None:
    job.progress = value
    job.message = message
    db.commit()


def _run(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None or job.status is not JobStatus.PENDING:
            return
        job.status = JobStatus.RUNNING
        job.started_at = beijing_now()
        _progress(db, job, 10, "Loading source")
        try:
            if job.target_type == "candidate_auto_search":
                _run_automatic_candidate_search(db, job)
            elif job.target_type == "crawl_pool":
                _run_pool_scan(db, job)
            elif job.payload and job.payload.get("operation") == "import":
                _run_import(db, job)
            else:
                _run_discovery(db, job)
            db.refresh(job, attribute_names=["status"])
            if job.status is JobStatus.RUNNING:
                job.status = JobStatus.SUCCESS
                job.progress = 100
                if job.target_type != "candidate_auto_search":
                    job.message = "Complete"
                job.finished_at = beijing_now()
            db.commit()
        except SpiderError as exc:
            db.rollback()
            _fail(db, job_id, exc.code, exc.message)
        except Exception:
            db.rollback()
            logger.exception("Spider job failed job_id=%s error_type=UNKNOWN_ERROR", job_id)
            _fail(db, job_id, "UNKNOWN_ERROR", "Unexpected spider error; inspect server log")
def _fail(db: Session, job_id: int, code: str, message: str) -> None:
    job = db.get(Job, job_id)
    if job is None: return
    job.status = JobStatus.FAILED
    job.error_message = f"{code}: {message}"[:2000]
    job.message = "Discovery failed"
    job.finished_at = beijing_now()
    if job.target_type == "source":
        source = db.get(SoftwareSource, job.target_id)
        if source:
            source.last_checked_at = beijing_now()
            source.last_error = job.error_message
            source.status = SourceStatus.FAILED
            if code in {"MANUAL_REQUIRED", "HTTP_403"}:
                source.automation_status = AutomationStatus.MANUAL_REQUIRED
    elif job.target_type == "crawl_pool":
        pool = db.get(CrawlPool, job.target_id)
        if pool:
            pool.last_checked_at = beijing_now()
            pool.last_error = job.error_message
            pool.status = SourceStatus.FAILED
    db.commit()


def _run_pool_scan(db: Session, job: Job) -> None:
    pool = db.get(CrawlPool, job.target_id)
    if pool is None or not pool.enabled:
        raise SpiderError("INVALID_SOURCE", "Crawl pool entry is missing or disabled")
    saved_targets = (job.payload or {}).get("targets")
    if saved_targets:
        candidates = [CandidateTarget(id=item["id"], name=item["name"],
            normalized_name=item["normalized_name"], status=CandidateStatus(item["status"]),
            target_version=item.get("target_version"),
            target_os=e.OperatingSystem(item["target_os"]) if item.get("target_os") else None,
            target_architecture=e.Architecture(item["target_architecture"]) if item.get("target_architecture") else None)
            for item in saved_targets]
    else:
        query = select(SoftwareCandidate).where(SoftwareCandidate.status.in_([
            CandidateStatus.DISCOVERED, CandidateStatus.REVIEWING, CandidateStatus.ACCEPTED]))
        ids = (job.payload or {}).get("candidate_ids")
        if ids:
            query = query.where(SoftwareCandidate.id.in_(ids))
        candidates = [CandidateTarget.from_model(item) for item in db.scalars(query.order_by(SoftwareCandidate.id))]
    if not candidates:
        raise SpiderError("INVALID_SOURCE", "Add software candidates before scanning this website")
    if len(candidates) > 50:
        raise SpiderError("TOO_MANY_TARGETS", "Select up to 50 software candidates for one scan")
    _progress(db, job, 20, "Searching for target software")
    def progress(snapshot: dict) -> None:
        job.result = snapshot
        job.progress = min(90, 20 + int(70 * min(snapshot["visited_pages"], pool.max_pages) / pool.max_pages))
        job.message = f"Checked {snapshot['visited_pages']} pages; matched {len(snapshot['matches'])}"
        db.commit()
    def should_pause() -> bool:
        db.refresh(job, attribute_names=["status"])
        return job.status is JobStatus.PAUSED
    result = PoolCrawler().scan(pool, candidates, progress,
                                checkpoint=(job.result or {}).get("checkpoint"), should_pause=should_pause)
    pool.last_checked_at = beijing_now()
    pool.last_error = None
    pool.last_result_count = len(result["matches"])
    pool.status = SourceStatus.HEALTHY
    job.result = result
    if result["stop_reason"] in {"PAUSED", "BUDGET", "NO_PROGRESS"}:
        job.status = JobStatus.PAUSED
        job.message = f"Paused ({result['stop_reason']}); {len(result['matches'])} matches"
        db.commit()
    else:
        db.refresh(job, attribute_names=["status"])
        if job.status is JobStatus.PAUSED:
            job.status = JobStatus.RUNNING  # The scan finished while a pause request was in flight.
        _progress(db, job, 95, f"Matched {len(result['matches'])} candidate pages")


def _run_automatic_candidate_search(db: Session, job: Job) -> None:
    if (job.result or {}).get("stop_reason") == "MATCH_FOUND":
        job.status = JobStatus.SUCCESS
        job.progress = 100
        job.message = "Matching resource found; candidate scan complete"
        job.finished_at = beijing_now()
        db.commit()
        return
    payload = job.payload or {}
    target_data = payload.get("candidate") or {}
    candidate_id = int(target_data.get("id", job.target_id))
    candidate = db.get(SoftwareCandidate, candidate_id)
    if candidate is None or candidate.status not in {CandidateStatus.DISCOVERED, CandidateStatus.REVIEWING,
                                                      CandidateStatus.ACCEPTED}:
        job.status = JobStatus.CANCELLED
        job.message = "Candidate is no longer eligible for automatic search"
        job.finished_at = beijing_now()
        db.commit()
        return
    if not target_data:
        target_data = {"id": candidate.id, "name": candidate.name, "normalized_name": candidate.normalized_name,
                       "status": candidate.status.value, "target_version": candidate.target_version,
                       "target_os": candidate.target_os.value if candidate.target_os else None,
                       "target_architecture": candidate.target_architecture.value if candidate.target_architecture else None}
    target = CandidateTarget(id=target_data["id"], name=target_data["name"],
        normalized_name=target_data["normalized_name"], status=CandidateStatus(target_data["status"]),
        target_version=target_data.get("target_version"),
        target_os=e.OperatingSystem(target_data["target_os"]) if target_data.get("target_os") else None,
        target_architecture=e.Architecture(target_data["target_architecture"])
            if target_data.get("target_architecture") else None)
    pool_ids = payload.get("pool_ids", [])
    if not pool_ids:
        raise SpiderError("INVALID_SOURCE", "No enabled website URL pool was available")

    state = job.result or {}
    pool_results = list(state.get("pool_results", []))
    pool_index = int(state.get("current_pool_index", 0))
    checkpoint = state.get("current_checkpoint")
    total_pools = len(pool_ids)

    def persist(message: str, current_result: dict | None = None) -> None:
        current_fraction = 0.0
        if current_result and pool_index < total_pools:
            active_pool = db.get(CrawlPool, int(pool_ids[pool_index]))
            if active_pool:
                current_fraction = min(1.0, current_result["visited_pages"] / max(active_pool.max_pages, 1))
        job.result = {"workflow": "automatic_candidate_search", "candidate_id": candidate.id,
            "candidate_name": candidate.name, "current_pool_index": pool_index,
            "current_pool": current_result.get("pool_url") if current_result else None,
            "current_checkpoint": current_result.get("checkpoint") if current_result else checkpoint,
            "pool_results": pool_results,
            "matches": [match for attempt in pool_results for match in attempt.get("matches", [])]
                       + (current_result or {}).get("matches", [])}
        job.progress = min(94, int(10 + 82 * (pool_index + current_fraction) / max(total_pools, 1)))
        job.message = message
        db.commit()

    while pool_index < total_pools:
        db.refresh(job, attribute_names=["status"])
        if job.status is JobStatus.PAUSED:
            persist(f"Paused before website {pool_index + 1} of {total_pools}")
            return
        pool_id = int(pool_ids[pool_index])
        pool = db.get(CrawlPool, pool_id)
        if pool is None or not pool.enabled:
            pool_results.append({"pool_id": pool_id, "pool_url": pool.base_url if pool else None,
                                 "matches": [], "error": "Website URL pool entry is missing or disabled"})
            pool_index += 1
            checkpoint = None
            persist(f"Skipped unavailable website; continuing ({pool_index}/{total_pools})")
            continue

        _progress(db, job, min(90, int(10 + 82 * pool_index / max(total_pools, 1))),
                  f"Searching {candidate.name} on website {pool_index + 1}/{total_pools}: {pool.base_url}")
        try:
            while True:
                def progress(snapshot: dict) -> None:
                    persist(f"Searching {candidate.name} on website {pool_index + 1}/{total_pools}: "
                            f"{snapshot['visited_pages']} pages visited", snapshot)

                def should_pause() -> bool:
                    db.refresh(job, attribute_names=["status"])
                    return job.status is JobStatus.PAUSED

                result = PoolCrawler().scan(pool, [target], progress, checkpoint=checkpoint,
                    should_pause=should_pause, stop_on_match=True)
                if result["stop_reason"] == "PAUSED":
                    persist(f"Paused on website {pool_index + 1}/{total_pools}", result)
                    return
                if result["stop_reason"] == "BUDGET" and result.get("checkpoint"):
                    checkpoint = result["checkpoint"]
                    persist(f"Continuing search on website {pool_index + 1}/{total_pools}", result)
                    continue
                break
        except SpiderError as exc:
            pool.last_checked_at = beijing_now()
            pool.last_error = f"{exc.code}: {exc.message}"[:2000]
            pool.status = SourceStatus.FAILED
            pool_results.append({"pool_id": pool.id, "pool_url": pool.base_url, "matches": [],
                                 "error": pool.last_error, "stop_reason": exc.code})
            db.commit()
            pool_index += 1
            checkpoint = None
            persist(f"Website failed; continuing ({pool_index}/{total_pools})")
            continue

        pool.last_checked_at = beijing_now()
        pool.last_error = None
        pool.last_result_count = len(result["matches"])
        pool.status = SourceStatus.HEALTHY
        for match in result["matches"]:
            match["crawl_pool_id"] = pool.id
        pool_results.append({"pool_id": pool.id, "pool_url": pool.base_url,
                             "stop_reason": result["stop_reason"], "visited_pages": result["visited_pages"],
                             "matches": result["matches"], "warnings": result["warnings"],
                             "strategies": result.get("strategies", {})})
        found = any(item.get("match_status") == "MATCHED" for item in result["matches"])
        pool_index += 1
        checkpoint = None
        persist("Matching resource found; stopping this candidate" if found else
                f"Website checked; continuing ({pool_index}/{total_pools})")
        if found:
            for later in db.scalars(select(Job).where(Job.job_type == JobType.CRAWL,
                    Job.target_type == "candidate_auto_search", Job.target_id == candidate.id,
                    Job.status == JobStatus.PENDING, Job.id != job.id)).all():
                later.status = JobStatus.CANCELLED
                later.message = "Stopped because another website scan found a match"
                later.finished_at = beijing_now()
            job.result = {**job.result, "stop_reason": "MATCH_FOUND"}
            job.status = JobStatus.SUCCESS
            job.progress = 100
            job.message = "Matching resource found; candidate scan complete"
            job.finished_at = beijing_now()
            db.commit()
            return

    if not any(attempt.get("error") for attempt in pool_results):
        stop_reason = "ALL_ENABLED_WEBSITES_CHECKED"
    elif len(pool_results) == 1 and pool_results[0].get("error"):
        stop_reason = "ALL_WEBSITES_FAILED"
    else:
        stop_reason = "WEBSITES_CHECKED_WITH_ERRORS"
    job.result = {**job.result, "stop_reason": stop_reason}
    job.status = JobStatus.SUCCESS
    job.message = "No matching resource found; all queued websites checked"
    job.progress = 100
    job.finished_at = beijing_now()
    db.commit()


def recover_interrupted_pool_scans() -> None:
    """Recover saved work and schedule active software candidates on startup."""
    with SessionLocal() as db:
        jobs = db.scalars(select(Job).where(Job.job_type.in_([JobType.CRAWL, JobType.CHECK_RELEASE]),
                                            Job.status == JobStatus.RUNNING)).all()
        for job in jobs:
            if job.target_type == "candidate_auto_search":
                job.status = JobStatus.PENDING
                job.message = "Interrupted; continuing automatically from checkpoint"
            elif job.target_type == "crawl_pool":
                job.status = JobStatus.PAUSED
                job.message = "Interrupted; resume to continue"
            else:
                job.status = JobStatus.FAILED
                job.error_message = "INTERRUPTED: Backend stopped while the Spider job was running"
                job.message = "Spider job interrupted"
                job.finished_at = beijing_now()
        if jobs:
            db.commit()
    enqueue_pending_spider_jobs()
    with SessionLocal() as db:
        schedule_automatic_candidate_searches(db)


def _run_discovery(db: Session, job: Job) -> None:
    source = db.get(SoftwareSource, job.target_id)
    if source is None:
        raise SpiderError("INVALID_SOURCE", "Source was deleted")
    _progress(db, job, 30, "Fetching and parsing source")
    result = SpiderService().discover(source, job_id=job.id)
    _progress(db, job, 70, "Classifying discoveries")
    result = DiscoveryPersistenceService().annotate(db, result)
    source.last_checked_at = beijing_now()
    source.last_success_at = beijing_now()
    source.last_error = None
    source.status = SourceStatus.HEALTHY
    source.automation_status = AutomationStatus.ALLOWED
    payload = {"discovery": result.model_dump(mode="json")}
    if job.job_type is JobType.CHECK_RELEASE:
        payload["release_check"] = compare_latest(db, result)
    job.result = payload
    _progress(db, job, 90, "Discovery ready for review")


def _run_import(db: Session, job: Job) -> None:
    preview_id = (job.payload or {}).get("preview_job_id")
    preview = db.get(Job, preview_id) if isinstance(preview_id, int) else None
    if preview is None or preview.status is not JobStatus.SUCCESS or preview.target_type != "source" or preview.target_id != job.target_id:
        raise SpiderError("INVALID_SOURCE", "Successful preview job was not found for this source")
    data = (preview.result or {}).get("discovery")
    if not isinstance(data, dict):
        raise SpiderError("PARSE_ERROR", "Preview result is missing")
    result = DiscoveryResult.model_validate(data)
    for index, version in (job.payload or {}).get("version_overrides", {}).items():
        index = int(index)
        if index < 0 or index >= len(result.releases) or not isinstance(version, str) or not version.strip() or len(version.strip()) > 100:
            raise SpiderError("PARSE_ERROR", "Invalid version override")
        result.releases[index].version = version.strip()
    _progress(db, job, 70, "Saving releases, platforms and artifacts")
    job.result = {"imported": DiscoveryPersistenceService().import_result(db, result),
                  "preview_job_id": preview_id}
    _progress(db, job, 90, "Database import complete")
