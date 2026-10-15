import os
import subprocess

from app.core.enums import SignatureStatus


class SignatureVerifier:
    """Windows Authenticode signal; unknown is intentionally non-fatal."""

    def verify(self, path) -> SignatureStatus:
        if os.name != "nt":
            return SignatureStatus.UNKNOWN
        escaped = str(path).replace("'", "''")
        command = f"(Get-AuthenticodeSignature -LiteralPath '{escaped}').Status.ToString()"
        try:
            process = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                                     capture_output=True, text=True, timeout=20, check=False)
            if process.returncode:
                return SignatureStatus.UNKNOWN
            return {"Valid": SignatureStatus.VALID, "NotSigned": SignatureStatus.UNSIGNED,
                    "HashMismatch": SignatureStatus.INVALID, "NotTrusted": SignatureStatus.INVALID}.get(
                        process.stdout.strip(), SignatureStatus.UNKNOWN)
        except (OSError, subprocess.TimeoutExpired):
            return SignatureStatus.UNKNOWN
