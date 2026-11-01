from __future__ import annotations

import os
import subprocess
import sys
import winreg
from pathlib import Path

from .winproc import NO_WINDOW

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


SHORTCUT_NAME = "2.4G Hardware Viewer.lnk"


def desktop_shortcut_path() -> Path:
    desktop = Path.home() / "Desktop"
    if not desktop.is_dir():
        desktop = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
    return desktop / SHORTCUT_NAME


def create_desktop_shortcut() -> Path:
    """Create a .lnk on the desktop that starts the app without a console."""
    target = desktop_shortcut_path()
    icon_source = _pythonw_path()
    script = f"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut('{target}')
$lnk.TargetPath = '{_pythonw_path()}'
$lnk.Arguments = '"{_launcher_path()}"'
$lnk.WorkingDirectory = '{_launcher_path().parent}'
$lnk.IconLocation = '{icon_source},0'
$lnk.Description = '2.4G Hardware Viewer'
$lnk.Save()
"""
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        creationflags=NO_WINDOW,
    )
    if completed.returncode != 0 or not target.exists():
        raise RuntimeError(completed.stderr.strip() or "快捷方式创建失败")
    return target


def remove_desktop_shortcut() -> bool:
    target = desktop_shortcut_path()
    if target.exists():
        target.unlink()
        return True
    return False
