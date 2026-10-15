from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


@dataclass(frozen=True)
class DownloadRequest:
    artifact_id: int
    url: str
    expected_filename: str
    part_path: Path
    expected_size: int | None = None


@dataclass(frozen=True)
class DownloadProgress:
    downloaded: int
    total: int | None
    speed: float


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    filename: str
    file_size: int
    content_type: str | None
    resolved_url: str
    elapsed_seconds: float
    http_status: int


class Downloader(Protocol):
    def download(self, request: DownloadRequest, progress: Callable[[DownloadProgress], None],
                 cancelled: Callable[[], bool]) -> DownloadResult: ...
