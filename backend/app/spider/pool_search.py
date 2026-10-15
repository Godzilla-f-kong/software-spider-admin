"""Reusable target scoring, page roles and search URL discovery for URL pools."""
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote_plus, urlencode, urlsplit

from bs4 import BeautifulSoup

from app.spider.normalizers import URLNormalizer


def norm(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def named(text: str, name: str) -> bool:
    needle, haystack = norm(name), norm(text)
    if len(needle) < 3:
        return False
    if needle.isascii() and needle.isalnum():
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", haystack))
    return needle in haystack


def same_site(url: str, host: str) -> bool:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.") == host


@dataclass(frozen=True)
class PageSignal:
    role: str
    title: str
    heading: str
    text: str


def classify_page(soup: BeautifulSoup, url: str, root: str) -> PageSignal:
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    heading = soup.h1.get_text(" ", strip=True) if soup.h1 else ""
    text = (soup.select_one("main, article, .entry-content, .post-content") or soup).get_text(" ", strip=True)[:10000]
    path = urlsplit(url).path.lower()
    has_download_link = bool(soup.select_one('a[href$=".exe"], a[href$=".msi"], a[href$=".zip"], a[href$=".7z"], a[href$=".dmg"]'))
    if url.rstrip("/") == root.rstrip("/"):
        role = "HOME"
    elif re.search(r"(?:search|/s/|[?&](?:s|q|keyword)=)", url, re.I) or (
            not heading and soup.select_one('form input[type="search"]') and len(soup.select('a[href]')) > 3):
        role = "SEARCH_RESULTS"
    elif re.search(r"(?:category|catalog|/tag/|/softwares?/?$|分类|目录)", path, re.I):
        role = "CATEGORY"
    elif re.search(r"(?:download|/dl/|下载)", path, re.I) and (heading or title):
        role = "DOWNLOAD"
    elif heading and (has_download_link or soup.select_one("article, main, .entry-content, .post-content") or len(text) >= 100
                      or re.search(r"(?:/post/|/article/|/detail/)", path, re.I)):
        role = "DETAIL"
    else:
        role = "OTHER"
    return PageSignal(role, title[:500], heading[:500], text)


def link_priority(url: str, label: str, targets: list, role: str) -> int:
    text = f"{urlsplit(url).path} {label}"
    score = max((100 if named(text, item.name) else 0 for item in targets), default=0)
    if re.search(r"(?:download|release|/post/|/soft/|下载)", text, re.I):
        score += 18
    if re.search(r"(?:category|catalog|software|/tag/|分类|软件)", text, re.I):
        score += 8
    if re.search(r"(?:next|下一页|page[=/]\d+|/page/\d+)", text, re.I):
        score += 7
    if role == "SEARCH_RESULTS":
        score += 12
    return score


def search_urls(soup: BeautifulSoup, page_url: str, host: str, targets: list,
                template: str | None = None) -> list[str]:
    """Use site GET search forms first; a per-site template overrides guessing."""
    urls: list[str] = []
    if template:
        if template.count("{query}") != 1 or len(template) > 1024:
            return []
        for target in targets:
            try:
                url = URLNormalizer.normalize(template.replace("{query}", quote_plus(target.name)), page_url)
                if same_site(url, host):
                    urls.append(url)
            except Exception:
                continue
        return urls
    for form in soup.select("form"):
        if str(form.get("method", "get")).lower() != "get":
            continue
        field = next((input_tag.get("name") for input_tag in form.select("input[name]")
                      if (input_tag.get("type") == "search" or
                          str(input_tag.get("name", "")).lower() in {"q", "s", "search", "keyword", "query"})), None)
        if not field:
            continue
        action = str(form.get("action") or page_url)
        try:
            endpoint = URLNormalizer.normalize(action, page_url)
        except Exception:
            continue
        if not same_site(endpoint, host):
            continue
        separator = "&" if urlsplit(endpoint).query else "?"
        urls.extend(endpoint + separator + urlencode({field: target.name}) for target in targets)
        break
    return urls
