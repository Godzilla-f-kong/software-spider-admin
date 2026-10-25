"""Targeted same-site search with a resumable priority queue."""
import heapq
import gzip
import io
import re
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.enums import Architecture, CandidateStatus, OperatingSystem
from app.models import CrawlPool, SoftwareCandidate
from app.spider.adapters import GenericHtmlAdapter, SourceInput
from app.spider.ai_page import AIPageRecognizer, OpenAIPageRecognizer
from app.spider.errors import SpiderError
from app.spider.external_search import ExternalSearchProvider, GoogleProgrammableSearch
from app.spider.http import SpiderHttpClient
from app.spider.normalizers import URLNormalizer, VersionParser
from app.spider.pool_search import PageSignal, named, same_site
from app.spider.site_adapters import PoolSiteAdapterRegistry, site_adapters


@dataclass(frozen=True)
class CandidateTarget:
    id: int
    name: str
    normalized_name: str
    status: CandidateStatus
    target_version: str | None = None
    target_os: OperatingSystem | None = None
    target_architecture: Architecture | None = None

    @classmethod
    def from_model(cls, item: SoftwareCandidate) -> "CandidateTarget":
        return cls(item.id, item.name, item.normalized_name, item.status,
                   item.target_version, item.target_os, item.target_architecture)


class PoolCrawler:
    SKIP_PATH = re.compile(r"\.(?:png|jpe?g|gif|svg|ico|css|js|pdf|mp4|webp|woff2?|exe|msi|zip|7z|dmg|deb|rpm)(?:$|[?#])", re.I)
    MAX_FRONTIER = 2500

    def __init__(self, http: SpiderHttpClient | None = None, external: ExternalSearchProvider | None = None,
                 registry: PoolSiteAdapterRegistry | None = None, ai: AIPageRecognizer | None = None):
        self.http, self.external = http, external
        self.registry = registry or site_adapters
        self.ai = ai

    def _robots(self, http: SpiderHttpClient, root: str) -> tuple[RobotFileParser, list[str]]:
        parser = RobotFileParser()
        parts = urlsplit(root)
        try:
            response, _ = http.request("GET", f"{parts.scheme}://{parts.netloc}/robots.txt",
                                       max_bytes=200_000, allowed_host=(parts.hostname or "").lower().removeprefix("www."))
            lines = response.text.splitlines()
            parser.parse(lines)
            sitemaps = [line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("sitemap:")]
        except SpiderError as exc:
            if exc.code == "HTTP_404":
                parser.parse([])
                sitemaps = []
            elif exc.code == "HTTP_403":
                raise SpiderError("MANUAL_REQUIRED", "robots.txt denied automated access") from exc
            else:
                raise
        if not parser.can_fetch(settings.spider_user_agent, root):
            raise SpiderError("MANUAL_REQUIRED", "robots.txt disallows the pool URL")
        return parser, sitemaps

    def _sitemap(self, http: SpiderHttpClient, root: str, host: str, sitemaps: list[str],
                 robots: RobotFileParser) -> list[str]:
        documents = sitemaps or [URLNormalizer.normalize("/sitemap.xml", root)]
        seen: set[str] = set()
        output: list[str] = []
        while documents and len(seen) < 5 and len(output) < 3000:
            try:
                url = URLNormalizer.normalize(documents.pop(0), root)
                if url in seen or not same_site(url, host) or not robots.can_fetch(settings.spider_user_agent, url):
                    continue
                seen.add(url)
                response, resolved = http.request("GET", url, max_bytes=1_000_000, allowed_host=host)
                if not same_site(resolved, host):
                    continue
                content = response.content
                if resolved.lower().endswith(".gz"):
                    with gzip.GzipFile(fileobj=io.BytesIO(content)) as stream:
                        content = stream.read(3_000_001)
                    if len(content) > 3_000_000:
                        continue
                if not content.lstrip().startswith(b"<"):
                    continue
                doc = ElementTree.fromstring(content)
                kind = doc.tag.rsplit("}", 1)[-1]
                if kind not in {"urlset", "sitemapindex"}:
                    continue
                for element in doc.iter():
                    if element.tag.rsplit("}", 1)[-1] != "loc" or not element.text:
                        continue
                    found = URLNormalizer.normalize(element.text.strip(), resolved)
                    if not same_site(found, host):
                        continue
                    if kind == "sitemapindex" and len(documents) < 5:
                        documents.append(found)
                    elif kind == "urlset" and len(output) < 3000:
                        output.append(found)
            except (SpiderError, ElementTree.ParseError, ValueError, OSError):
                continue
        return output

    def scan(self, pool: CrawlPool, candidates: list[CandidateTarget], progress=None,
             checkpoint: dict | None = None, should_pause=None, stop_on_match: bool = False) -> dict:
        root = URLNormalizer.normalize(pool.base_url)
        host = (urlsplit(root).hostname or "").lower().removeprefix("www.")
        adapter = self.registry.for_host(host)
        own_client = self.http is None
        http = self.http or SpiderHttpClient()
        external = self.external or (GoogleProgrammableSearch() if settings.google_cse_api_key and settings.google_cse_cx else None)
        ai = self.ai or (OpenAIPageRecognizer() if settings.ai_page_recognition_enabled
                         and settings.openai_api_key and settings.ai_page_model else None)
        try:
            robots, sitemaps = self._robots(http, root)
            warnings = list((checkpoint or {}).get("warnings", []))
            matches = list((checkpoint or {}).get("matches", []))
            visited = set((checkpoint or {}).get("visited", []))
            queue = [tuple(item) for item in (checkpoint or {}).get("frontier", [])] or [(0, 0, 0, root, "HOME")]
            heapq.heapify(queue)
            queued = {item[3] for item in queue} | visited
            counter = max((int(item[1]) for item in queue), default=0)
            roles = dict((checkpoint or {}).get("page_roles", {}))
            strategies = dict((checkpoint or {}).get("strategies", {}))
            found_targets = {int(item["candidate_id"]) for item in matches if item.get("match_status") == "MATCHED"}
            session_visits = stale = 0

            def add(url: str, priority: int, depth: int, strategy: str) -> None:
                nonlocal counter
                try:
                    url = URLNormalizer.normalize(url, root)
                except SpiderError:
                    return
                if (not same_site(url, host) or url in queued or self.SKIP_PATH.search(urlsplit(url).path)
                        or len(queue) >= self.MAX_FRONTIER or depth > pool.max_depth):
                    return
                counter += 1
                queued.add(url)
                heapq.heappush(queue, (-priority, counter, depth, url, strategy))

            def snapshot(reason: str) -> dict:
                state = {"frontier": [list(item) for item in queue], "visited": sorted(visited),
                         "matches": matches, "warnings": warnings[-30:], "page_roles": roles,
                         "strategies": strategies}
                return {"pool_url": root, "visited_pages": len(visited), "queued_pages": len(queued),
                        "matches": matches, "warnings": warnings[-30:], "page_roles": roles,
                        "strategies": strategies, "stop_reason": reason,
                        "limit_reached": reason == "BUDGET", "checkpoint": state if queue else None}

            if not checkpoint:
                for url in self._sitemap(http, root, host, sitemaps, robots):
                    score = adapter.priority(url, "", candidates, "SITEMAP")
                    if score >= 20:
                        add(url, score + 15, 1, "SITEMAP")
                for path in (pool.category_paths or "").splitlines()[:30]:
                    add(path.strip(), 25, 1, "CATEGORY")
                if external:
                    for target in candidates[:20]:
                        try:
                            for url in external.discover(host, target.name):
                                add(url, 105, 1, "EXTERNAL")
                        except SpiderError as exc:
                            warnings.append(f"External search unavailable: {exc.code}")
                            break

            while queue and session_visits < pool.max_pages:
                if should_pause and should_pause():
                    return snapshot("PAUSED")
                _, _, depth, url, strategy = heapq.heappop(queue)
                if url in visited:
                    continue
                visited.add(url)
                if not robots.can_fetch(settings.spider_user_agent, url):
                    continue
                session_visits += 1
                strategies[strategy] = strategies.get(strategy, 0) + 1
                before = len(matches)
                try:
                    response, resolved = http.request("GET", url, allowed_host=host)
                    if not same_site(resolved, host):
                        warnings.append("Cross-site redirect skipped")
                        continue
                    if "html" not in response.headers.get("content-type", "").lower():
                        continue
                    soup = BeautifulSoup(response.content, "html.parser")
                    signal = adapter.classify(soup, resolved, root)
                    if (signal.role == "OTHER" and ai and strategies.get("AI_ASSIST", 0) < 5
                            and any(named(signal.title, target.name) or named(signal.heading, target.name)
                                    for target in candidates)):
                        strategies["AI_ASSIST"] = strategies.get("AI_ASSIST", 0) + 1
                        suggested = ai.classify(signal)
                        if suggested in {"DETAIL", "DOWNLOAD"}:
                            signal = PageSignal(suggested, signal.title, signal.heading, signal.text)
                        elif suggested is None and not any("AI page recognition unavailable" in note for note in warnings):
                            warnings.append("AI page recognition unavailable; using rule-based classification")
                    roles[signal.role] = roles.get(signal.role, 0) + 1
                    if signal.role == "HOME":
                        for search_url in adapter.search(soup, resolved, host, candidates, pool.search_path_template):
                            add(search_url, 120, 1, "SITE_SEARCH")
                    if signal.role in {"DETAIL", "DOWNLOAD"}:
                        for target in candidates:
                            if target.id in found_targets or not (named(signal.title, target.name) or named(signal.heading, target.name)):
                                continue
                            try:
                                found = GenericHtmlAdapter(http).discover_document(
                                    SourceInput(0, target.id, resolved), response, resolved)
                                wanted = VersionParser.parse(target.target_version)[1] if target.target_version else None
                                releases = [release for release in found.releases if not wanted or VersionParser.parse(release.version)[1] == wanted]
                                artifacts = [item for release in releases for item in release.artifacts
                                             if (not target.target_os or item.os == target.target_os)
                                             and (not target.target_architecture or item.architecture == target.target_architecture)]
                                all_artifacts = [item for release in found.releases for item in release.artifacts]
                                status = "MATCHED" if (artifacts or (not target.target_os and not target.target_architecture and not target.target_version and found.link_count)) else "REVIEW_REQUIRED"
                                matches.append({"candidate_id": target.id, "candidate_name": target.name,
                                    "candidate_status": target.status.value, "page_url": resolved,
                                    "page_title": signal.title, "page_role": signal.role,
                                    "relevance_score": 100 if status == "MATCHED" else 60,
                                    "match_status": status, "target_version": target.target_version,
                                    "target_os": target.target_os.value if target.target_os else None,
                                    "target_architecture": target.target_architecture.value if target.target_architecture else None,
                                    "versions": [release.version for release in found.releases if release.version][:10],
                                    "artifact_count": found.artifact_count, "link_count": found.link_count,
                                    "artifacts": [{"filename": item.filename, "url": item.download_url,
                                                   "os": item.os.value, "architecture": item.architecture.value,
                                                   "package_type": item.package_type.value,
                                                   "target_match": item in artifacts} for item in all_artifacts],
                                    "links": [{"url": link.link_url, "provider": link.provider.value,
                                               "link_type": link.link_type.value, "label": link.label,
                                               "access_code": link.access_code} for release in found.releases
                                              for link in release.links],
                                    "warnings": found.warnings[:5]})
                                if status == "MATCHED":
                                    found_targets.add(target.id)
                            except SpiderError as exc:
                                warnings.append(f"Matched page could not be inspected: {exc.code}")
                    if depth < pool.max_depth:
                        for anchor in soup.select("a[href]")[:800]:
                            label = anchor.get_text(" ", strip=True)
                            try:
                                target_url = URLNormalizer.normalize(str(anchor.get("href")), resolved)
                            except SpiderError:
                                continue
                            score = adapter.priority(target_url, label, candidates, signal.role)
                            if score or depth == 0:
                                navigation = bool(re.search(r"(?:[?&]page=\d+|/page/\d+|下一页|next|category|/tag/|分类)",
                                                            target_url + " " + label, re.I))
                                add(target_url, score, depth if navigation and depth >= 1 else depth + 1,
                                    "PAGINATION" if navigation else "LINK")
                except SpiderError as exc:
                    if url == root:
                        raise
                    warnings.append(f"Page skipped ({exc.code}): {url[:160]}")
                stale = 0 if len(matches) > before else stale + 1
                if progress:
                    progress(snapshot("RUNNING"))
                if (all(target.target_version for target in candidates)
                        and found_targets == {target.id for target in candidates}):
                    return snapshot("TARGETS_FOUND")
                if stop_on_match and any(item.get("match_status") == "MATCHED" for item in matches[before:]):
                    return snapshot("MATCH_FOUND")
                if stale >= max(20, min(50, pool.max_pages)):
                    return snapshot("NO_PROGRESS")
            return snapshot("BUDGET" if queue else "FRONTIER_EMPTY")
        finally:
            if own_client:
                http.close()
            if self.external is None and external and hasattr(external, "close"):
                external.close()
            if self.ai is None and ai and hasattr(ai, "close"):
                ai.close()
