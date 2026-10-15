import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from app.core.enums import AdapterType, PackageType
from app.db.base import BEIJING
from app.spider.classifier import ArtifactClassifier
from app.spider.errors import SpiderError
from app.spider.http import SpiderHttpClient, content_disposition_filename
from app.spider.link_extractor import DownloadLinkExtractor
from app.spider.normalizers import URLNormalizer, VersionParser, filename_from_url
from app.spider.result import ArtifactCandidate, DiscoveryResult, ReleaseCandidate


@dataclass(frozen=True)
class SourceInput:
    id: int
    software_id: int
    source_url: str


class BaseSourceAdapter(ABC):
    def __init__(self, http: SpiderHttpClient):
        self.http = http
        self.classifier = ArtifactClassifier()

    @abstractmethod
    def discover(self, source: SourceInput) -> DiscoveryResult: ...

    def artifact(self, url: str, filename: str, *, size: int | None = None,
                 anchor_text: str = "", content_type: str = "", original_url: str | None = None,
                 resolved_url: str | None = None) -> ArtifactCandidate:
        kind = self.classifier.classify(filename, url, anchor_text, content_type)
        return ArtifactCandidate(filename=filename[:512], download_url=url, original_url=original_url,
                                 resolved_url=resolved_url, file_size=size, content_type=content_type or None,
                                 os=kind.os, architecture=kind.architecture, package_type=kind.package_type)


class GithubReleaseAdapter(BaseSourceAdapter):
    @staticmethod
    def repository(url: str) -> tuple[str, str]:
        parts = urlsplit(URLNormalizer.normalize(url))
        segments = [segment for segment in parts.path.split("/") if segment]
        if parts.hostname not in {"github.com", "www.github.com"} or len(segments) < 2:
            raise SpiderError("INVALID_SOURCE", "Expected a GitHub repository URL")
        if len(segments) > 2 and segments[2] != "releases":
            raise SpiderError("INVALID_SOURCE", "Expected repository or releases URL")
        return segments[0], segments[1]

    def discover(self, source: SourceInput) -> DiscoveryResult:
        from app.core.config import settings
        owner, repo = self.repository(source.source_url)
        headers = {"Accept": "application/vnd.github+json"}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        response, _ = self.http.request("GET", f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=20", headers=headers)
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise SpiderError("PARSE_ERROR", "GitHub releases response is not JSON") from exc
        if not isinstance(payload, list):
            raise SpiderError("PARSE_ERROR", "GitHub releases response has unexpected structure")
        result = DiscoveryResult(source_id=source.id, software_id=source.software_id,
                                 source_metadata={"repository": f"{owner}/{repo}", "adapter": "GITHUB_RELEASE"})
        for entry in payload:
            if entry.get("draft"):
                continue
            raw, version = VersionParser.parse(entry.get("tag_name") or entry.get("name"))
            if not version:
                result.warnings.append("Release without a usable tag or name was skipped")
                continue
            published = entry.get("published_at")
            try:
                release_date = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(BEIJING).date() if published else None
            except ValueError:
                release_date = None
            release = ReleaseCandidate(version=version, raw_version=raw, release_date=release_date,
                                       release_notes=entry.get("body"), is_prerelease=bool(entry.get("prerelease")),
                                       source_release_url=entry.get("html_url"))
            for asset in entry.get("assets") or []:
                url = asset.get("browser_download_url")
                filename = asset.get("name")
                if url and filename:
                    release.artifacts.append(self.artifact(url, filename, size=asset.get("size"),
                                                           content_type=asset.get("content_type") or ""))
            result.releases.append(release)
        if not result.releases:
            result.warnings.append("No published releases found")
        return result


class GenericHtmlAdapter(BaseSourceAdapter):
    def discover(self, source: SourceInput) -> DiscoveryResult:
        self.http.check_robots(source.source_url)
        response, resolved = self.http.request("GET", source.source_url)
        return self.discover_document(source, response, resolved)

    def discover_document(self, source: SourceInput, response, resolved: str) -> DiscoveryResult:
        """Parse HTML already fetched by a policy-checked pool crawl."""
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower() and not response.text.lstrip().startswith(("<!", "<html")):
            raise SpiderError("PARSE_ERROR", "Source is not an HTML page")
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        result = DiscoveryResult(source_id=source.id, software_id=source.software_id,
                                 software_metadata={"page_title": title},
                                 source_metadata={"resolved_url": resolved, "adapter": "GENERIC_HTML"})
        releases: dict[str, ReleaseCandidate] = {}
        links, _section_urls = DownloadLinkExtractor(self.http.validator).extract(soup, resolved)
        _, page_version = VersionParser.parse(title)
        if page_version == title:
            page_version = None
        if links:
            releases[page_version or "__unknown__"] = ReleaseCandidate(
                version=page_version, raw_version=page_version, source_release_url=resolved, links=links)
        link_urls = {URLNormalizer.normalize(link.link_url) for link in links}
        seen: set[str] = set()
        for anchor in soup.select("a[href]")[:500]:
            try:
                url = URLNormalizer.normalize(str(anchor.get("href")), resolved)
            except SpiderError:
                continue
            if url in seen:
                continue
            seen.add(url)
            if url in link_urls:
                continue
            text = anchor.get_text(" ", strip=True)
            filename = filename_from_url(url)
            classification = self.classifier.classify(filename, url, text)
            if classification.package_type is PackageType.OTHER and url not in _section_urls and text.strip().lower() != "download":
                continue
            if classification.package_type is PackageType.OTHER and url in _section_urls:
                text = "download"
            if classification.package_type is PackageType.OTHER and not re.search(r"\bdownload\b|下载", text, re.I):
                continue
            try:
                self.http.validator.validate(url)
            except SpiderError:
                result.warnings.append("An unsafe download link was skipped")
                continue
            size = None
            asset_type = ""
            original_url = url
            resolved_url = None
            if classification.package_type is PackageType.OTHER:
                try:
                    head, final_url = self.http.request("HEAD", url)
                    filename = content_disposition_filename(head.headers.get("content-disposition")) or filename
                    size = int(head.headers["content-length"]) if head.headers.get("content-length", "").isdigit() else None
                    asset_type = head.headers.get("content-type", "")
                    resolved_url = final_url if final_url != url else None
                    classification = self.classifier.classify(filename, url, text, asset_type)
                except SpiderError as exc:
                    if not links:
                        result.warnings.append(f"Could not inspect link metadata: {exc.code}")
                    continue
            if classification.package_type is PackageType.OTHER:
                continue
            raw, version = VersionParser.parse(filename)
            if version == filename:
                _, version = VersionParser.parse(text)
                if version == text:
                    _, version = VersionParser.parse(title)
                    if version == title:
                        version = None
            key = version or "__unknown__"
            release = releases.setdefault(key, ReleaseCandidate(version=version, raw_version=raw if version else None,
                                                                 source_release_url=resolved))
            release.artifacts.append(self.artifact(url, filename, size=size, anchor_text=text,
                                                   content_type=asset_type, original_url=original_url,
                                                   resolved_url=resolved_url))
        result.releases = list(releases.values())
        if "__unknown__" in releases and result.artifact_count:
            result.warnings.append("Some files have no reliable version; add a version before importing")
        if result.link_count and not result.artifact_count:
            result.warnings.append("Download entry links found; installer file details require review")
        if not result.artifact_count and not result.link_count:
            result.warnings.append("No downloadable installer links found")
        return result


class StaticUrlAdapter(BaseSourceAdapter):
    def discover(self, source: SourceInput) -> DiscoveryResult:
        self.http.check_robots(source.source_url)
        response, resolved = self.http.request("HEAD", source.source_url)
        filename = content_disposition_filename(response.headers.get("content-disposition")) or filename_from_url(resolved)
        if not filename:
            raise SpiderError("PARSE_ERROR", "Could not determine filename from URL or headers")
        raw, version = VersionParser.parse(filename)
        if version == filename:
            version = None
        size = int(response.headers["content-length"]) if response.headers.get("content-length", "").isdigit() else None
        artifact = self.artifact(source.source_url, filename, size=size,
                                 content_type=response.headers.get("content-type", ""),
                                 original_url=source.source_url, resolved_url=resolved)
        result = DiscoveryResult(source_id=source.id, software_id=source.software_id,
                                 releases=[ReleaseCandidate(version=version, raw_version=raw if version else None,
                                                            artifacts=[artifact])],
                                 source_metadata={"resolved_url": resolved, "adapter": "STATIC_URL"})
        if not version:
            result.warnings.append("File has no reliable version; add a version before importing")
        return result


class JsonApiAdapter(BaseSourceAdapter):
    def discover(self, source: SourceInput) -> DiscoveryResult:
        self.http.check_robots(source.source_url)
        response, resolved = self.http.request("GET", source.source_url)
        try:
            payload = response.json()
        except ValueError as exc:
            raise SpiderError("PARSE_ERROR", "Source is not JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("releases"), list):
            raise SpiderError("PARSE_ERROR", "Expected JSON object with releases array")
        result = DiscoveryResult(source_id=source.id, software_id=source.software_id,
                                 source_metadata={"resolved_url": resolved, "adapter": "JSON_API"})
        for item in payload["releases"]:
            if not isinstance(item, dict): continue
            raw, version = VersionParser.parse(str(item.get("version") or item.get("tag") or ""))
            release = ReleaseCandidate(version=version, raw_version=raw)
            for asset in item.get("assets") or []:
                if not isinstance(asset, dict) or not asset.get("url"): continue
                url = URLNormalizer.normalize(str(asset["url"]), resolved)
                self.http.validator.validate(url)
                release.artifacts.append(self.artifact(url, str(asset.get("filename") or filename_from_url(url)),
                                                       size=asset.get("size")))
            result.releases.append(release)
        return result


class ManualAdapter(BaseSourceAdapter):
    def discover(self, source: SourceInput) -> DiscoveryResult:
        raise SpiderError("MANUAL_REQUIRED", "This source requires manual review")


class BrowserAdapter(ManualAdapter):
    pass


class SourceAdapterFactory:
    REGISTRY: dict[AdapterType, type[BaseSourceAdapter]] = {
        AdapterType.GITHUB_RELEASE: GithubReleaseAdapter,
        AdapterType.GENERIC_HTML: GenericHtmlAdapter,
        AdapterType.STATIC_URL: StaticUrlAdapter,
        AdapterType.JSON_API: JsonApiAdapter,
        AdapterType.BROWSER: BrowserAdapter,
        AdapterType.MANUAL: ManualAdapter,
    }

    @classmethod
    def create(cls, adapter_type: AdapterType, http: SpiderHttpClient) -> BaseSourceAdapter:
        return cls.REGISTRY[adapter_type](http)
