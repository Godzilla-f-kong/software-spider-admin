from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (CommerceListing, GeneratedContent, Software, SoftwareArtifact,
                        SoftwareCandidate, SoftwareRelease, SoftwareSource, SoftwareVariant)


LOOKUP_MODELS = {
    "candidates": SoftwareCandidate,
    "software": Software,
    "sources": SoftwareSource,
    "releases": SoftwareRelease,
    "variants": SoftwareVariant,
    "artifacts": SoftwareArtifact,
    "content": GeneratedContent,
    "listings": CommerceListing,
}


def _label(db: Session, kind: str, item: object) -> str:
    if kind == "candidates":
        return f"{item.name} (#{item.id})"
    if kind == "software":
        return f"{item.name} (#{item.id})"
    if kind == "sources":
        return f"{item.software.name} / {item.source_type.value} / {item.source_url} (#{item.id})"
    if kind == "releases":
        return f"{item.software.name} / {item.version} (#{item.id})"
    if kind == "variants":
        return (f"{item.release.software.name} / {item.release.version} / "
                f"{item.os.value} {item.architecture.value} (#{item.id})")
    if kind == "artifacts":
        return (f"{item.variant.release.software.name} / {item.variant.release.version} / "
                f"{item.variant.os.value} {item.variant.architecture.value} / {item.filename} (#{item.id})")
    if kind == "content":
        software = db.get(Software, item.software_id)
        return f"{software.name if software else item.software_id} / {item.content_type.value} / {item.title or 'Untitled'} (#{item.id})"
    software = db.get(Software, item.software_id)
    return f"{software.name if software else item.software_id} / {item.platform.value} / {item.title} (#{item.id})"


def find_lookups(db: Session, kind: str, *, query: str = "", selected_id: int | None = None,
                 software_id: int | None = None, release_id: int | None = None,
                 variant_id: int | None = None, limit: int = 20) -> list[dict[str, object]]:
    model = LOOKUP_MODELS[kind]
    statement = select(model)
    if kind == "sources":
        statement = statement.join(Software, SoftwareSource.software_id == Software.id)
        search_columns = (Software.name, SoftwareSource.source_url)
    elif kind == "releases":
        statement = statement.join(Software, SoftwareRelease.software_id == Software.id)
        search_columns = (Software.name, SoftwareRelease.version)
    elif kind == "variants":
        statement = statement.join(SoftwareRelease, SoftwareVariant.release_id == SoftwareRelease.id).join(Software, SoftwareRelease.software_id == Software.id)
        search_columns = (Software.name, SoftwareRelease.version)
    elif kind == "artifacts":
        statement = statement.join(SoftwareVariant, SoftwareArtifact.variant_id == SoftwareVariant.id).join(
            SoftwareRelease, SoftwareVariant.release_id == SoftwareRelease.id).join(Software, SoftwareRelease.software_id == Software.id)
        search_columns = (Software.name, SoftwareRelease.version, SoftwareArtifact.filename)
    elif kind == "content":
        statement = statement.join(Software, GeneratedContent.software_id == Software.id)
        search_columns = (Software.name, GeneratedContent.title)
    elif kind == "listings":
        statement = statement.join(Software, CommerceListing.software_id == Software.id)
        search_columns = (Software.name, CommerceListing.title)
    elif kind == "candidates":
        search_columns = (SoftwareCandidate.name,)
    else:
        search_columns = (Software.name, Software.slug)

    if selected_id is not None:
        statement = statement.where(model.id == selected_id)
    else:
        if software_id is not None:
            if kind in ("sources", "releases", "content", "listings"):
                statement = statement.where(model.software_id == software_id)
            elif kind in ("variants", "artifacts"):
                statement = statement.where(SoftwareRelease.software_id == software_id)
        if release_id is not None:
            if kind == "variants":
                statement = statement.where(SoftwareVariant.release_id == release_id)
            elif kind == "artifacts":
                statement = statement.where(SoftwareVariant.release_id == release_id)
        if variant_id is not None and kind == "artifacts":
            statement = statement.where(SoftwareArtifact.variant_id == variant_id)
        if query.strip():
            pattern = f"%{query.strip()}%"
            clauses = [column.ilike(pattern) for column in search_columns]
            if query.strip().isdigit():
                clauses.append(model.id == int(query.strip()))
            statement = statement.where(or_(*clauses))

    items = db.scalars(statement.order_by(model.id.desc()).limit(limit)).all()
    return [{"id": item.id, "label": _label(db, kind, item)} for item in items]
