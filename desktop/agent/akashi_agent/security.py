import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict


class PathPolicy:
    def __init__(self, roots: tuple[Path, ...]) -> None:
        self.roots = tuple(root.resolve() for root in roots)

    def resolve(self, raw_path: str, must_exist: bool = True) -> Path:
        if not raw_path or "\x00" in raw_path:
            raise ValueError("A valid path is required.")
        candidate = Path(raw_path).expanduser().resolve(strict=False)
        def check(path):
            if not any(path == root or root in path.parents for root in self.roots):
                raise PermissionError("Path is outside the configured AKASHI roots.")
            if any(part.casefold() in {".git", ".ssh", ".aws", ".azure", ".gnupg", "node_modules", ".venv"}
                   or part.casefold().startswith(".env") for part in path.parts):
                raise PermissionError("Credential and internal directories are excluded.")
            if path.suffix.casefold() in {".pem", ".key", ".pfx", ".p12", ".credential", ".secure"}:
                raise PermissionError("Credential files are excluded.")
        # Check authority before existence, so an excluded path cannot act as a
        # file-existence oracle. Recheck after strict symlink/junction resolution.
        check(candidate)
        if must_exist:
            candidate = candidate.resolve(strict=True)
            check(candidate)
        return candidate


if sys.platform == "win32":
    class _DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> Any:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect_data(data: bytes) -> bytes:
    """Protect data for the current Windows user with DPAPI."""
    if sys.platform != "win32":
        raise RuntimeError("This credential store requires Windows DPAPI.")
    source, source_buffer = _blob(data)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "AKASHI device credential",
        None,
        None,
        None,
        0x01,
        ctypes.byref(output),
    ):
        raise OSError("Windows DPAPI could not protect the credential.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def unprotect_data(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("This credential store requires Windows DPAPI.")
    source, source_buffer = _blob(data)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(output)
    ):
        raise OSError("Windows DPAPI could not read the credential.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


class CredentialStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, credential: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(credential, separators=(",", ":")).encode("utf-8")
        self.path.write_bytes(protect_data(encoded))
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def load(self) -> Dict[str, Any]:
        if not self.path.is_file():
            raise FileNotFoundError("This agent has not been paired with AKASHI Core.")
        value = json.loads(unprotect_data(self.path.read_bytes()).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Invalid device credential document.")
        return value

    def remove(self) -> None:
        self.path.unlink(missing_ok=True)
