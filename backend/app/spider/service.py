import logging
import time
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import (AdapterType, AutomationStatus, DownloadStatus, LinkReviewStatus, ReleaseStatus,
                            SourceStatus, VerificationStatus)
from app.models import DownloadLink, Software, SoftwareArtifact, SoftwareRelease, SoftwareSource, SoftwareVariant
from app.spider.adapters import SourceAdapterFactory, SourceInput
from app.spider.errors import SpiderError
from app.spider.http import SpiderHttpClient
from app.spider.result import DiscoveryResult

logger = logging.getLogger(__name__)


class SpiderService:
    def discover(self, source: SoftwareSource, *, http: SpiderHttpClient | None = None,
                 job_id: int | None = None) -> DiscoveryResult:
        if not source.enabled or source.automation_status is AutomationStatus.DISABLED:
            raise SpiderError("MANUAL_REQUIRED", "Source is disabled")
        if source.automation_status is AutomationStatus.MANUAL_REQUIRED:
            raise SpiderError("MANUAL_REQUIRED", "Source requires manual review")
        if source.adapter_type in {AdapterType.MANUAL, AdapterType.BROWSER}:
            raise SpiderError("MANUAL_REQUIRED", "Adapter requires manual review")
        started = time.monotonic()
        parts = urlsplit(source.source_url)
        safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        logger.info("Spider discovery started job_id=%s source_id=%s software_id=%s adapter=%s url=%s",
                    job_id, source.id, source.software_id, source.adapter_type.value, safe_url)
        own_client = http is None
        http = http or SpiderHttpClient()
        try:
            result = SourceAdapterFactory.create(source.adapter_type, http).discover(
                SourceInput(source.id, source.software_id, source.source_url))
            result.source_metadata["source_url"] = source.source_url
            logger.info("Spider discovery completed job_id=%s source_id=%s software_id=%s adapter=%s "
                        "releases=%s artifacts=%s links=%s duration=%.2fs",
                        job_id, source.id, source.software_id, source.adapter_type.value,
                        len(result.releases), result.artifact_count, result.link_count, time.monotonic() - started)
            return result
        except SpiderError as exc:
            logger.warning("Spider discovery failed job_id=%s source_id=%s software_id=%s adapter=%s "
                           "error_type=%s duration=%.2fs", job_id, source.id, source.software_id,
                           source.adapter_type.value, exc.code, time.monotonic() - started)
            raise
        finally:
            if own_client:
                http.close()


class DiscoveryPersistenceService:
    def annotate(self, db: Session, result: DiscoveryResult) -> DiscoveryResult:
        for release in result.releases:
            existing = None
            if not release.version:
                release.status = "UNKNOWN"
                for artifact in release.artifacts: artifact.status = "UNKNOWN"
            else:
                existing = db.scalar(select(SoftwareRelease).where(
                    SoftwareRelease.software_id == result.software_id, SoftwareRelease.version == release.version))
                release.status = "EXISTING" if existing else "NEW"
            for link in release.links:
                link.status = "EXISTING" if db.scalar(select(DownloadLink.id).where(
                    DownloadLink.source_id == result.source_id,
                    DownloadLink.release_id == (existing.id if existing else None),
                    DownloadLink.link_url == link.link_url)) else "NEW"
            if not release.version:
                continue
            for artifact in release.artifacts:
                artifact.status = "NEW"
                if not existing: continue
                variant = db.scalar(select(SoftwareVariant).where(
                    SoftwareVariant.release_id == existing.id, SoftwareVariant.os == artifact.os,
                    SoftwareVariant.architecture == artifact.architecture,
                    SoftwareVariant.edition == artifact.edition,
                    SoftwareVariant.language == artifact.language))
                if variant and db.scalar(select(SoftwareArtifact.id).where(
                    SoftwareArtifact.variant_id == variant.id, SoftwareArtifact.filename == artifact.filename,
                    SoftwareArtifact.package_type == artifact.package_type,
                    SoftwareArtifact.source_url == artifact.download_url)):
                    artifact.status = "EXISTING"
        return result

    def import_result(self, db: Session, result: DiscoveryResult) -> dict[str, int]:
        source = db.get(SoftwareSource, result.source_id)
        if source is None or source.software_id != result.software_id:
            raise SpiderError("INVALID_SOURCE", "Discovery source no longer belongs to this software")
        if result.source_metadata.get("source_url") and result.source_metadata["source_url"] != source.source_url:
            raise SpiderError("INVALID_SOURCE", "Source URL changed since preview; run discovery again")
        # Lock the parent row so concurrent imports for one software serialize.
        db.scalar(select(Software).where(Software.id == result.software_id).with_for_update())
        counts = {"releases": 0, "variants": 0, "artifacts": 0, "links": 0, "skipped_unknown_version": 0}
        for candidate in result.releases:
            release = None
            if not candidate.version or len(candidate.version) > 100:
                if candidate.artifacts:
                    counts["skipped_unknown_version"] += 1
            else:
                release = db.scalar(select(SoftwareRelease).where(
                    SoftwareRelease.software_id == result.software_id,
                    SoftwareRelease.version == candidate.version))
                if release is None:
                    release = SoftwareRelease(software_id=result.software_id, version=candidate.version,
                                              release_date=candidate.release_date,
                                              release_notes=candidate.release_notes, status=ReleaseStatus.DISCOVERED)
                    db.add(release)
                    db.flush()
                    counts["releases"] += 1
            for link in candidate.links:
                if db.scalar(select(DownloadLink.id).where(
                    DownloadLink.source_id == source.id, DownloadLink.release_id == (release.id if release else None),
                    DownloadLink.link_url == link.link_url)):
                    continue
                db.add(DownloadLink(software_id=result.software_id, source_id=source.id,
                                    release_id=release.id if release else None, provider=link.provider,
                                    link_type=link.link_type, link_url=link.link_url,
                                    source_page_url=link.source_page_url, access_code=link.access_code,
                                    label=link.label, context_text=link.context_text,
                                    review_status=LinkReviewStatus.DISCOVERED))
                db.flush()
                counts["links"] += 1
            if release is None:
                continue
            for asset in candidate.artifacts:
                variant = db.scalar(select(SoftwareVariant).where(
                    SoftwareVariant.release_id == release.id, SoftwareVariant.os == asset.os,
                    SoftwareVariant.architecture == asset.architecture,
                    SoftwareVariant.edition == asset.edition, SoftwareVariant.language == asset.language))
                if variant is None:
                    variant = SoftwareVariant(release_id=release.id, os=asset.os,
                                              architecture=asset.architecture, edition=asset.edition,
                                              language=asset.language)
                    db.add(variant)
                    db.flush()
                    counts["variants"] += 1
                exists = db.scalar(select(SoftwareArtifact.id).where(
                    SoftwareArtifact.variant_id == variant.id, SoftwareArtifact.filename == asset.filename,
                    SoftwareArtifact.package_type == asset.package_type,
                    SoftwareArtifact.source_url == asset.download_url))
                if exists: continue
                db.add(SoftwareArtifact(variant_id=variant.id, package_type=asset.package_type,
                                        filename=asset.filename, file_size=asset.file_size,
                                        source_url=asset.download_url,
                                        download_status=DownloadStatus.NOT_DOWNLOADED,
                                        verification_status=VerificationStatus.PENDING))
                db.flush()
                counts["artifacts"] += 1
        db.commit()
        return counts


def compare_latest(db: Session, result: DiscoveryResult) -> dict[str, str | None]:
    remote = next((release for release in result.releases if release.version and not release.is_prerelease), None)
    if remote is None:
        return {"status": "UNKNOWN", "remote_version": None, "local_version": None}
    local = db.scalar(select(SoftwareRelease).where(SoftwareRelease.software_id == result.software_id,
                                                     SoftwareRelease.is_latest.is_(True)).limit(1))
    if local is None:
        local = db.scalar(select(SoftwareRelease).where(SoftwareRelease.software_id == result.software_id)
                          .order_by(SoftwareRelease.release_date.desc(), SoftwareRelease.id.desc()).limit(1))
    if local is None:
        status = "NEW_RELEASE"
    elif local.version == remote.version:
        status = "NO_CHANGE"
    elif remote.release_date and local.release_date and remote.release_date > local.release_date:
        status = "NEW_RELEASE"
    else:
        status = "UNKNOWN"
    return {"status": status, "remote_version": remote.version,
            "local_version": local.version if local else None}
