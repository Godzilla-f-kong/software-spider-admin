"""Import successfully archived crawl downloads into the software catalog."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import enums as e
from app.db.base import beijing_now
from app.models import (ArtifactStorage, DownloadLink, Job, Software, SoftwareArtifact,
                        SoftwareCandidate, SoftwareRelease, SoftwareSource, SoftwareVariant)
from app.services.catalog import ensure_candidate_software, set_latest_release
from app.spider.classifier import ArtifactClassifier
from app.storage.archive import ArchiveManager
from app.storage.providers.self_hosted_provider import SelfHostedPanProvider


def _crawl_match(crawl_job: Job, download_job: Job) -> dict:
    matches = (crawl_job.result or {}).get("matches", [])
    page_url = (download_job.payload or {}).get("page_url")
    return next((match for match in matches if page_url and match.get("page_url") == page_url),
                matches[0] if matches else {})


def _get_source(db: Session, software: Software, match: dict, download_job: Job) -> SoftwareSource:
    page_url = match.get("page_url") or (download_job.payload or {}).get("page_url")
    if not page_url:
        page_url = (download_job.payload or {}).get("url")
    source = db.scalar(select(SoftwareSource).where(
        SoftwareSource.software_id == software.id,
        SoftwareSource.source_url == page_url,
    ).limit(1))
    if source is None:
        source = SoftwareSource(
            software_id=software.id,
            source_type=e.SourceType.OTHER,
            source_url=page_url,
            adapter_type=e.AdapterType.GENERIC_HTML,
            status=e.SourceStatus.HEALTHY,
            automation_status=e.AutomationStatus.UNKNOWN,
            last_checked_at=download_job.finished_at or beijing_now(),
            last_success_at=download_job.finished_at or beijing_now(),
        )
        db.add(source)
        db.flush()
    return source


def _get_release(db: Session, software: Software, match: dict,
                 candidate: SoftwareCandidate) -> SoftwareRelease:
    versions = match.get("versions") or []
    version = str(versions[0] if versions else candidate.target_version or "Unknown")[:100]
    release = db.scalar(select(SoftwareRelease).where(
        SoftwareRelease.software_id == software.id,
        SoftwareRelease.version == version,
    ).limit(1))
    if release is None:
        release = SoftwareRelease(
            software_id=software.id,
            version=version,
            status=e.ReleaseStatus.DISCOVERED,
            is_latest=version != "Unknown" and not bool(db.scalar(select(SoftwareRelease.id).where(
                SoftwareRelease.software_id == software.id,
                SoftwareRelease.is_latest.is_(True),
            ).limit(1))),
        )
        db.add(release)
        db.flush()
        set_latest_release(db, release)
    return release


def import_successful_crawl_download(db: Session, download_job: Job) -> int:
    """Create release, platform, installer, local storage, and discovered links idempotently."""
    payload = download_job.payload or {}
    crawl_job_id = int(payload.get("crawl_job_id") or download_job.target_id)
    crawl_job = db.get(Job, crawl_job_id)
    if crawl_job is None or crawl_job.target_type != "candidate_auto_search":
        return 0
    candidate = db.get(SoftwareCandidate, crawl_job.target_id)
    if candidate is None:
        return 0
    software = ensure_candidate_software(db, candidate.id)
    match = _crawl_match(crawl_job, download_job)
    source = _get_source(db, software, match, download_job)
    release = _get_release(db, software, match, candidate)

    for item in match.get("links", []):
        link_url = item.get("url")
        if not link_url or db.scalar(select(DownloadLink.id).where(
                DownloadLink.software_id == software.id,
                DownloadLink.source_id == source.id,
                DownloadLink.link_url == link_url,
        ).limit(1)):
            continue
        try:
            provider = e.DownloadLinkProvider(item.get("provider", "OTHER"))
            link_type = e.DownloadLinkType(item.get("link_type", "DOWNLOAD_PAGE"))
        except ValueError:
            provider, link_type = e.DownloadLinkProvider.OTHER, e.DownloadLinkType.DOWNLOAD_PAGE
        db.add(DownloadLink(
            software_id=software.id,
            source_id=source.id,
            release_id=release.id,
            provider=provider,
            link_type=link_type,
            link_url=link_url,
            source_page_url=match.get("page_url"),
            access_code=item.get("access_code"),
            label=item.get("label"),
            review_status=e.LinkReviewStatus.DISCOVERED,
        ))

    imported = 0
    classifier = ArtifactClassifier()
    for file_info in (download_job.result or {}).get("files", []):
        local_path = file_info.get("local_path")
        if not local_path:
            continue
        try:
            archived_path = ArchiveManager().resolve_relative(local_path)
        except ValueError:
            continue
        if not archived_path.is_file():
            continue
        existing = db.scalar(select(SoftwareArtifact).where(
            SoftwareArtifact.local_path == local_path,
        ).limit(1))
        if existing is not None:
            continue

        filename = file_info.get("filename") or "download.bin"
        resolved_url = file_info.get("resolved_url") or file_info.get("source_url") or ""
        classification = classifier.classify(filename, resolved_url)
        variant = db.scalar(select(SoftwareVariant).where(
            SoftwareVariant.release_id == release.id,
            SoftwareVariant.os == classification.os,
            SoftwareVariant.architecture == classification.architecture,
            SoftwareVariant.cpu_family == classification.cpu_family,
        ).limit(1))
        if variant is None:
            variant = SoftwareVariant(release_id=release.id, os=classification.os,
                                      architecture=classification.architecture,
                                      cpu_family=classification.cpu_family,
                                      language=classification.language)
            db.add(variant)
            db.flush()

        artifact = SoftwareArtifact(
            variant_id=variant.id,
            package_type=classification.package_type,
            install_type=classification.install_type,
            filename=filename[:512],
            file_size=file_info.get("file_size"),
            source_url=payload.get("url"),
            local_path=local_path,
            resolved_url=resolved_url,
            sha256=file_info.get("sha256"),
            md5=file_info.get("md5") or SelfHostedPanProvider._md5(archived_path),
            downloaded_at=download_job.finished_at or beijing_now(),
            download_status=e.DownloadStatus.DOWNLOADED,
        )
        db.add(artifact)
        db.flush()
        storage = db.scalar(select(ArtifactStorage.id).where(
            ArtifactStorage.artifact_id == artifact.id,
            ArtifactStorage.provider == e.StorageProviderType.LOCAL,
        ).limit(1))
        if storage is None:
            db.add(ArtifactStorage(
                artifact_id=artifact.id,
                provider=e.StorageProviderType.LOCAL,
                remote_path=local_path,
                status=e.StorageStatus.AVAILABLE,
            ))
        imported += 1

    db.commit()
    return imported


def backfill_successful_crawl_downloads(db: Session) -> int:
    jobs = db.scalars(select(Job).where(
        Job.job_type == e.JobType.DOWNLOAD,
        Job.target_type == "crawl_link_download",
        Job.status == e.JobStatus.SUCCESS,
    ).order_by(Job.id)).all()
    return sum(import_successful_crawl_download(db, job) for job in jobs)
