import json
import gzip
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.enums import AdapterType, Architecture, OperatingSystem, PackageType, SourceType
from app.db.base import Base
from app.models import DownloadLink, Software, SoftwareArtifact, SoftwareRelease, SoftwareSource, SoftwareVariant
from app.spider.adapters import (GenericHtmlAdapter, GithubReleaseAdapter, SourceInput,
                                 StaticUrlAdapter)
from app.spider.classifier import ArtifactClassifier
from app.spider.errors import SpiderError
from app.spider.http import SpiderHttpClient
from app.spider.normalizers import URLNormalizer, URLSafetyValidator, VersionParser
from app.spider.result import ArtifactCandidate, DiscoveryResult, ReleaseCandidate
from app.spider.service import DiscoveryPersistenceService

FIXTURES = Path(__file__).parent / "fixtures"


@compiles(BigInteger, "sqlite")
def compile_bigint_for_sqlite(_type, _compiler, **_kwargs):
    return "INTEGER"


@pytest.mark.parametrize(("raw", "expected"), [
    ("v1.2.3", "1.2.3"), ("release-1.2.3", "1.2.3"),
    ("version_1.2.3", "1.2.3"), ("2026.10", "2026.10"),
    ("24.09", "24.09"), ("nightly-main", "nightly-main")])
def test_version_parser(raw, expected):
    assert VersionParser.parse(raw)[1] == expected


@pytest.mark.parametrize(("filename", "os", "arch", "package"), [
    ("tool-win-x64.exe", OperatingSystem.WINDOWS, Architecture.X64, PackageType.EXE),
    ("tool-win-arm64.msi", OperatingSystem.WINDOWS, Architecture.ARM64, PackageType.MSI),
    ("tool-linux-x64.tar.gz", OperatingSystem.LINUX, Architecture.X64, PackageType.TAR_GZ),
    ("tool-macos-arm64.dmg", OperatingSystem.MACOS, Architecture.ARM64, PackageType.DMG),
    ("tool-win32.7z", OperatingSystem.WINDOWS, Architecture.UNKNOWN, PackageType.SEVEN_Z),
    ("tool-linux-aarch64.tar.xz", OperatingSystem.LINUX, Architecture.ARM64, PackageType.TAR_XZ),
    ("tool-win-x86.zip", OperatingSystem.WINDOWS, Architecture.X86, PackageType.ZIP),
])
def test_classifier(filename, os, arch, package):
    result = ArtifactClassifier().classify(filename)
    assert (result.os, result.architecture, result.package_type) == (os, arch, package)


def test_url_normalizer_preserves_query_and_blocks_unsafe():
    assert URLNormalizer.normalize("/download?id=456&amp;file=123#part", "https://example.com/path") == "https://example.com/download?id=456&file=123"
    with pytest.raises(SpiderError): URLNormalizer.normalize("file:///etc/passwd")
    with pytest.raises(SpiderError): URLSafetyValidator().validate("http://127.0.0.1/private")


def mock_client(handler):
    return SpiderHttpClient(transport=httpx.MockTransport(handler), allow_private=True, retries=0, delay=0)


def test_github_release_adapter():
    payload = json.loads((FIXTURES / "github_release.json").read_text(encoding="utf-8"))
    def handler(request):
        assert request.url.path == "/repos/acme/tool/releases"
        return httpx.Response(200, json=payload)
    with mock_client(handler) as http:
        result = GithubReleaseAdapter(http).discover(SourceInput(4, 9, "https://github.com/acme/tool/releases/latest"))
    assert GithubReleaseAdapter.repository("https://github.com/acme/tool") == ("acme", "tool")
    assert result.releases[0].version == "1.2.3"
    assert len(result.releases[0].variants) == 3
    assert [(x.os, x.architecture) for x in result.releases[0].artifacts] == [
        (OperatingSystem.WINDOWS, Architecture.X64), (OperatingSystem.LINUX, Architecture.X64),
        (OperatingSystem.MACOS, Architecture.ARM64)]


def test_generic_html_adapter():
    html = (FIXTURES / "generic_download_page.html").read_text(encoding="utf-8")
    def handler(request):
        if request.url.path == "/robots.txt": return httpx.Response(404)
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})
    with mock_client(handler) as http:
        result = GenericHtmlAdapter(http).discover(SourceInput(1, 2, "https://example.com/downloads"))
    assert result.artifact_count == 4
    assert result.releases[0].version == "2.4.0"
    assert {x.package_type for x in result.releases[0].artifacts} == {
        PackageType.EXE, PackageType.MSI, PackageType.TAR_GZ, PackageType.SEVEN_Z}


def test_generic_html_extracts_cloud_links_without_requesting_shares():
    html = (FIXTURES / "generic_share_page.html").read_text(encoding="utf-8")
    def handler(request):
        assert request.url.host == "example.com"
        if request.url.path == "/robots.txt": return httpx.Response(404)
        assert request.method == "GET"
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})
    with mock_client(handler) as http:
        result = GenericHtmlAdapter(http).discover(SourceInput(1, 2, "https://example.com/ddu.html"))
    assert result.artifact_count == 0
    assert result.link_count == 3
    assert result.releases[0].version == "18.1.6.0"
    links = result.releases[0].links
    assert [link.provider.value for link in links] == ["QUARK", "XUNLEI", "OTHER"]
    assert [link.access_code for link in links] == [None, "8qu6", "3519"]
    assert links[1].link_url.endswith("?pwd=8qu6")


def test_generic_html_uses_head_for_extensionless_link():
    def handler(request):
        if request.url.path == "/robots.txt": return httpx.Response(404)
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-disposition": 'attachment; filename="tool-1.0-win-x64.msi"',
                                               "content-length": "512"})
        return httpx.Response(200, text='<html><a href="/download?id=123">Download</a></html>',
                              headers={"content-type": "text/html"})
    with mock_client(handler) as http:
        result = GenericHtmlAdapter(http).discover(SourceInput(1, 2, "https://example.com/page"))
    assert result.artifact_count == 1
    assert result.releases[0].artifacts[0].package_type is PackageType.MSI
    assert result.releases[0].artifacts[0].download_url.endswith("?id=123")


def test_rate_limited_github_api_is_typed_error():
    def handler(_request):
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0"})
    with mock_client(handler) as http:
        with pytest.raises(SpiderError) as error:
            GithubReleaseAdapter(http).discover(SourceInput(1, 2, "https://github.com/acme/tool"))
    assert error.value.code == "RATE_LIMITED"


def test_static_url_redirect_keeps_original():
    def handler(request):
        if request.url.path == "/robots.txt": return httpx.Response(404)
        if request.url.host == "example.com": return httpx.Response(302, headers={"location": "https://cdn.example.com/tool-1.2.3-x64.zip"})
        return httpx.Response(200, headers={"content-length": "123", "content-type": "application/zip"})
    with mock_client(handler) as http:
        result = StaticUrlAdapter(http).discover(SourceInput(1, 2, "https://example.com/download?id=3"))
    artifact = result.releases[0].artifacts[0]
    assert artifact.original_url == artifact.download_url == "https://example.com/download?id=3"
    assert artifact.resolved_url == "https://cdn.example.com/tool-1.2.3-x64.zip"
    assert artifact.file_size == 123


def test_http_client_decodes_compressed_metadata_once():
    def handler(_request):
        return httpx.Response(200, content=gzip.compress(b'{"ok": true}'),
                              headers={"content-encoding": "gzip", "content-type": "application/json"})
    with mock_client(handler) as http:
        response, _ = http.request("GET", "https://example.com/metadata")
    assert response.json() == {"ok": True}


def test_redirect_drops_authorization_for_new_host():
    def handler(request):
        if request.url.host == "example.com":
            assert request.headers.get("authorization") == "Bearer secret"
            return httpx.Response(302, headers={"location": "https://cdn.example.com/file"})
        assert "authorization" not in request.headers
        return httpx.Response(200, text="ok")
    with mock_client(handler) as http:
        response, _ = http.request("GET", "https://example.com/start", headers={"Authorization": "Bearer secret"})
    assert response.text == "ok"


def test_persistence_is_idempotent():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        software = Software(name="Tool", slug="tool")
        db.add(software)
        db.flush()
        source = SoftwareSource(software_id=software.id, source_type=SourceType.GITHUB,
                                source_url="https://github.com/acme/tool", adapter_type=AdapterType.GITHUB_RELEASE)
        db.add(source)
        db.commit()
        result = DiscoveryResult(source_id=source.id, software_id=software.id,
            releases=[ReleaseCandidate(version="1.2.3", artifacts=[
                ArtifactCandidate(filename="tool-win-x64.zip", download_url="https://example.com/file.zip",
                                  os=OperatingSystem.WINDOWS, architecture=Architecture.X64,
                                  package_type=PackageType.ZIP)])])
        service = DiscoveryPersistenceService()
        assert service.annotate(db, result).releases[0].status == "NEW"
        result = DiscoveryResult.model_validate(result.model_dump(mode="json"))
        assert service.import_result(db, result) == {"releases": 1, "variants": 1, "artifacts": 1, "links": 0, "skipped_unknown_version": 0}
        assert service.annotate(db, result).releases[0].artifacts[0].status == "EXISTING"
        assert service.import_result(db, result)["artifacts"] == 0
        assert db.scalar(select(func.count()).select_from(SoftwareRelease)) == 1
        assert db.scalar(select(func.count()).select_from(SoftwareVariant)) == 1
        artifact = db.scalar(select(SoftwareArtifact))
        assert artifact.download_status.value == "NOT_DOWNLOADED"


def test_share_link_import_is_idempotent_without_known_version():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        software = Software(name="Tool", slug="tool-share")
        db.add(software)
        db.flush()
        source = SoftwareSource(software_id=software.id, source_type=SourceType.OTHER,
                                source_url="https://example.com/page", adapter_type=AdapterType.GENERIC_HTML)
        db.add(source)
        db.commit()
        html = (FIXTURES / "generic_share_page.html").read_text(encoding="utf-8").replace("DDU v18.1.6.0", "DDU")
        def handler(request):
            if request.url.path == "/robots.txt": return httpx.Response(404)
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        with mock_client(handler) as http:
            result = GenericHtmlAdapter(http).discover(SourceInput(source.id, software.id, source.source_url))
        result.source_metadata["source_url"] = source.source_url
        service = DiscoveryPersistenceService()
        assert service.annotate(db, result).releases[0].links[0].status == "NEW"
        result = DiscoveryResult.model_validate(result.model_dump(mode="json"))
        assert service.import_result(db, result)["links"] == 3
        assert service.annotate(db, result).releases[0].links[0].status == "EXISTING"
        assert service.import_result(db, result)["links"] == 0
        assert db.scalar(select(func.count()).select_from(DownloadLink)) == 3
        assert db.scalar(select(func.count()).select_from(SoftwareRelease)) == 0
        assert all(link.release_id is None for link in db.scalars(select(DownloadLink)).all())
