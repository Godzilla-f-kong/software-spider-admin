"""Uploader for the private software_spider cloud drive integration API."""
import hashlib
import logging
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.core.config import settings
from app.storage.exceptions import StorageError
from app.storage.models import UploadRequest, UploadResult
from app.storage.self_hosted_categories import SELF_HOSTED_FILE_ARCH_CATEGORIES

logger = logging.getLogger(__name__)


class SelfHostedPanProvider:
    def __init__(self, client: httpx.Client | None = None):
        self.base_url = settings.self_hosted_base_url.rstrip("/")
        parts = urlsplit(self.base_url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise StorageError("INVALID_CONFIGURATION", "SELF_HOSTED_BASE_URL must be an HTTP(S) origin")
        if not settings.self_hosted_api_key:
            raise StorageError("NOT_CONFIGURED", "Set SELF_HOSTED_API_KEY")
        if not settings.self_hosted_username:
            raise StorageError("NOT_CONFIGURED", "Set SELF_HOSTED_USERNAME")
        if settings.self_hosted_chunk_size < 64 * 1024 or settings.self_hosted_chunk_size > 16 * 1024 * 1024:
            raise StorageError("INVALID_CONFIGURATION", "SELF_HOSTED_CHUNK_SIZE must be between 64 KiB and 16 MiB")
        self.client = client or httpx.Client(timeout=settings.self_hosted_timeout, follow_redirects=False)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def categories(self) -> list[str]:
        try:
            response = self.client.get(
                f"{self.base_url}/filearch/categories",
                headers={"X-Integration-Key": settings.self_hosted_api_key},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise StorageError("CLOUD_API_ERROR", "Could not load cloud-drive file_arch categories") from exc
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise StorageError("CLOUD_INVALID_RESPONSE", "Cloud-drive category response is invalid")
        return items

    def upload(self, request: UploadRequest) -> UploadResult:
        path = request.local_path
        if not path.is_file():
            raise StorageError("LOCAL_FILE_MISSING", "Verified archive file is missing")
        size = path.stat().st_size
        if size <= 0 or size > 2_147_483_647:
            raise StorageError("FILE_SIZE_UNSUPPORTED", "Cloud-drive metadata currently supports files up to 2 GiB")
        metadata = request.metadata or {}
        category = str(metadata.get("file_arch", ""))
        if category not in SELF_HOSTED_FILE_ARCH_CATEGORIES:
            raise StorageError("INVALID_CATEGORY", "Select a file_arch category returned by the cloud drive")

        identifier = f"{self._md5(path)}_{request.artifact_id}"
        chunk_size = settings.self_hosted_chunk_size
        total_chunks = (size + chunk_size - 1) // chunk_size
        sent = 0
        remote_path: str | None = None
        with path.open("rb") as stream:
            for chunk_number in range(1, total_chunks + 1):
                content = stream.read(chunk_size)
                fields = {
                    "taskId": str(request.artifact_id),
                    "chunkNumber": str(chunk_number),
                    "chunkSize": str(chunk_size),
                    "totalChunks": str(total_chunks),
                    "identifier": identifier,
                }
                try:
                    response = self.client.post(
                        f"{self.base_url}/integration/file/chunk",
                        headers={"X-Integration-Key": settings.self_hosted_api_key},
                        data=fields,
                        files={"file": (path.name, content, "application/octet-stream")},
                    )
                    response.raise_for_status()
                    result = response.json()
                except httpx.HTTPStatusError as exc:
                    raise StorageError("CLOUD_CHUNK_UPLOAD_FAILED",
                        f"Cloud drive returned HTTP {exc.response.status_code} at chunk {chunk_number}/{total_chunks}") from exc
                except httpx.RequestError as exc:
                    raise StorageError("CLOUD_CHUNK_UPLOAD_FAILED",
                        f"Cloud drive connection failed ({type(exc).__name__}) at chunk {chunk_number}/{total_chunks}") from exc
                except ValueError as exc:
                    raise StorageError("CLOUD_CHUNK_UPLOAD_FAILED",
                        f"Cloud drive returned invalid JSON at chunk {chunk_number}/{total_chunks}") from exc
                # 云盘旧分片接口对成功的中间片返回空对象。
                expected = "上传完毕" if chunk_number == total_chunks else "第一片上传成功"
                if chunk_number not in {1, total_chunks}:
                    accepted = result == {}
                else:
                    accepted = isinstance(result, dict) and result.get("result") == expected
                if not accepted:
                    raise StorageError("CLOUD_CHUNK_UPLOAD_FAILED", f"Cloud drive rejected chunk {chunk_number}/{total_chunks}")
                if chunk_number == total_chunks:
                    remote_path = result.get("path")
                sent += len(content)
                if request.progress:
                    request.progress(sent, size)

        if not remote_path:
            raise StorageError("CLOUD_UPLOAD_INCOMPLETE", "Cloud drive did not return a completed file path")
        try:
            response = self.client.post(
                f"{self.base_url}/integration/file/complete",
                headers={"X-Integration-Key": settings.self_hosted_api_key},
                json={
                    "filename": path.name,
                    "filesize": size,
                    "filetype": 5,
                    "file_arch": category,
                    "fileindex": remote_path,
                    "fileusername": settings.self_hosted_username,
                    "filemodal": 0,
                    "create": True,
                    "identifier": identifier,
                },
            )
            response.raise_for_status()
            completed = response.json()
        except httpx.HTTPStatusError as exc:
            raise StorageError("CLOUD_METADATA_FAILED",
                f"Cloud drive returned HTTP {exc.response.status_code} while registering file metadata") from exc
        except httpx.RequestError as exc:
            raise StorageError("CLOUD_METADATA_FAILED",
                f"Cloud drive connection failed ({type(exc).__name__}) while registering file metadata") from exc
        except ValueError as exc:
            raise StorageError("CLOUD_METADATA_FAILED", "Cloud drive returned invalid JSON while registering file metadata") from exc
        if not isinstance(completed, dict) or not completed.get("success"):
            raise StorageError("CLOUD_METADATA_FAILED", "Cloud drive did not confirm the file record")
        remote_file_id = str(completed.get("fileid") or remote_path)
        logger.info("Self-hosted cloud upload completed artifact_id=%s bytes=%s", request.artifact_id, size)
        return UploadResult(remote_path=remote_path, remote_file_id=remote_file_id, size=size)

    @staticmethod
    def _md5(path: Path) -> str:
        digest = hashlib.md5()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
