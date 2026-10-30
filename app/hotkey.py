from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312


class GlobalHotkey(QAbstractNativeEventFilter):
    """System-wide hotkey through Win32 RegisterHotKey."""

    def __init__(
        self,
        hotkey_id: int,
        modifiers: int,
        virtual_key: int,
        callback: Callable[[], None],
    ) -> None:
        super().__init__()
        self._id = hotkey_id
        self._callback = callback
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL
        self.registered = bool(
            self._user32.RegisterHotKey(None, hotkey_id, modifiers, virtual_key)
        )

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt override)
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0
        if msg.message == WM_HOTKEY and msg.wParam == self._id:
            self._callback()
        return False, 0

    def unregister(self) -> None:
        if self.registered:
            self._user32.UnregisterHotKey(None, self._id)
            self.registered = False
