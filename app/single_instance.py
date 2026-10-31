from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "2.4G-Hardware-Viewer"
REVEAL_FILE = Path(__file__).resolve().parent.parent / ".reveal_request"

_MUTEX_HANDLE: object = None


def acquire_single_instance(name: str = MUTEX_NAME) -> bool:
    """Return False when another instance already owns the named mutex."""
    global _MUTEX_HANDLE
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        # Without a mutex, prefer starting over refusing to run.
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    # Hold the handle for the process lifetime so the mutex stays owned.
    _MUTEX_HANDLE = handle
    return True


def request_reveal() -> None:
    """Ask the running instance to bring its window to the front."""
    try:
        REVEAL_FILE.write_text("1", encoding="utf-8")
    except OSError:
        pass


def take_reveal_request() -> bool:
    """Consume a pending reveal request, if any."""
    if not REVEAL_FILE.exists():
        return False
    try:
        REVEAL_FILE.unlink()
    except OSError:
        return False
    return True


def clear_reveal_request() -> None:
    try:
        REVEAL_FILE.unlink()
    except OSError:
        pass
