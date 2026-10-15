import html
import ipaddress
import re
import socket
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from app.spider.errors import SpiderError


class URLNormalizer:
    @staticmethod
    def normalize(url: str, base: str | None = None, *, keep_fragment: bool = False) -> str:
        value = html.unescape(url.strip())
        if base:
            value = urljoin(base, value)
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise SpiderError("INVALID_SOURCE", "Only HTTP and HTTPS URLs are allowed")
        if parts.username or parts.password:
            raise SpiderError("INVALID_SOURCE", "URLs with embedded credentials are not allowed")
        return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path or "/", parts.query,
                           parts.fragment if keep_fragment else ""))


class URLSafetyValidator:
    def __init__(self, allow_private: bool = False):
        self.allow_private = allow_private
        self._checked_hosts: set[str] = set()

    def validate(self, url: str) -> str:
        normalized = URLNormalizer.normalize(url)
        host = urlsplit(normalized).hostname or ""
        if not self.allow_private:
            if host in self._checked_hosts:
                return normalized
            if host.lower() in {"localhost", "localhost.localdomain"} or host.lower().endswith(".localhost"):
                raise SpiderError("INVALID_SOURCE", "Localhost sources are disabled")
            try:
                addresses = {entry[4][0] for entry in socket.getaddrinfo(host, None)}
            except socket.gaierror as exc:
                raise SpiderError("NETWORK_ERROR", "Source host could not be resolved") from exc
            if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
                raise SpiderError("INVALID_SOURCE", "Private or non-public source addresses are disabled")
            self._checked_hosts.add(host)
        return normalized


class VersionParser:
    VERSION = re.compile(r"(?<![\w])(?:release[-_ ]|version[-_ ]|v)?(\d{1,4}(?:[._-]\d{1,4}){1,4}(?:[-_.]?(?:rc|beta|alpha)\d*)?)(?!\d)", re.I)

    @classmethod
    def parse(cls, raw: str | None) -> tuple[str | None, str | None]:
        if not raw or not raw.strip():
            return None, None
        raw = raw.strip()
        match = cls.VERSION.search(raw)
        if match:
            return raw, match.group(1).replace("_", ".")
        return raw, raw if len(raw) <= 100 else None


def filename_from_url(url: str) -> str:
    from pathlib import PurePosixPath
    return unquote(PurePosixPath(urlsplit(url).path).name)
