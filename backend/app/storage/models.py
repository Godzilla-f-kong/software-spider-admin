from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class UploadRequest:
    artifact_id: int
    local_path: Path
    remote_path: str
    access_token: str = ""
    progress: Callable[[int, int], None] | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class UploadResult:
    remote_path: str
    remote_file_id: str
    size: int


@dataclass(frozen=True)
class ShareResult:
    share_id: str
    url: str
    code: str | None = None
