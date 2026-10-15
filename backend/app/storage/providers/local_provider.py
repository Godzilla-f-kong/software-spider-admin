from pathlib import Path

from app.storage.archive import ArchiveManager
from app.storage.exceptions import StorageError
from app.storage.models import ShareResult, UploadRequest, UploadResult


class LocalStorageProvider:
    def __init__(self, manager: ArchiveManager | None = None):
        self.manager = manager or ArchiveManager()

    def upload(self, request: UploadRequest) -> UploadResult:
        target = self.manager.resolve_relative(request.remote_path)
        if request.local_path.resolve() != target.resolve() or not target.is_file():
            raise StorageError("LOCAL_FILE_MISSING", "Verified archive file is unavailable")
        return UploadResult(request.remote_path, request.remote_path, target.stat().st_size)

    def delete(self, remote_path: str, access_token: str = "") -> None:
        target = self.manager.resolve_relative(remote_path)
        if target.is_file():
            target.unlink()

    def create_share(self, remote_file_id: str, access_token: str, password: str | None = None) -> ShareResult:
        raise StorageError("UNSUPPORTED_OPERATION", "Local storage cannot create public shares")

    def remove_share(self, share_id: str, access_token: str) -> None:
        raise StorageError("UNSUPPORTED_OPERATION", "Local storage has no public shares")

    def get_status(self, remote_path: str, access_token: str = "") -> bool:
        try:
            return self.manager.resolve_relative(remote_path).is_file()
        except ValueError:
            return False
