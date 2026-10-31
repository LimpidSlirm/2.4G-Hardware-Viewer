from __future__ import annotations

import ctypes
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183


def acquire_single_instance(name: str = "2.4G-Hardware-Viewer") -> bool:
    """Return False when another instance already owns the named mutex.

    Autostart plus a manual launch would otherwise leave two overlays on screen
    and two resident HID listeners competing for the same handles.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        # Could not create the mutex; do not block startup on this alone.
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    # Keep the handle alive for the process lifetime so the mutex stays owned.
    globals()["_INSTANCE_MUTEX"] = handle
    return True
