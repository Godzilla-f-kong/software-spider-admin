from datetime import date
from pydantic import BaseModel, Field, computed_field

from app.core.enums import (Architecture, CpuFamily, DownloadLinkProvider, DownloadLinkType, InstallType,
                            OperatingSystem, PackageType)


class ArtifactCandidate(BaseModel):
    filename: str
    download_url: str
    original_url: str | None = None
    resolved_url: str | None = None
    file_size: int | None = None
    content_type: str | None = None
    package_type: PackageType = PackageType.OTHER
    os: OperatingSystem = OperatingSystem.UNKNOWN
    architecture: Architecture = Architecture.UNKNOWN
    cpu_family: CpuFamily = CpuFamily.UNKNOWN
    install_type: InstallType = InstallType.UNKNOWN
    edition: str | None = None
    language: str | None = None
    status: str = "UNKNOWN"


class DownloadLinkCandidate(BaseModel):
    link_url: str
    source_page_url: str
    provider: DownloadLinkProvider = DownloadLinkProvider.OTHER
    link_type: DownloadLinkType = DownloadLinkType.DOWNLOAD_PAGE
    access_code: str | None = None
    label: str | None = None
    context_text: str | None = None
    status: str = "UNKNOWN"


class VariantCandidate(BaseModel):
    os: OperatingSystem
    architecture: Architecture
    cpu_family: CpuFamily = CpuFamily.UNKNOWN
    edition: str | None = None
    language: str | None = None
    artifacts: list[ArtifactCandidate] = Field(default_factory=list)


class ReleaseCandidate(BaseModel):
    version: str | None = None
    raw_version: str | None = None
    release_date: date | None = None
    release_notes: str | None = None
    is_prerelease: bool = False
    source_release_url: str | None = None
    artifacts: list[ArtifactCandidate] = Field(default_factory=list)
    links: list[DownloadLinkCandidate] = Field(default_factory=list)
    status: str = "UNKNOWN"

    @computed_field
    @property
    def variants(self) -> list[VariantCandidate]:
        grouped: dict[tuple[OperatingSystem, Architecture, CpuFamily, str | None, str | None], VariantCandidate] = {}
        for artifact in self.artifacts:
            key = (artifact.os, artifact.architecture, artifact.cpu_family, artifact.edition, artifact.language)
            if key not in grouped:
                grouped[key] = VariantCandidate(os=artifact.os, architecture=artifact.architecture,
                                                cpu_family=artifact.cpu_family,
                                                edition=artifact.edition, language=artifact.language)
            grouped[key].artifacts.append(artifact)
        return list(grouped.values())


class DiscoveryResult(BaseModel):
    source_id: int
    software_id: int
    software_metadata: dict[str, str] = Field(default_factory=dict)
    releases: list[ReleaseCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    source_metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def artifact_count(self) -> int:
        return sum(len(release.artifacts) for release in self.releases)

    @property
    def link_count(self) -> int:
        return sum(len(release.links) for release in self.releases)
