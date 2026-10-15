from pathlib import Path
import hashlib

from app.core.config import settings
from app.downloader.policy import safe_component, safe_filename


class ArchiveManager:
    def __init__(self, root: Path | None = None):
        self.root = root or settings.data_path

    def resolve_relative(self, value: str) -> Path:
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] != "archive":
            raise ValueError("Unsafe archive path")
        root = self.root.resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Archive path escapes data root")
        return target

    def archive_relative(self, software_slug: str, version: str, os: str, architecture: str,
                         filename: str) -> Path:
        return Path("archive") / safe_component(software_slug) / safe_component(version) / safe_component(os.lower()) / safe_component(architecture.lower()) / safe_filename(filename)

    def archive(self, source: Path, relative: Path) -> Path:
        target = self.resolve_relative(relative.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if self._sha256(source) == self._sha256(target):
                source.unlink()
                return target
            raise FileExistsError(f"Archive path already exists: {relative}")
        source.replace(target)
        return target

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def fail(self, source: Path, artifact_id: int) -> Path:
        target = self.root / "failed" / f"artifact-{artifact_id}-{self._sha256(source)[:12]}.rejected"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            source.unlink()
        else:
            source.replace(target)
        return target
