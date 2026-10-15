"""Baidu Netdisk OAuth and official three-step slice upload API."""
import hashlib
import json
import secrets
import logging
from pathlib import Path
from urllib.parse import urlsplit
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.storage.exceptions import StorageError
from app.storage.models import ShareResult, UploadRequest, UploadResult

# Baidu requires access_token in query parameters. Do not let transport
# request logging print that URL when the Admin enables INFO/DEBUG logging.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class BaiduPanProvider:
    FILE_API = "https://pan.baidu.com/rest/2.0/xpan/file"
    LOCATE_API = "https://d.pcs.baidu.com/rest/2.0/pcs/file"
    SHARE_API = "https://pan.baidu.com/apaas/1.0/share/set"
    TOKEN_API = "https://openapi.baidu.com/oauth/2.0/token"
    AUTH_API = "https://openapi.baidu.com/oauth/2.0/authorize"

    def __init__(self, client: httpx.Client | None = None, chunk_size: int | None = None):
        self.client = client or httpx.Client(timeout=httpx.Timeout(120, connect=15), follow_redirects=False)
        self._owns_client = client is None
        self.chunk_size = chunk_size or settings.storage_upload_chunk_size
        if self.chunk_size < 1 or self.chunk_size > 4 * 1024 * 1024:
            raise ValueError("Baidu upload chunk size must be between 1 and 4 MiB")

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    @classmethod
    def authorization_url(cls, state: str) -> str:
        if not settings.baidu_app_key:
            raise StorageError("NOT_CONFIGURED", "Set BAIDU_APP_KEY first")
        return cls.AUTH_API + "?" + urlencode({"response_type": "code", "client_id": settings.baidu_app_key,
            "redirect_uri": settings.baidu_redirect_uri, "scope": "basic,netdisk", "state": state})

    def exchange_code(self, code: str) -> dict:
        return self._token({"grant_type": "authorization_code", "code": code,
                            "redirect_uri": settings.baidu_redirect_uri})

    def refresh_token(self, refresh_token: str) -> dict:
        return self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def _token(self, data: dict[str, str]) -> dict:
        if not settings.baidu_app_key or not settings.baidu_app_secret:
            raise StorageError("NOT_CONFIGURED", "Set BAIDU_APP_KEY and BAIDU_APP_SECRET")
        try:
            response = self.client.post(self.TOKEN_API, data={**data, "client_id": settings.baidu_app_key,
                                        "client_secret": settings.baidu_app_secret})
            response.raise_for_status()
            value = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise StorageError("OAUTH_FAILED", "Baidu OAuth request failed") from exc
        if "access_token" not in value or "refresh_token" not in value:
            raise StorageError("OAUTH_FAILED", "Baidu did not return access and refresh tokens")
        return value

    def _request(self, url: str, method: str, token: str, *, query: dict | None = None,
                 data: dict | None = None, files: dict | None = None) -> dict:
        params = {"access_token": token, **(query or {})}
        try:
            response = self.client.request(method, url, params=params, data=data, files=files)
            response.raise_for_status()
            value = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise StorageError("BAIDU_HTTP_ERROR", "Baidu API request failed") from exc
        if not isinstance(value, dict):
            raise StorageError("BAIDU_INVALID_RESPONSE", "Baidu returned an invalid response")
        errno = value.get("errno", value.get("error_code", 0))
        if errno not in (0, "0", None):
            raise StorageError("BAIDU_API_ERROR", f"Baidu API error code {errno}")
        return value

    def upload(self, request: UploadRequest) -> UploadResult:
        path = request.local_path
        if not path.is_file() or path.stat().st_size <= 0:
            raise StorageError("LOCAL_FILE_MISSING", "Verified archive file is empty or missing")
        if not request.remote_path.startswith("/apps/") or ".." in Path(request.remote_path).parts:
            raise StorageError("INVALID_REMOTE_PATH", "Baidu destination must be inside the app folder")
        size = path.stat().st_size
        hashes: list[str] = []
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(self.chunk_size), b""):
                hashes.append(hashlib.md5(chunk).hexdigest())  # Baidu's slice protocol uses MD5.
        pre = self._request(self.FILE_API, "POST", request.access_token, query={"method": "precreate"},
                            data={"path": request.remote_path, "size": str(size), "isdir": "0",
                                  "autoinit": "1", "rtype": "0", "block_list": json.dumps(hashes)})
        upload_id = pre.get("uploadid")
        if not upload_id:
            raise StorageError("BAIDU_INVALID_RESPONSE", "Precreate returned no upload ID")
        location = self._request(self.LOCATE_API, "GET", request.access_token,
            query={"method": "locateupload", "appid": "250528", "path": request.remote_path,
                   "uploadid": upload_id, "upload_version": "2.0"})
        servers = location.get("servers") or []
        host = next((item.get("server") for item in servers if isinstance(item, dict)
                     and str(item.get("server", "")).startswith("https://")), None)
        if not host or not (urlsplit(host).hostname or "").endswith(".pcs.baidu.com"):
            raise StorageError("BAIDU_INVALID_RESPONSE", "Baidu did not return a safe HTTPS upload host")
        slice_api = host.rstrip("/") + "/rest/2.0/pcs/superfile2"
        required = set(pre.get("block_list", list(range(len(hashes)))))
        sent = 0
        block_list = hashes.copy()
        with path.open("rb") as stream:
            for index, expected_md5 in enumerate(hashes):
                chunk = stream.read(self.chunk_size)
                if index in required:
                    part = self._request(slice_api, "POST", request.access_token,
                        query={"method": "upload", "type": "tmpfile", "path": request.remote_path,
                               "uploadid": upload_id, "partseq": index},
                        files={"file": (path.name, chunk, "application/octet-stream")})
                    returned_md5 = part.get("md5")
                    if not returned_md5 or returned_md5.lower() != expected_md5:
                        raise StorageError("SLICE_MISMATCH", f"Baidu slice {index} checksum mismatch")
                    block_list[index] = returned_md5
                sent += len(chunk)
                if request.progress:
                    request.progress(sent, size)
        created = self._request(self.FILE_API, "POST", request.access_token, query={"method": "create"},
                                data={"path": request.remote_path, "size": str(size), "isdir": "0",
                                      "rtype": "0", "uploadid": upload_id,
                                      "block_list": json.dumps(block_list)})
        fs_id = created.get("fs_id")
        if not fs_id:
            raise StorageError("BAIDU_INVALID_RESPONSE", "File create returned no fs_id")
        return UploadResult(str(created.get("path") or request.remote_path), str(fs_id), size)

    def create_share(self, remote_file_id: str, access_token: str, password: str | None = None) -> ShareResult:
        if not settings.baidu_app_id:
            raise StorageError("NOT_CONFIGURED", "Set BAIDU_APP_ID and activate Baidu's paid file-share service")
        code = password or "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(4))
        if len(code) != 4 or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789" for char in code):
            raise StorageError("INVALID_SHARE_PASSWORD", "Share password must be four lowercase letters or digits")
        fields = {"fsid_list": (None, json.dumps([str(remote_file_id)])), "period": (None, "7"),
                  "pwd": (None, code)}
        result = self._request(self.SHARE_API, "POST", access_token,
                               query={"product": "netdisk", "appid": settings.baidu_app_id}, files=fields)
        data = result.get("data") or {}
        url = data.get("link")
        share_id = data.get("share_id")
        if not url or not share_id:
            raise StorageError("BAIDU_INVALID_RESPONSE", "Share creation returned no link or share ID")
        return ShareResult(str(share_id), str(url), str(data.get("pwd") or code))

    def remove_share(self, share_id: str, access_token: str) -> None:
        raise StorageError("NOT_SUPPORTED_BY_OPEN_API", "Baidu's documented open API has no cancel-share endpoint; cancel it in Baidu Pan")

    def delete(self, remote_path: str, access_token: str = "") -> None:
        self._request(self.FILE_API, "POST", access_token, query={"method": "filemanager", "opera": "delete"},
                      data={"async": "0", "filelist": json.dumps([remote_path])})

    def get_status(self, remote_path: str, access_token: str = "") -> bool:
        result = self._request("https://pan.baidu.com/rest/2.0/xpan/multimedia", "GET", access_token,
                               query={"method": "filemetas", "fsids": json.dumps([int(remote_path)])})
        return bool(result.get("list"))
