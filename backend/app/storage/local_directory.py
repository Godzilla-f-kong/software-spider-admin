"""Resolve an archived artifact and open its directory on the backend host."""

import os
from pathlib import Path

from app.core.enums import StorageProviderType
from app.models import ArtifactStorage
from app.storage.archive import ArchiveManager


def archived_file_for_storage(storage: ArtifactStorage) -> Path | None:
    if storage.provider is not StorageProviderType.LOCAL:
        return None
    relative = storage.artifact.local_path
    if not relative:
        return None
    try:
        path = ArchiveManager().resolve_relative(relative)
    except ValueError:
        return None
    return path if path.is_file() else None


def open_local_directory(path: Path) -> None:
    if os.name != "nt":
        raise OSError("Opening a local directory requires a Windows backend")
    os.startfile(str(path.parent))
