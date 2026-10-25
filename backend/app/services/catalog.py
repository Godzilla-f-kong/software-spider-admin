import re
import unicodedata

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import CandidateStatus, DownloadStatus, JobStatus, JobType, SoftwareStatus
from app.models import Job, Software, SoftwareArtifact, SoftwareCandidate, SoftwareRelease
from app.storage.archive import ArchiveManager


def slugify(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def accept_candidate(db: Session, candidate_id: int) -> Software:
    candidate = db.get(SoftwareCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Candidate not found")
    if candidate.status == CandidateStatus.ACCEPTED:
        raise HTTPException(409, "Candidate already accepted")
    base_slug = slugify(candidate.name)
    if not base_slug:
        raise HTTPException(422, "Name cannot be converted to a slug; create software manually")
    existing = db.scalar(select(Software).where(Software.slug == base_slug))
    if existing:
        raise HTTPException(409, f"Software already exists: {existing.id}")
    software = Software(name=candidate.name, slug=base_slug, category=candidate.category,
                        official_url=candidate.source_url, status=SoftwareStatus.ACTIVE)
    db.add(software)
    db.flush()
    candidate.status = CandidateStatus.ACCEPTED
    candidate.software_id = software.id
    db.commit()
    db.refresh(software)
    return software


def ensure_candidate_software(db: Session, candidate_id: int) -> Software:
    """Create or link a catalog record for a successfully crawled candidate."""
    candidate = db.get(SoftwareCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Candidate not found")
    if candidate.status in {CandidateStatus.REJECTED, CandidateStatus.IGNORED}:
        raise HTTPException(409, f"Candidate is {candidate.status.value.lower()}")
    if candidate.software_id:
        software = db.get(Software, candidate.software_id)
        if software:
            if candidate.status != CandidateStatus.ACCEPTED:
                candidate.status = CandidateStatus.ACCEPTED
                db.commit()
            return software

    base_slug = slugify(candidate.name)
    if not base_slug:
        raise HTTPException(422, "Name cannot be converted to a slug; create software manually")
    existing = db.scalar(select(Software).where(Software.slug == base_slug))
    if existing:
        if existing.name.strip().casefold() != candidate.name.strip().casefold():
            raise HTTPException(409, f"Software slug conflicts with a different name: {existing.id}")
        software = existing
    else:
        software = Software(name=candidate.name, slug=base_slug, category=candidate.category,
                            official_url=candidate.source_url, status=SoftwareStatus.ACTIVE)
        db.add(software)
        db.flush()

    candidate.status = CandidateStatus.ACCEPTED
    candidate.software_id = software.id
    db.commit()
    db.refresh(software)
    return software


def set_latest_release(db: Session, release: SoftwareRelease) -> None:
    if release.is_latest:
        for previous in db.scalars(select(SoftwareRelease).where(
            SoftwareRelease.software_id == release.software_id,
            SoftwareRelease.id != release.id,
            SoftwareRelease.is_latest.is_(True),
        )):
            previous.is_latest = False


def create_artifact_job(db: Session, artifact_id: int, job_type: JobType, *, redownload: bool = False) -> Job:
    artifact = db.get(SoftwareArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, "Artifact not found")
    if job_type == JobType.DOWNLOAD and not artifact.source_url:
        raise HTTPException(422, "Artifact source_url is required for download")
    manager = ArchiveManager()
    local_exists = False
    if artifact.local_path:
        try:
            local_exists = manager.resolve_relative(artifact.local_path).is_file()
        except ValueError:
            pass
    if job_type == JobType.DOWNLOAD and local_exists and not redownload:
        raise HTTPException(409, "Already downloaded; use Re-download")
    if job_type != JobType.DOWNLOAD:
        raise HTTPException(422, "Only artifact download jobs can be created")
    existing = db.scalar(select(Job).where(Job.job_type == job_type, Job.target_type == "artifact",
                                                Job.target_id == artifact_id, Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING])))
    if existing:
        return existing
    other = db.scalar(select(Job).where(Job.job_type == JobType.DOWNLOAD,
        Job.job_type != job_type, Job.target_type == "artifact", Job.target_id == artifact_id,
        Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING])).limit(1))
    if other:
        raise HTTPException(409, "A download job is active for this artifact")
    job = Job(job_type=job_type, target_type="artifact", target_id=artifact_id,
              status=JobStatus.PENDING, progress=0, message="Awaiting a worker",
              payload={"redownload": redownload} if job_type == JobType.DOWNLOAD else None)
    db.add(job)
    if job_type == JobType.DOWNLOAD:
        artifact.download_status = DownloadStatus.QUEUED
    db.commit()
    db.refresh(job)
    return job
