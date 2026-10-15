import shutil
import re
import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from email.message import Message
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from app.core.config import settings
from app.downloader.base import DownloadProgress, DownloadRequest, DownloadResult
from app.downloader.errors import DownloadError
from app.downloader.policy import DownloadPolicy, safe_filename


class HttpDownloader:
    def __init__(self, *, transport: httpx.BaseTransport | None = None, policy: DownloadPolicy | None = None):
        self.transport = transport
        self.policy = policy or DownloadPolicy()

    def download(self, request: DownloadRequest, progress: Callable[[DownloadProgress], None],
                 cancelled: Callable[[], bool]) -> DownloadResult:
        request.part_path.parent.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        last_error: DownloadError | None = None
        for attempt in range(settings.download_max_retries + 1):
            try:
                return self._once(request, progress, cancelled, start)
            except DownloadError as exc:
                last_error = exc
                if exc.code not in {"TIMEOUT", "CONNECTION_ERROR", "SERVER_ERROR", "HTTP_429", "CONTENT_LENGTH_MISMATCH"} or attempt == settings.download_max_retries:
                    raise
                if exc.code == "HTTP_429" and exc.retry_after is not None and exc.retry_after > 60:
                    raise DownloadError("HTTP_429", f"Rate limited; retry after {round(exc.retry_after)} seconds") from exc
                time.sleep(min(exc.retry_after if exc.retry_after is not None else 2 ** attempt, 60))
        raise last_error or DownloadError("UNKNOWN_ERROR", "Download failed")

    def _once(self, request: DownloadRequest, progress: Callable[[DownloadProgress], None],
              cancelled: Callable[[], bool], start: float) -> DownloadResult:
        timeout = httpx.Timeout(settings.download_timeout, connect=settings.download_connect_timeout)
        with httpx.Client(transport=self.transport, timeout=timeout, follow_redirects=False,
                          headers={"User-Agent": settings.download_user_agent, "Accept-Encoding": "identity"}) as client:
            current = self.policy.validate(request.url)
            source_url = current
            sidecar = request.part_path.with_suffix(".json")
            try:
                resume_info = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
            except (OSError, ValueError):
                resume_info = {}
            if request.part_path.exists() and resume_info.get("url") != current:
                request.part_path.unlink(missing_ok=True)
                sidecar.unlink(missing_ok=True)
                resume_info = {}
            offset = request.part_path.stat().st_size if request.part_path.exists() else 0
            for hop in range(8):
                if cancelled():
                    raise DownloadError("CANCELLED", "Download cancelled")
                headers = {"Range": f"bytes={offset}-"} if offset else {}
                if offset and resume_info.get("validator"):
                    headers["If-Range"] = resume_info["validator"]
                try:
                    with client.stream("GET", current, headers=headers) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location:
                                raise DownloadError("REDIRECT_BLOCKED", "Redirect has no Location")
                            current = self.policy.validate(urljoin(current, location), redirect=True)
                            continue
                        if response.status_code == 416 and offset:
                            request.part_path.unlink(missing_ok=True)
                            offset = 0
                            continue
                        if response.status_code in {401, 403, 404, 429}:
                            delay = None
                            if response.status_code == 429:
                                raw_delay = response.headers.get("Retry-After", "")
                                try:
                                    delay = float(raw_delay) if raw_delay else None
                                except ValueError:
                                    try:
                                        delay = max(0, (parsedate_to_datetime(raw_delay) - datetime.now(timezone.utc)).total_seconds())
                                    except (TypeError, ValueError, OverflowError):
                                        pass
                            raise DownloadError(f"HTTP_{response.status_code}", f"Remote server returned {response.status_code}", delay)
                        if response.status_code >= 500:
                            raise DownloadError("SERVER_ERROR", f"Remote server returned {response.status_code}")
                        if response.status_code not in {200, 206}:
                            raise DownloadError("SERVER_ERROR", f"Unexpected HTTP {response.status_code}")
                        if response.headers.get("Content-Encoding", "identity").lower() not in {"identity", ""}:
                            raise DownloadError("VERIFICATION_FAILED", "Unexpected compressed HTTP transfer encoding")
                        if response.status_code == 206:
                            content_range = response.headers.get("Content-Range", "")
                            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", content_range)
                            if not match or int(match.group(1)) != offset or int(match.group(2)) < offset:
                                request.part_path.unlink(missing_ok=True)
                                raise DownloadError("CONTENT_LENGTH_MISMATCH", "Invalid Content-Range")
                            if match.group(3) != "*" and int(match.group(2)) >= int(match.group(3)):
                                raise DownloadError("CONTENT_LENGTH_MISMATCH", "Invalid Content-Range total")
                            if match.group(3) != "*" and int(match.group(2)) + 1 != int(match.group(3)):
                                raise DownloadError("CONTENT_LENGTH_MISMATCH", "Partial Range response did not reach end of file")
                        elif offset:
                            offset = 0  # 200 ignores Range: truncate, never append.
                        validator = response.headers.get("ETag") or response.headers.get("Last-Modified")
                        sidecar.write_text(json.dumps({"url": source_url, "validator": validator}), encoding="utf-8")
                        length = response.headers.get("Content-Length", "")
                        remaining = int(length) if length.isdigit() else None
                        if response.status_code == 206 and remaining is not None and remaining != int(match.group(2)) - offset + 1:
                            raise DownloadError("CONTENT_LENGTH_MISMATCH", "Content-Range and Content-Length disagree")
                        total = offset + remaining if remaining is not None else None
                        if settings.download_max_file_size and total and total > settings.download_max_file_size:
                            raise DownloadError("MAX_FILE_SIZE_EXCEEDED", "Download exceeds configured limit")
                        free = shutil.disk_usage(request.part_path.parent).free
                        if free < max(settings.download_min_free_space, (remaining or 0) + 64 * 1024 * 1024):
                            raise DownloadError("INSUFFICIENT_DISK_SPACE", "Not enough free disk space")
                        filename = self._filename(response.headers.get("Content-Disposition"), request.expected_filename, current)
                        downloaded = offset
                        next_disk_check = offset + 64 * 1024 * 1024
                        with request.part_path.open("ab" if offset else "wb") as output:
                            for chunk in response.iter_bytes(chunk_size=settings.download_chunk_size):
                                if cancelled():
                                    raise DownloadError("CANCELLED", "Download cancelled")
                                if not chunk:
                                    continue
                                downloaded += len(chunk)
                                if downloaded >= next_disk_check:
                                    if shutil.disk_usage(request.part_path.parent).free < settings.download_min_free_space:
                                        raise DownloadError("INSUFFICIENT_DISK_SPACE", "Free disk space fell below the configured minimum")
                                    next_disk_check = downloaded + 64 * 1024 * 1024
                                if settings.download_max_file_size and downloaded > settings.download_max_file_size:
                                    raise DownloadError("MAX_FILE_SIZE_EXCEEDED", "Download exceeds configured limit")
                                output.write(chunk)
                                elapsed = max(time.monotonic() - start, .001)
                                progress(DownloadProgress(downloaded, total, downloaded / elapsed))
                        if total is not None and downloaded != total:
                            raise DownloadError("CONTENT_LENGTH_MISMATCH", "Received byte count differs from Content-Length")
                        if downloaded == 0:
                            raise DownloadError("VERIFICATION_FAILED", "Downloaded file is empty")
                        sidecar.unlink(missing_ok=True)
                        return DownloadResult(request.part_path, filename, downloaded,
                                              response.headers.get("Content-Type"), current, time.monotonic() - start,
                                              response.status_code)
                except httpx.TimeoutException as exc:
                    raise DownloadError("TIMEOUT", "Download request timed out") from exc
                except httpx.RequestError as exc:
                    raise DownloadError("CONNECTION_ERROR", "Download connection failed") from exc
            raise DownloadError("REDIRECT_BLOCKED", "Too many redirects")

    @staticmethod
    def _filename(disposition: str | None, expected: str, url: str) -> str:
        message = Message()
        message["Content-Disposition"] = disposition or ""
        candidate = message.get_filename() or expected or unquote(Path(urlsplit(url).path).name) or "download.bin"
        return safe_filename(candidate)
