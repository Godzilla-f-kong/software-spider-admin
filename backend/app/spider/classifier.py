import re
from dataclasses import dataclass

from app.core.enums import Architecture, CpuFamily, InstallType, OperatingSystem, PackageType


@dataclass(frozen=True)
class ArtifactClassification:
    os: OperatingSystem
    architecture: Architecture
    package_type: PackageType
    cpu_family: CpuFamily
    install_type: InstallType
    language: str


class ArtifactClassifier:
    PACKAGES = (
        (".tar.gz", PackageType.TAR_GZ), (".tgz", PackageType.TAR_GZ),
        (".tar.xz", PackageType.TAR_XZ), (".txz", PackageType.TAR_XZ),
        (".appimage", PackageType.APPIMAGE), (".exe", PackageType.EXE),
        (".msi", PackageType.MSI), (".zip", PackageType.ZIP),
        (".7z", PackageType.SEVEN_Z), (".dmg", PackageType.DMG),
        (".pkg", PackageType.PKG), (".deb", PackageType.DEB), (".rpm", PackageType.RPM),
    )

    @staticmethod
    def _has(text: str, aliases: str) -> bool:
        return bool(re.search(r"(?<![a-z0-9])(?:" + aliases + r")(?![a-z0-9])", text, re.I))

    def classify(self, filename: str, url: str = "", anchor_text: str = "", content_type: str = "") -> ArtifactClassification:
        text = " ".join((filename, url.split("?", 1)[0], anchor_text)).lower()
        lower_name = filename.lower().split("?", 1)[0]
        package = next((kind for suffix, kind in self.PACKAGES if lower_name.endswith(suffix)), PackageType.OTHER)
        if package is PackageType.OTHER and anchor_text:
            package = next((kind for suffix, kind in self.PACKAGES
                            if re.search(re.escape(suffix) + r"(?:\b|$)", anchor_text.lower())), PackageType.OTHER)
        if package is PackageType.OTHER:
            if "application/zip" in content_type: package = PackageType.ZIP
            elif "x-msdownload" in content_type: package = PackageType.EXE
            elif "application/x-msi" in content_type: package = PackageType.MSI
        if self._has(text, r"android|apk"):
            os = OperatingSystem.ANDROID
        elif self._has(text, r"macos|osx|darwin|mac") or package in {PackageType.DMG, PackageType.PKG}:
            os = OperatingSystem.MACOS
        elif self._has(text, r"linux|ubuntu|debian") or package in {PackageType.DEB, PackageType.RPM, PackageType.APPIMAGE}:
            os = OperatingSystem.LINUX
        elif self._has(text, r"windows|win32|win64|win") or package in {PackageType.EXE, PackageType.MSI}:
            os = OperatingSystem.WINDOWS
        else:
            os = OperatingSystem.UNKNOWN
        if self._has(text, r"arm64|aarch64"):
            architecture = Architecture.ARM64
        elif self._has(text, r"armv7|armhf"):
            architecture = Architecture.ARM
        elif self._has(text, r"x64|amd64|x86_64") or (self._has(text, r"win64") and os is OperatingSystem.WINDOWS):
            architecture = Architecture.X64
        elif self._has(text, r"x86|i386|i686"):
            architecture = Architecture.X86
        elif self._has(text, r"universal|noarch|all"):
            architecture = Architecture.UNIVERSAL
        else:
            architecture = Architecture.UNKNOWN
        cpu_family = (CpuFamily.ARM if architecture in {Architecture.ARM, Architecture.ARM64}
                      else CpuFamily.AMD if architecture in {Architecture.X86, Architecture.X64}
                      else CpuFamily.UNKNOWN)
        portable = self._has(text, r"portable|noinstall|免安装") or package is PackageType.APPIMAGE
        archive_only = package in {PackageType.ZIP, PackageType.SEVEN_Z, PackageType.TAR_GZ, PackageType.TAR_XZ}
        install_type = (InstallType.PORTABLE if portable else InstallType.UNKNOWN if archive_only
                        else InstallType.INSTALLER if package is not PackageType.OTHER else InstallType.UNKNOWN)
        language = "ZH" if self._has(text, r"zh|zh-cn|chinese|简体中文|繁體中文") else "EN" if self._has(text, r"en|en-us|english") else "UNKNOWN"
        return ArtifactClassification(os, architecture, package, cpu_family, install_type, language)
