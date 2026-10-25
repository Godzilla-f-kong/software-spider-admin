"""Create catalog records for completed automatic candidate crawls."""
import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import JobStatus, JobType
from app.models import Job, SoftwareCandidate
from app.services.catalog import ensure_candidate_software

logger = logging.getLogger(__name__)


def register_successful_candidate_crawl(db: Session, job: Job) -> None:
    if (job.job_type is not JobType.CRAWL or job.target_type != "candidate_auto_search"
            or job.status is not JobStatus.SUCCESS):
        return

    try:
        software = ensure_candidate_software(db, job.target_id)
        result = dict(job.result or {})
        result.update(software_id=software.id, software_name=software.name)
        job.result = result
        job.message = f"{job.message or 'Candidate crawl completed'} · Cataloged {software.name}"
        db.commit()
    except HTTPException as exc:
        db.rollback()
        job = db.get(Job, job.id)
        if job is None:
            return
        result = dict(job.result or {})
        result["catalog_error"] = str(exc.detail)
        job.result = result
        job.message = f"{job.message or 'Candidate crawl completed'} · Catalog creation failed: {exc.detail}"[:1024]
        db.commit()
        logger.warning("Automatic software catalog creation failed job_id=%s candidate_id=%s reason=%s",
                       job.id, job.target_id, exc.detail)
    except Exception:
        db.rollback()
        logger.exception("Automatic software catalog creation failed job_id=%s candidate_id=%s",
                         job.id, job.target_id)


def backfill_successful_candidate_crawls(db: Session) -> int:
    candidate_ids = db.scalars(select(Job.target_id).where(
        Job.job_type == JobType.CRAWL,
        Job.target_type == "candidate_auto_search",
        Job.status == JobStatus.SUCCESS,
    ).distinct().order_by(Job.target_id)).all()
    processed = 0
    for candidate_id in candidate_ids:
        try:
            candidate = db.get(SoftwareCandidate, candidate_id)
            before = (candidate.status, candidate.software_id) if candidate else None
            software = ensure_candidate_software(db, candidate_id)
            if before != (candidate.status, software.id):
                processed += 1
        except HTTPException as exc:
            logger.warning("Historical candidate catalog backfill skipped candidate_id=%s reason=%s",
                           candidate_id, exc.detail)
    return processed
