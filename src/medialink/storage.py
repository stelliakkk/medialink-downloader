"""Store preferences beside the executable, with a per-user fallback on read-only drives."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

from . import APP_ID
from .platforms.bilibili import WEB_COOKIES

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]


class DataBlob(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]


def _protect(payload: bytes, *, decrypt: bool = False) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(payload)
    source = DataBlob(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    result = DataBlob()
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [
        ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
    ]
    operation.restype = wintypes.BOOL
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.length)
    finally:
        kernel32.LocalFree(result.data)


def atomic_write(path: Path, payload: bytes) -> None:
    with NamedTemporaryFile(dir=path.parent, delete=False) as file:
        pending = Path(file.name)
        try:
            file.write(payload)
            file.close()
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)


class Storage:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or ROOT / "data"
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=self.directory):
                pass
        except OSError:
            if directory is not None:
                raise
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
            self.directory = base / APP_ID
            self.directory.mkdir(parents=True, exist_ok=True)
        self.settings = self.directory / "settings.json"
        self.credential = self.directory / "bilibili-session.dat"

    def load_cookies(self) -> dict[str, str]:
        try:
            data = json.loads(_protect(self.credential.read_bytes(), decrypt=True))
            return {k: v for k, v in data.items() if k in WEB_COOKIES and isinstance(v, str)}
        except (OSError, ValueError, AttributeError):
            return {}

    def save_cookies(self, cookies: dict[str, str]) -> None:
        scoped = {k: v for k, v in cookies.items() if k in WEB_COOKIES}
        atomic_write(self.credential, _protect(json.dumps(scoped).encode()))

    def clear_cookies(self) -> None:
        self.credential.unlink(missing_ok=True)

    def download_folder(self) -> Path:
        try:
            settings = json.loads(self.settings.read_text(encoding="utf-8"))
            path = Path(settings["folder"])
            if path.is_absolute():
                return path
        except (OSError, ValueError, TypeError, KeyError):
            pass
        return Path.home() / "Downloads" / APP_ID

    def save_folder(self, folder: Path) -> None:
        atomic_write(self.settings, json.dumps({"folder": str(folder)}, ensure_ascii=False).encode())
