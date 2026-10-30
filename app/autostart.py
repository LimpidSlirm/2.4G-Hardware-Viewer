from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "2.4G-Hardware-Viewer"


def _launcher_path() -> Path:
    return Path(__file__).resolve().parent.parent / "launch.pyw"


def _pythonw_path() -> Path:
    executable = Path(sys.executable)
    candidate = executable.with_name("pythonw.exe")
    return candidate if candidate.exists() else executable


def autostart_command() -> str:
    return f'"{_pythonw_path()}" "{_launcher_path()}"'


def install_autostart() -> str:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, autostart_command())
    return autostart_command()


def remove_autostart() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return True


def autostart_command_if_set() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return None
    return str(value)
