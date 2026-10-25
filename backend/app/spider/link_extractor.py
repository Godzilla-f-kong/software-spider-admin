"""Find cloud shares and download entries without opening their targets."""
import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup, Tag

from app.core.enums import DownloadLinkProvider, DownloadLinkType, PackageType
from app.spider.classifier import ArtifactClassifier
from app.spider.errors import SpiderError
from app.spider.normalizers import URLNormalizer, URLSafetyValidator
from app.spider.result import DownloadLinkCandidate


class DownloadLinkExtractor:
    SECTION = re.compile(r"\u4e0b\u8f7d(?:\u5730\u5740|\u94fe\u63a5|\u65b9\u5f0f)|download\s+(?:links?|mirrors?)", re.I)
    CODE = re.compile(r"(?:\u5982\u6709\u5bc6\u7801|\u63d0\u53d6\u7801|\u8bbf\u95ee\u7801|\u5bc6\u7801|password|passcode)\s*[:\uff1a]?\s*([A-Za-z0-9]{3,12})", re.I)
    EXACT_DOWNLOAD = re.compile(r"^(?:\u7acb\u5373)?\u4e0b\u8f7d(?:\u5730\u5740|\u94fe\u63a5)?$|^download$", re.I)

    def __init__(self, validator: URLSafetyValidator):
        self.validator = validator
        self.classifier = ArtifactClassifier()

    @staticmethod
    def provider(host: str) -> DownloadLinkProvider:
        host = host.lower()
        if host == "pan.quark.cn": return DownloadLinkProvider.QUARK
        if host == "pan.xunlei.com": return DownloadLinkProvider.XUNLEI
        if host == "pan.baidu.com": return DownloadLinkProvider.BAIDU
        if host == "123pan.com" or host.endswith(".123pan.com") or host == "123684.com" or host.endswith(".123684.com"):
            return DownloadLinkProvider.PAN123
        if host in {"www.alipan.com", "www.aliyundrive.com"}: return DownloadLinkProvider.ALIYUN
        if host.startswith("lanzou") or ".lanzou" in host: return DownloadLinkProvider.LANZOU
        return DownloadLinkProvider.OTHER

    @staticmethod
    def _context(anchor: Tag) -> tuple[str, bool]:
        parent = anchor.find_parent(["p", "li", "td", "div"])
        if parent is None:
            return anchor.get_text(" ", strip=True)[:500], True
        return parent.get_text(" ", strip=True)[:500], len(parent.find_all("a")) == 1

    @classmethod
    def _access_code(cls, url: str, context: str, unambiguous: bool) -> str | None:
        query = parse_qs(urlsplit(url).query)
        for key in ("pwd", "password", "passcode"):
            values = query.get(key)
            if values and re.fullmatch(r"[A-Za-z0-9]{3,12}", values[0]):
                return values[0]
        if unambiguous:
            match = cls.CODE.search(context)
            if match:
                return match.group(1)
        return None

    def extract(self, soup: BeautifulSoup, page_url: str) -> tuple[list[DownloadLinkCandidate], set[str]]:
        article_host = urlsplit(page_url).hostname or ""
        page_codes = set(self.CODE.findall(soup.get_text(" ", strip=True)))
        provider_share_count = sum(
            self.provider(urlsplit(str(anchor.get("href"))).hostname or "") is not DownloadLinkProvider.OTHER
            for anchor in soup.select("a[href]")[:500]
        )
        section_anchors: list[Tag] = []
        for heading in soup.select("h2, h3, h4, h5"):
            if not self.SECTION.search(heading.get_text(" ", strip=True)):
                continue
            for sibling in heading.next_siblings:
                if isinstance(sibling, Tag) and sibling.name in {"h2", "h3", "h4", "h5"}:
                    break
                if isinstance(sibling, Tag):
                    if sibling.name == "a": section_anchors.append(sibling)
                    section_anchors.extend(sibling.find_all("a", href=True))
        section_ids = {id(anchor) for anchor in section_anchors}
        section_urls: set[str] = set()
        candidates: list[DownloadLinkCandidate] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href]")[:500]:
            raw = anchor.get("href")
            if not raw:
                continue
            try:
                url = URLNormalizer.normalize(str(raw), page_url, keep_fragment=True)
                normalized = URLNormalizer.normalize(str(raw), page_url)
            except SpiderError:
                continue
            if len(url) > 2048:
                continue
            in_section = id(anchor) in section_ids
            if in_section: section_urls.add(normalized)
            host = urlsplit(url).hostname or ""
            provider = self.provider(host)
            if provider is DownloadLinkProvider.OTHER and not in_section:
                continue
            label = anchor.get_text(" ", strip=True)[:255]
            context, unambiguous = self._context(anchor)
            if provider is DownloadLinkProvider.OTHER:
                if host == article_host:
                    continue
                if not (label.startswith(("http://", "https://")) or self.EXACT_DOWNLOAD.fullmatch(label)
                        or re.search(r"\u7f51\u76d8|\u63d0\u53d6\u7801|\u8bbf\u95ee\u7801|\u5bc6\u7801|\u9ad8\u901f|\u76f4\u94fe", context)):
                    continue
            if url in seen:
                continue
            try:
                self.validator.validate(normalized)
            except SpiderError:
                continue
            seen.add(url)
            package = self.classifier.classify(label, normalized).package_type
            link_type = (DownloadLinkType.PAN_SHARE if provider is not DownloadLinkProvider.OTHER
                         else DownloadLinkType.DIRECT_FILE if package is not PackageType.OTHER
                         else DownloadLinkType.DOWNLOAD_PAGE)
            candidates.append(DownloadLinkCandidate(link_url=url, source_page_url=page_url,
                            provider=provider, link_type=link_type,
                            access_code=self._access_code(url, context, unambiguous)
                            or (next(iter(page_codes)) if provider is not DownloadLinkProvider.OTHER
                                and len(page_codes) == 1 and provider_share_count == 1
                                else None),
                            label=label or None, context_text=context or None))
        return candidates, section_urls
