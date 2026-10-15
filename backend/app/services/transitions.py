from fastapi import HTTPException

from app.core import enums as e
from app.models import ArtifactStorage, CommerceListing, GeneratedContent, Job, Software, SoftwareArtifact, SoftwareCandidate, SoftwareRelease, SoftwareSource


TRANSITIONS: dict[type, dict[str, set[str]]] = {
    SoftwareCandidate: {
        "DISCOVERED": {"REVIEWING", "REJECTED", "IGNORED"},
        "REVIEWING": {"DISCOVERED", "REJECTED", "IGNORED"},
        "REJECTED": {"REVIEWING"}, "IGNORED": {"REVIEWING"}, "ACCEPTED": set(),
    },
    Software: {"ACTIVE": {"DISABLED"}, "DISABLED": {"ACTIVE"}, "ARCHIVED": {"ACTIVE"}},
    SoftwareSource: {"NEW": {"HEALTHY", "FAILED", "DISABLED"}, "HEALTHY": {"FAILED", "DISABLED"}, "FAILED": {"HEALTHY", "DISABLED"}, "DISABLED": {"NEW"}},
    SoftwareRelease: {"DISCOVERED": {"PROCESSING", "REJECTED"}, "PROCESSING": {"READY", "REJECTED"}, "READY": {"PUBLISHED", "REJECTED"}, "PUBLISHED": set(), "REJECTED": {"DISCOVERED"}},
    ArtifactStorage: {"PENDING": {"UPLOADING", "AVAILABLE", "FAILED"}, "UPLOADING": {"AVAILABLE", "FAILED"}, "AVAILABLE": {"EXPIRED", "FAILED"}, "FAILED": {"PENDING"}, "EXPIRED": {"PENDING"}},
    GeneratedContent: {"NOT_GENERATED": {"GENERATING", "DRAFT"}, "GENERATING": {"DRAFT"}, "DRAFT": {"REVIEWED"}, "REVIEWED": {"APPROVED", "DRAFT"}, "APPROVED": {"PUBLISHED", "DRAFT"}, "PUBLISHED": set()},
    CommerceListing: {"DRAFT": {"REVIEW_REQUIRED"}, "REVIEW_REQUIRED": {"APPROVED", "DRAFT"}, "APPROVED": {"PUBLISHED", "DRAFT"}, "PUBLISHED": {"PAUSED", "REMOVED"}, "PAUSED": {"PUBLISHED", "REMOVED"}, "REMOVED": set()},
    Job: {"PENDING": {"RUNNING", "CANCELLED"}, "RUNNING": {"SUCCESS", "FAILED", "CANCELLED"}, "SUCCESS": set(), "FAILED": set(), "CANCELLED": set()},
}


def validate_transition(model: type, current: object, new: object) -> None:
    before = str(getattr(current, "value", current))
    after = str(getattr(new, "value", new))
    if before == after:
        return
    if after not in TRANSITIONS.get(model, {}).get(before, set()):
        raise HTTPException(409, f"Invalid status transition: {before} -> {after}")


def validate_artifact_state(item: SoftwareArtifact, data: dict) -> None:
    for field in ("download_status", "verification_status", "signature_status", "local_path", "sha256", "md5", "resolved_url", "downloaded_at", "verified_at", "verification_details"):
        if field in data and data[field] != getattr(item, field):
            raise HTTPException(409, f"{field} is managed by a worker")
