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

    @property
    def transport(self) -> str:
        instance_id = self.instance_id.upper()
        if instance_id.startswith("USB\\"):
            return "USB"
        if instance_id.startswith("HID\\"):
            return "HID"
        if instance_id.startswith("BTH"):
            return "蓝牙"
        if instance_id.startswith("SWD\\"):
            return "Windows 音频端点"
        return "系统设备"

    @property
    def vid_pid(self) -> str | None:
        marker = self.instance_id.upper()
        vid_start = marker.find("VID_")
        pid_start = marker.find("PID_")
        if vid_start < 0 or pid_start < 0:
            return None
        vid = marker[vid_start + 4 : vid_start + 8]
        pid = marker[pid_start + 4 : pid_start + 8]
        if len(vid) == 4 and len(pid) == 4:
            return f"{vid}:{pid}"
        return None


class DeviceDiscoveryError(RuntimeError):
    pass


_POWERSHELL_SCRIPT = """
$classes = @('AudioEndpoint', 'Keyboard', 'Mouse')
$devices = Get-PnpDevice -PresentOnly |
    Where-Object { $_.Class -in $classes } |
    Select-Object Status, Class, FriendlyName, InstanceId
[PSCustomObject]@{
    Devices = @($devices)
} | ConvertTo-Json -Compress
"""


def _category_for_class(device_class: str) -> str:
    return {
        "AudioEndpoint": "音频设备",
        "Keyboard": "键盘",
        "Mouse": "鼠标",
    }.get(device_class, device_class)


def _is_user_target_device(device_class: str, name: str, instance_id: str) -> bool:
    if device_class == "Keyboard":
        return not (
            instance_id.upper().startswith("ACPI\\")
            or "PS/2" in name
            or "标准键盘" in name
        )
    if device_class == "AudioEndpoint":
        return "麦克风阵列" not in name
    return True


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
        if (
            device_class
            and instance_id
            and _is_user_target_device(device_class, name, instance_id)
        ):
            records.append(
                DeviceRecord(
                    category=_category_for_class(device_class),
                    name=name,
                    status=status,
                    instance_id=instance_id,
                )
            )
    return records


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
    return devices
