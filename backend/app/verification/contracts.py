from pathlib import Path
from typing import Protocol


class MalwareScanner(Protocol):
    def scan(self, path: Path) -> dict[str, str]: ...


class MsiMetadataExtractor(Protocol):
    def extract(self, path: Path) -> dict[str, str]: ...
