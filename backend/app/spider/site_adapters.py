"""Site-specific search hooks; core persistence and safety remain shared."""
from typing import Protocol

from bs4 import BeautifulSoup

from app.spider.pool_search import PageSignal, classify_page, link_priority, search_urls


class PoolSiteAdapter(Protocol):
    def search(self, soup: BeautifulSoup, page_url: str, host: str, targets: list,
               template: str | None) -> list[str]: ...

    def classify(self, soup: BeautifulSoup, url: str, root: str) -> PageSignal: ...

    def priority(self, url: str, label: str, targets: list, role: str) -> int: ...


class GenericPoolSiteAdapter:
    def search(self, soup: BeautifulSoup, page_url: str, host: str, targets: list,
               template: str | None) -> list[str]:
        return search_urls(soup, page_url, host, targets, template)

    def classify(self, soup: BeautifulSoup, url: str, root: str) -> PageSignal:
        return classify_page(soup, url, root)

    def priority(self, url: str, label: str, targets: list, role: str) -> int:
        return link_priority(url, label, targets, role)


class PoolSiteAdapterRegistry:
    def __init__(self):
        self._adapters: dict[str, PoolSiteAdapter] = {}
        self._default = GenericPoolSiteAdapter()

    def register(self, host: str, adapter: PoolSiteAdapter) -> None:
        self._adapters[host.lower().removeprefix("www.")] = adapter

    def for_host(self, host: str) -> PoolSiteAdapter:
        return self._adapters.get(host.lower().removeprefix("www."), self._default)


site_adapters = PoolSiteAdapterRegistry()
