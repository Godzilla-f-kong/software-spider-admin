from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.models import GeneratedContent, SoftwareArtifact
from app.spider.adapters import SourceInput
from app.spider.result import DiscoveryResult


@dataclass(frozen=True)
class DownloadTask:
    artifact_id: int
    source_url: str
    destination: Path


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    bytes_written: int


class Downloader(Protocol):
    def download(self, task: DownloadTask) -> DownloadResult: ...


class SourceAdapter(Protocol):
    def discover(self, source: SourceInput) -> DiscoveryResult: ...


class ArtifactVerifier(Protocol):
    def verify(self, artifact: SoftwareArtifact, path: Path) -> bool: ...


class StorageProvider(Protocol):
    def upload(self, artifact: SoftwareArtifact, path: Path) -> str: ...


class AIContentGenerator(Protocol):
    def generate(self, content: GeneratedContent) -> str: ...


class CommercePublisher(Protocol):
    def publish(self, listing_id: int) -> str: ...
