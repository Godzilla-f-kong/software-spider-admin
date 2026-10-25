import time
from email.message import Message
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.core.config import settings
from app.spider.errors import SpiderError
from app.spider.normalizers import URLSafetyValidator

class SpiderHttpClient:
    def __init__(self, *, transport: httpx.BaseTransport | None = None, allow_private: bool | None = None,
                 timeout: float | None = None, retries: int | None = None, delay: float | None = None):
        self.validator = URLSafetyValidator(settings.allow_private_source_urls if allow_private is None else allow_private)
        self.timeout = timeout if timeout is not None else settings.spider_timeout
        self.retries = retries if retries is not None else settings.spider_max_retries
        self.delay = delay if delay is not None else settings.spider_request_delay
        self.last_request = 0.0
        self.client = httpx.Client(transport=transport, follow_redirects=False, timeout=self.timeout,
                                   headers={"User-Agent": settings.spider_user_agent, "Accept": "*/*"})

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def request(self, method: str, url: str, *, headers: dict[str, str] | None = None,
                max_bytes: int = 2_000_000, allowed_host: str | None = None,
                data: dict[str, str] | None = None) -> tuple[httpx.Response, str]:
        current = self.validator.validate(url)
        if allowed_host and (urlsplit(current).hostname or "").lower().removeprefix("www.") != allowed_host:
            raise SpiderError("INVALID_SOURCE", "URL left the configured website")
        request_headers = dict(headers or {})
        for redirect in range(6):
            response = self._attempt(method, current, headers=request_headers, max_bytes=max_bytes,
                                     data=data if redirect == 0 else None)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise SpiderError("PARSE_ERROR", "Redirect has no Location header")
                next_url = self.validator.validate(urljoin(current, location))
                if allowed_host and (urlsplit(next_url).hostname or "").lower().removeprefix("www.") != allowed_host:
                    raise SpiderError("INVALID_SOURCE", "Redirect left the configured website")
                if urlsplit(next_url).netloc != urlsplit(current).netloc:
                    request_headers.pop("Authorization", None)
                    request_headers.pop("Cookie", None)
                current = next_url
                continue
            if response.status_code in {401, 403}:
                if response.headers.get("x-ratelimit-remaining") == "0":
                    raise SpiderError("RATE_LIMITED", "GitHub API rate limit reached")
                raise SpiderError("HTTP_403", f"Source denied automated access ({response.status_code})")
            if response.status_code == 404:
                raise SpiderError("HTTP_404", "Source URL was not found")
            if response.status_code == 429:
                raise SpiderError("RATE_LIMITED", "Remote source rate limit reached")
            if response.status_code >= 400:
                raise SpiderError("NETWORK_ERROR", f"Remote source returned HTTP {response.status_code}")
            return response, current
        raise SpiderError("INVALID_SOURCE", "Too many redirects")

    def _attempt(self, method: str, url: str, *, headers: dict[str, str] | None, max_bytes: int,
                 data: dict[str, str] | None = None) -> httpx.Response:
        for attempt in range(self.retries + 1):
            remaining = self.delay - (time.monotonic() - self.last_request)
            if remaining > 0:
                time.sleep(remaining)
            self.last_request = time.monotonic()
            try:
                with self.client.stream(method, url, headers=headers, data=data) as response:
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < self.retries:
                        retry_after = response.headers.get("retry-after", "")
                        wait = min(float(retry_after), 10) if retry_after.isdigit() else min(2 ** attempt, 10)
                        time.sleep(wait)
                        continue
                    if method.upper() == "HEAD":
                        body = b""
                    else:
                        chunks: list[bytes] = []
                        size = 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > max_bytes:
                                raise SpiderError("PARSE_ERROR", "Metadata response exceeds size limit")
                            chunks.append(chunk)
                        body = b"".join(chunks)
                    clean_headers = dict(response.headers)
                    if method.upper() != "HEAD":
                        clean_headers.pop("content-encoding", None)
                        clean_headers.pop("content-length", None)
                    return httpx.Response(response.status_code, headers=clean_headers,
                                          content=body, request=response.request)
            except httpx.TimeoutException as exc:
                if attempt == self.retries:
                    raise SpiderError("TIMEOUT", "Source request timed out") from exc
            except httpx.RequestError as exc:
                if attempt == self.retries:
                    raise SpiderError("NETWORK_ERROR", "Source request failed") from exc
        raise SpiderError("NETWORK_ERROR", "Source request failed")

    def check_robots(self, url: str) -> None:
        parts = urlsplit(self.validator.validate(url))
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            response, _ = self.request("GET", robots_url, max_bytes=200_000)
        except SpiderError as exc:
            if exc.code == "HTTP_404":
                return
            if exc.code == "HTTP_403":
                raise SpiderError("MANUAL_REQUIRED", "robots.txt denied automated access") from exc
            raise
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        if not parser.can_fetch(settings.spider_user_agent, url):
            raise SpiderError("MANUAL_REQUIRED", "robots.txt disallows this source URL")


def content_disposition_filename(header: str | None) -> str | None:
    if not header:
        return None
    from urllib.parse import unquote
    message = Message()
    message["content-disposition"] = header
    filename = message.get_filename()
    if not filename:
        return None
    return unquote(filename).split("/")[-1].split("\\")[-1]
