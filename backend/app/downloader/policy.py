import re
from pathlib import PurePath
from urllib.parse import urlsplit

from app.core.config import settings
from app.downloader.errors import DownloadError
from app.spider.errors import SpiderError
from app.spider.normalizers import URLSafetyValidator


def safe_component(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    if value.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{x}" for x in range(1, 10)), *(f"LPT{x}" for x in range(1, 10))}:
        value = "_" + value
    return value[:180] or "unnamed"


def safe_filename(value: str) -> str:
    return safe_component(value.replace("\\", "/").split("/")[-1])


class DownloadPolicy:
    def __init__(self, *, allow_private: bool | None = None, domains: str | None = None,
                 redirect_domains: str | None = None):
        self.validator = URLSafetyValidator(settings.allow_private_source_urls if allow_private is None else allow_private)
        self.domains = {x.strip().lower() for x in (settings.download_allowed_domains if domains is None else domains).split(",") if x.strip()}
        self.redirect_domains = {x.strip().lower() for x in (settings.download_allowed_redirect_domains if redirect_domains is None else redirect_domains).split(",") if x.strip()}

    def validate(self, url: str, *, redirect: bool = False) -> str:
        if urlsplit(url).scheme.lower() not in {"http", "https"}:
            raise DownloadError("UNSUPPORTED_PROTOCOL", "Only HTTP and HTTPS downloads are supported")
        try:
            clean = self.validator.validate(url)
        except SpiderError as exc:
            code = "DNS_ERROR" if exc.code == "NETWORK_ERROR" else ("REDIRECT_BLOCKED" if redirect else "URL_BLOCKED")
            raise DownloadError(code, exc.message) from exc
        host = (urlsplit(clean).hostname or "").lower()
        allowed = self.redirect_domains if redirect and self.redirect_domains else self.domains
        if allowed and not any(host == item or host.endswith("." + item) for item in allowed):
            raise DownloadError("REDIRECT_BLOCKED" if redirect else "URL_BLOCKED", "Domain is not allowed")
        return clean
