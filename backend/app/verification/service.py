import hashlib
import struct
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.core.enums import Architecture, PackageType, SignatureStatus, VerificationStatus
from app.spider.normalizers import VersionParser
from app.verification.signature import SignatureVerifier


@dataclass
class VerificationResult:
    status: VerificationStatus
    detected_file_type: str
    detected_architecture: str | None = None
    detected_version: str | None = None
    signature_status: SignatureStatus = SignatureStatus.UNKNOWN
    checks: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    sha256: str = ""
    md5: str = ""
    file_size: int = 0

    def as_dict(self) -> dict:
        return {**self.__dict__, "status": self.status.value, "signature_status": self.signature_status.value}


def hashes(path: Path) -> tuple[str, str, int]:
    sha = hashlib.sha256()
    md5 = hashlib.md5()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest(), size


def detect_file_type(path: Path) -> str:
    with path.open("rb") as stream:
        head = stream.read(512)
    lowered = head.lstrip().lower()
    if lowered.startswith((b"<!doctype html", b"<html", b"<?xml")):
        return "HTML"
    if head[:2] == b"MZ":
        return "PE"
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        return "ZIP"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "SEVEN_Z"
    if head.startswith(b"\x1f\x8b"):
        return "GZIP"
    if head.startswith(b"\xfd7zXZ\x00"):
        return "XZ"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "MSI_OLE"
    if head.startswith(b"!<arch>\n"):
        return "DEB_AR"
    if head.startswith(b"\xed\xab\xee\xdb"):
        return "RPM"
    if head.startswith(b"\x7fELF"):
        return "ELF"
    if head.startswith(b"xar!"):
        return "XAR"
    if len(head) > 262 and head[257:262] == b"ustar":
        return "TAR"
    return "UNKNOWN"


def pe_architecture(path: Path) -> Architecture | None:
    try:
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                return None
            stream.seek(0x3c)
            offset = struct.unpack("<I", stream.read(4))[0]
            if offset > path.stat().st_size - 6:
                return None
            stream.seek(offset)
            if stream.read(4) != b"PE\0\0":
                return None
            machine = struct.unpack("<H", stream.read(2))[0]
        return {0x14c: Architecture.X86, 0x8664: Architecture.X64,
                0x1c0: Architecture.ARM, 0xaa64: Architecture.ARM64}.get(machine)
    except (OSError, ValueError, struct.error):
        return None


def pe_metadata(path: Path) -> dict[str, str]:
    try:
        import pefile
        image = pefile.PE(str(path), fast_load=True)
        image.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        values: dict[str, str] = {}
        for entry in getattr(image, "FileInfo", []):
            for table in entry if isinstance(entry, list) else [entry]:
                for string_table in getattr(table, "StringTable", []):
                    for key, value in string_table.entries.items():
                        values[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
        image.close()
        return {key: values[key] for key in ("CompanyName", "ProductName", "FileDescription", "FileVersion", "ProductVersion", "OriginalFilename") if key in values}
    except (ImportError, OSError, ValueError, AttributeError, KeyError):
        return {}


class VerificationService:
    TYPE_MAP = {
        PackageType.EXE: {"PE"}, PackageType.MSI: {"MSI_OLE"},
        PackageType.ZIP: {"ZIP"}, PackageType.SEVEN_Z: {"SEVEN_Z"},
        PackageType.TAR_GZ: {"GZIP"}, PackageType.TAR_XZ: {"XZ"},
        PackageType.DEB: {"DEB_AR"}, PackageType.RPM: {"RPM"},
        PackageType.APPIMAGE: {"ELF"}, PackageType.DMG: {"DMG"},
        PackageType.PKG: {"XAR"},
    }

    def verify(self, path: Path, *, package_type: PackageType, expected_architecture: Architecture,
               expected_version: str, filename: str, content_type: str | None = None,
               expected_sha256: str | None = None) -> VerificationResult:
        sha, md5, size = hashes(path)
        kind = detect_file_type(path)
        result = VerificationResult(VerificationStatus.VERIFIED, kind, sha256=sha, md5=md5, file_size=size)
        def check(name: str, status: str, message: str) -> None:
            result.checks.append({"name": name, "status": status, "message": message})
            if status == "FAIL":
                result.errors.append(message)
                result.status = VerificationStatus.REJECTED
            elif status == "WARNING" and result.status is VerificationStatus.VERIFIED:
                result.warnings.append(message)
                result.status = VerificationStatus.MANUAL_REVIEW
        if not size:
            check("FILE_SIZE", "FAIL", "Downloaded file is empty")
            return result
        check("FILE_SIZE", "PASS", f"{size} bytes")
        if kind == "HTML" or (content_type or "").lower().startswith("text/html"):
            check("FILE_TYPE", "FAIL", "HTML_INSTEAD_OF_ARTIFACT")
            return result
        if expected_sha256 and expected_sha256.lower() != sha:
            check("SHA256", "FAIL", "SHA256 mismatch with expected checksum")
        elif expected_sha256:
            check("SHA256", "PASS", "Expected SHA256 matched")
        expected = self.TYPE_MAP.get(package_type)
        if expected and kind not in expected:
            check("FILE_TYPE", "WARNING" if kind == "UNKNOWN" else "FAIL", f"Expected {package_type.value}; detected {kind}")
        else:
            check("FILE_TYPE", "PASS" if kind != "UNKNOWN" else "WARNING", f"Detected {kind}")
        if kind == "ZIP":
            try:
                with zipfile.ZipFile(path) as archive:
                    infos = archive.infolist()
                    expanded = sum(item.file_size for item in infos)
                    if len(infos) > 20000 or expanded > 8 * 1024**3 or expanded > max(size, 1) * 200:
                        check("ARCHIVE", "WARNING", "Archive expansion limits exceeded; manual inspection required")
                    elif archive.testzip() is not None:
                        check("ARCHIVE", "FAIL", "ARCHIVE_CORRUPTED: ZIP CRC failure")
                    else:
                        check("ARCHIVE", "PASS", f"ZIP entries: {len(infos)}")
            except (zipfile.BadZipFile, OSError, RuntimeError):
                check("ARCHIVE", "FAIL", "ARCHIVE_CORRUPTED: invalid ZIP")
        elif kind in {"GZIP", "XZ", "TAR"} and package_type in {PackageType.TAR_GZ, PackageType.TAR_XZ}:
            try:
                with tarfile.open(path, mode="r:*") as archive:
                    count = 0
                    expanded = 0
                    for member in archive:
                        count += 1
                        expanded += member.size
                        if count > 20000 or expanded > 8 * 1024**3 or expanded > size * 200:
                            check("ARCHIVE", "WARNING", "TAR expansion limits exceeded")
                            break
                    else:
                        check("ARCHIVE", "PASS", f"TAR entries: {count}")
            except (tarfile.TarError, OSError, EOFError):
                check("ARCHIVE", "FAIL", "ARCHIVE_CORRUPTED: invalid TAR")
        elif kind == "SEVEN_Z":
            check("ARCHIVE", "WARNING", "7Z structure recognized; deep integrity check unavailable")
        if kind == "PE":
            result.metadata = pe_metadata(path)
            result.signature_status = SignatureVerifier().verify(path)
            detected = pe_architecture(path)
            result.detected_architecture = detected.value if detected else None
            if detected and expected_architecture not in {Architecture.UNKNOWN, Architecture.OTHER, Architecture.UNIVERSAL}:
                check("ARCHITECTURE", "PASS" if detected == expected_architecture else "FAIL",
                      f"PE machine {detected.value}; expected {expected_architecture.value}")
            else:
                check("ARCHITECTURE", "WARNING", "PE machine could not be confirmed")
        else:
            check("ARCHITECTURE", "WARNING", "Package architecture not confirmed from file metadata")
        pe_version = result.metadata.get("ProductVersion") or result.metadata.get("FileVersion")
        _, detected_version = VersionParser.parse(pe_version or filename)
        result.detected_version = detected_version
        if detected_version:
            _, normalized_expected = VersionParser.parse(expected_version)
            def trim_zero(value: str) -> str:
                return ".".join(part for part in value.split(".")[:-1] if part) if value.endswith(".0") else value
            left = trim_zero(detected_version)
            right = trim_zero(normalized_expected or expected_version)
            check("VERSION", "PASS" if pe_version and left == right else "WARNING",
                  f"{'PE metadata' if pe_version else 'Filename'} version {detected_version}; release {expected_version}")
        else:
            check("VERSION", "WARNING", "Version could not be confirmed")
        if kind == "PE":
            check("SIGNATURE", "WARNING" if result.signature_status is SignatureStatus.INVALID else "PASS",
                  f"Authenticode: {result.signature_status.value}")
        else:
            check("SIGNATURE", "PASS", "Not applicable")
        return result
