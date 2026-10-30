from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DeviceRecord:
    category: str
    name: str
    status: str
    instance_id: str
    battery_percent: int | None = None


class DeviceDiscoveryError(RuntimeError):
    pass


_POWERSHELL_SCRIPT = """
$classes = @('AudioEndpoint', 'Keyboard', 'Mouse')
$devices = Get-PnpDevice -PresentOnly |
    Where-Object { $_.Class -in $classes } |
    Select-Object Status, Class, FriendlyName, InstanceId
$battery = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue |
    Select-Object Name, Status, EstimatedChargeRemaining, EstimatedRunTime
[PSCustomObject]@{
    Devices = @($devices)
    Batteries = @($battery)
} | ConvertTo-Json -Compress
"""


def _category_for_class(device_class: str) -> str:
    return {
        "AudioEndpoint": "耳机/音频",
        "Keyboard": "键盘",
        "Mouse": "鼠标",
    }.get(device_class, device_class)


def _records_from_json(payload: Any) -> list[DeviceRecord]:
    if not isinstance(payload, dict) or not isinstance(payload.get("Devices"), list):
        raise DeviceDiscoveryError("Windows returned an unexpected device list.")

    records: list[DeviceRecord] = []
    for item in payload["Devices"]:
        if not isinstance(item, dict):
            continue
        device_class = str(item.get("Class") or "")
        name = str(item.get("FriendlyName") or "未命名设备")
        status = str(item.get("Status") or "Unknown")
        instance_id = str(item.get("InstanceId") or "")
        if device_class and instance_id:
            records.append(
                DeviceRecord(
                    category=_category_for_class(device_class),
                    name=name,
                    status=status,
                    instance_id=instance_id,
                )
            )
    return records


def _battery_from_json(payload: Any) -> int | None:
    batteries = payload.get("Batteries") if isinstance(payload, dict) else None
    if not isinstance(batteries, list):
        return None
    levels = [
        item.get("EstimatedChargeRemaining")
        for item in batteries
        if isinstance(item, dict)
        and isinstance(item.get("EstimatedChargeRemaining"), int)
        and 0 <= item["EstimatedChargeRemaining"] <= 100
    ]
    return min(levels) if levels else None


def discover_devices() -> list[DeviceRecord]:
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _POWERSHELL_SCRIPT,
            ],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeviceDiscoveryError(f"Unable to query Windows devices: {exc}") from exc

    if completed.returncode != 0:
        message = completed.stderr.strip() or "PowerShell device query failed."
        raise DeviceDiscoveryError(message)

    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise DeviceDiscoveryError("Windows returned invalid device data.") from exc
    devices = _records_from_json(payload)
    battery_percent = _battery_from_json(payload)
    if battery_percent is not None:
        devices.append(
            DeviceRecord(
                category="本机电池",
                name="Windows ACPI 电池",
                status="OK",
                instance_id="system-battery",
                battery_percent=battery_percent,
            )
        )
    return devices
