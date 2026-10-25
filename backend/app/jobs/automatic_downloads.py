"""Queue downloads discovered by completed automatic candidate crawls."""
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.enums import JobStatus, JobType
from app.db.session import SessionLocal
from app.models import Job


def schedule_completed_crawl_downloads(db: Session | None = None, job_ids: list[int] | None = None) -> int:
    owns_session = db is None
    if db is None:
        db = SessionLocal()
    try:
        query = select(Job.id).where(
            Job.job_type == JobType.CRAWL,
            Job.target_type == "candidate_auto_search",
            Job.status == JobStatus.SUCCESS,
            Job.auto_download_processed.is_(False),
        ).order_by(Job.id)
        if job_ids is not None:
            if not job_ids:
                return 0
            query = query.where(Job.id.in_(job_ids))

        from app.jobs.download_runner import enqueue

        scheduled = 0
        for crawl_job_id in db.scalars(query).all():
            claimed = db.execute(update(Job).where(
                Job.id == crawl_job_id,
                Job.auto_download_processed.is_(False),
                Job.status == JobStatus.SUCCESS,
            ).values(auto_download_processed=True))
            if claimed.rowcount != 1:
                db.rollback()
                continue
            crawl_job = db.scalar(select(Job).where(Job.id == crawl_job_id).execution_options(populate_existing=True))
            if crawl_job is None:
                db.rollback()
                continue

            result = crawl_job.result or {}
            links: dict[str, dict] = {}
            for match in result.get("matches", []):
                candidate_name = match.get("candidate_name") or f"candidate-{crawl_job.target_id}"
                for artifact in match.get("artifacts", []):
                    url = artifact.get("url")
                    if url:
                        links.setdefault(url, {
                            "url": url,
                            "filename": artifact.get("filename"),
                            "kind": "DIRECT_FILE",
                            "label": artifact.get("filename"),
                            "candidate_name": candidate_name,
                            "crawl_job_id": crawl_job.id,
                            "page_url": match.get("page_url"),
                        })
                for link in match.get("links", []):
                    url = link.get("url")
                    if url:
                        links.setdefault(url, {
                            "url": url,
                            "filename": link.get("label"),
                            "kind": link.get("link_type") or "DOWNLOAD_PAGE",
                            "provider": link.get("provider") or "OTHER",
                            "access_code": link.get("access_code"),
                            "label": link.get("label"),
                            "candidate_name": candidate_name,
                            "crawl_job_id": crawl_job.id,
                            "page_url": match.get("page_url"),
                        })

            child_jobs = [Job(
                job_type=JobType.DOWNLOAD,
                target_type="crawl_link_download",
                target_id=crawl_job.id,
                status=JobStatus.PENDING,
                progress=0,
                message="Waiting for automatic link download",
                payload=payload,
            ) for payload in links.values()]
            db.add_all(child_jobs)
            db.commit()
            scheduled += len(child_jobs)
            for child in child_jobs:
                db.refresh(child)
                try:
                    queued = enqueue(child.id)
                except Exception:
                    queued = False
                if not queued:
                    child.message = "Waiting for an available download worker"
            db.commit()
        return scheduled
    finally:
        if owns_session:
            db.close()
