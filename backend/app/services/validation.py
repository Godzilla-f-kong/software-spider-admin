from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (CommerceListing, DownloadLink, GeneratedContent, Software, SoftwareArtifact,
                        SoftwareRelease, SoftwareSource, SoftwareVariant)
from app.spider.normalizers import URLNormalizer, URLSafetyValidator
from app.core.config import settings


def ensure_relations(db: Session, model: type, data: dict[str, Any]) -> None:
    checks = {
        "software_id": Software,
        "release_id": SoftwareRelease,
        "variant_id": SoftwareVariant,
        "artifact_id": SoftwareArtifact,
        "source_id": SoftwareSource,
        "generated_content_id": GeneratedContent,
    }
    for field, related_model in checks.items():
        if field in data and data[field] is not None and db.get(related_model, data[field]) is None:
            raise HTTPException(422, f"{field} does not exist")
    if model in (GeneratedContent, CommerceListing) and data.get("release_id"):
        release = db.get(SoftwareRelease, data["release_id"])
        if release and release.software_id != data.get("software_id"):
            raise HTTPException(422, "Release belongs to another software")
    if model is DownloadLink:
        source = db.get(SoftwareSource, data.get("source_id"))
        release = db.get(SoftwareRelease, data.get("release_id")) if data.get("release_id") else None
        if source and source.software_id != data.get("software_id"):
            raise HTTPException(422, "Source belongs to another software")
        if release and release.software_id != data.get("software_id"):
            raise HTTPException(422, "Release belongs to another software")
        try:
            URLSafetyValidator(allow_private=settings.allow_private_source_urls).validate(
                URLNormalizer.normalize(data.get("link_url", "")))
        except Exception as exc:
            raise HTTPException(422, "Invalid or unsafe link URL") from exc
        existing = db.scalar(select(DownloadLink).where(
            DownloadLink.source_id == data.get("source_id"),
            DownloadLink.release_id == data.get("release_id"),
            DownloadLink.link_url == data.get("link_url")))
        if existing and existing.id != data.get("id"):
            raise HTTPException(409, f"Download link already exists: {existing.id}")
    if model is CommerceListing and data.get("generated_content_id"):
        content = db.get(GeneratedContent, data["generated_content_id"])
        if content and content.software_id != data.get("software_id"):
            raise HTTPException(422, "Content belongs to another software")
    if model is SoftwareVariant and data.get("release_id"):
        existing = db.scalar(select(SoftwareVariant).where(
            SoftwareVariant.release_id == data["release_id"], SoftwareVariant.os == data.get("os"),
            SoftwareVariant.architecture == data.get("architecture"),
            SoftwareVariant.edition == data.get("edition"), SoftwareVariant.language == data.get("language")))
        if existing and existing.id != data.get("id"):
            raise HTTPException(409, f"Variant already exists: {existing.id}")
    if model is SoftwareArtifact and data.get("variant_id") and data.get("filename"):
        existing = db.scalar(select(SoftwareArtifact).where(
            SoftwareArtifact.variant_id == data["variant_id"], SoftwareArtifact.filename == data["filename"],
            SoftwareArtifact.package_type == data.get("package_type"), SoftwareArtifact.source_url == data.get("source_url")))
        if existing and existing.id != data.get("id"):
            raise HTTPException(409, f"Artifact already exists: {existing.id}")
