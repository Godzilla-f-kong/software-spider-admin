from pathlib import Path

from app.core.config import settings


class StagingManager:
    def __init__(self, root: Path | None = None):
        self.root = root or settings.data_path

    def part(self, artifact_id: int) -> Path:
        return self.root / "staging" / "jobs" / str(artifact_id) / "artifact.part"

    def complete(self, artifact_id: int) -> Path:
        return self.root / "staging" / "jobs" / str(artifact_id) / "artifact.downloaded"
