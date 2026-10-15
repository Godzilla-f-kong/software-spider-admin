"""Optional, documented search API discovery. No search-engine HTML scraping."""
import logging
from typing import Protocol

import httpx

from app.core.config import settings
from app.spider.errors import SpiderError
from app.spider.normalizers import URLNormalizer
from app.spider.pool_search import same_site

# This API requires a key in the query. Suppress transport URL logging.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class ExternalSearchProvider(Protocol):
    def discover(self, host: str, query: str) -> list[str]: ...


class GoogleProgrammableSearch:
    API = "https://customsearch.googleapis.com/customsearch/v1"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=10)
        self.owns_client = client is None

    def discover(self, host: str, query: str) -> list[str]:
        if not settings.google_cse_api_key or not settings.google_cse_cx:
            return []
        try:
            response = self.client.get(self.API, params={"key": settings.google_cse_api_key,
                "cx": settings.google_cse_cx, "q": query, "siteSearch": host,
                "siteSearchFilter": "i", "num": 10})
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SpiderError("EXTERNAL_SEARCH_ERROR", "Configured external search API failed") from exc
        urls = []
        for item in data.get("items", []) if isinstance(data, dict) else []:
            try:
                url = URLNormalizer.normalize(item.get("link", ""))
                if same_site(url, host):
                    urls.append(url)
            except (AttributeError, SpiderError):
                continue
        return urls

    def close(self) -> None:
        if self.owns_client:
            self.client.close()
