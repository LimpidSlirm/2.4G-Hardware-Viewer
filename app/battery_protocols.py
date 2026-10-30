from __future__ import annotations

import json
import threading
import time

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from pywinusb import hid

from .hid_inventory import enumerate_hid_interfaces, read_input_reports


@dataclass(frozen=True)
class BatteryReading:
    vendor_id: int
    product_id: int
    report_id: int
    values: tuple[int, ...]
    source: str


def read_vendor_battery_candidates() -> list[BatteryReading]:
    readings: list[BatteryReading] = []
    devices = hid.HidDeviceFilter(vendor_id=0x3554, product_id=0xFA09).get_devices()
    for device in devices:
        try:
            device.open()
            for report in device.find_feature_reports():
                if report.report_id != 6:
                    continue
                raw_values = tuple(int(value) for value in report.get())
                candidates = raw_values[3:6]
                if len(candidates) == 3 and all(0 <= value <= 100 for value in candidates):
                    readings.append(
                        BatteryReading(
                            vendor_id=device.vendor_id,
                            product_id=device.product_id,
                            report_id=report.report_id,
                            values=candidates,
                            source="厂商 Feature Report 候选（3554:FA09 / Report 6）",
                        )
                    )
        except (OSError, hid.HIDError):
            continue
        finally:
            device.close()
    return readings


RAPOO_REPORT_ID = 7
RAPOO_MIN_DPI = 100
RAPOO_MAX_DPI = 32000


@dataclass(frozen=True)
class RapooStatus:
    vendor_id: int
    product_id: int
    device_id: int
    dpi_index: int
    dpi_x: int
    dpi_y: int
    active_state: int
    battery_percent: int
    captured_clock: str = ""
    cached: bool = False


def parse_rapoo_status(raw: list[int]) -> RapooStatus | None:
    if len(raw) < 9 or raw[0] != RAPOO_REPORT_ID:
        return None
    dpi_x = raw[3] | (raw[4] << 8)
    dpi_y = raw[5] | (raw[6] << 8)
    # The DPI pair is the layout self-check: a wrong offset produces implausible
    # values, so the battery byte is only trusted when both axes decode sanely.
    if not RAPOO_MIN_DPI <= dpi_x <= RAPOO_MAX_DPI:
        return None
    if not RAPOO_MIN_DPI <= dpi_y <= RAPOO_MAX_DPI:
        return None
    if not 0 <= raw[8] <= 100:
        return None
    return RapooStatus(
        vendor_id=0,
        product_id=0,
        device_id=raw[1],
        dpi_index=raw[2],
        dpi_x=dpi_x,
        dpi_y=dpi_y,
        active_state=raw[7],
        battery_percent=raw[8],
    )


_MOUSE_CACHE: dict[tuple[int, int], tuple[RapooStatus, float]] = {}
_MOUSE_CACHE_LOCK = threading.Lock()
_MOUSE_LISTENER: "MouseBatteryListener | None" = None
_MOUSE_LISTENER_LOCK = threading.Lock()
_CACHE_FILE = Path(__file__).resolve().parent.parent / ".mouse_battery_cache.json"


def _load_cache_from_disk() -> None:
    """Restore the last reading so a restart does not blank the battery row."""
    try:
        payload = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for key, entry in payload.items():
        try:
            vendor_text, product_text = key.split(":")
            vendor_id = int(vendor_text, 16)
            product_id = int(product_text, 16)
            status = RapooStatus(
                vendor_id=vendor_id,
                product_id=product_id,
                device_id=int(entry["device_id"]),
                dpi_index=int(entry["dpi_index"]),
                dpi_x=int(entry["dpi_x"]),
                dpi_y=int(entry["dpi_y"]),
                active_state=int(entry["active_state"]),
                battery_percent=int(entry["battery_percent"]),
                captured_clock=str(entry.get("captured_clock", "")),
                cached=True,
            )
            age = max(0.0, time.time() - float(entry["saved_at"]))
        except (KeyError, TypeError, ValueError):
            continue
        with _MOUSE_CACHE_LOCK:
            _MOUSE_CACHE[(vendor_id, product_id)] = (status, time.monotonic() - age)


def _save_cache_to_disk(status: RapooStatus) -> None:
    key = f"{status.vendor_id:04X}:{status.product_id:04X}"
    payload: dict[str, dict[str, object]] = {}
    try:
        existing = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            payload = existing
    except (OSError, ValueError):
        payload = {}
    payload[key] = {
        "device_id": status.device_id,
        "dpi_index": status.dpi_index,
        "dpi_x": status.dpi_x,
        "dpi_y": status.dpi_y,
        "active_state": status.active_state,
        "battery_percent": status.battery_percent,
        "captured_clock": status.captured_clock,
        "saved_at": time.time(),
    }
    try:
        _CACHE_FILE.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


_load_cache_from_disk()


class MouseBatteryListener:
    """Keeps one HID handle open and records every Report 7 broadcast.

    The mouse only broadcasts on state changes, sometimes minutes apart, so a
    short polling window misses most reports. A resident listener captures them
    whenever they happen and never sends a report itself.
    """

    def __init__(self, vendor_id: int, product_id: int) -> None:
        self.vendor_id = vendor_id
        self.product_id = product_id
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._device = None
        self.connected = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="mouse-battery-listener", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            interface = self._find_interface()
            if interface is None:
                self.connected = False
                self._stop.wait(5)
                continue
            self.connected = True
            try:
                read_input_reports(interface, self._handle, self._stop)
            except Exception:
                pass
            finally:
                self.connected = False
            if not self._stop.is_set():
                self._stop.wait(3)

    def _find_interface(self):
        for interface in enumerate_hid_interfaces():
            if interface.vid_pid != f"{self.vendor_id:04X}:{self.product_id:04X}":
                continue
            if interface.usage_page != 0xFF00 or interface.usage != 0x0002:
                continue
            if interface.input_report_length <= 0:
                continue
            return interface
        return None

    def _handle(self, data: list[int]) -> None:
        status = parse_rapoo_status([int(value) for value in data])
        if status is None:
            return
        stamped = replace(
            status,
            vendor_id=self.vendor_id,
            product_id=self.product_id,
            captured_clock=datetime.now().strftime("%H:%M"),
            cached=False,
        )
        with _MOUSE_CACHE_LOCK:
            _MOUSE_CACHE[(self.vendor_id, self.product_id)] = (
                stamped,
                time.monotonic(),
            )
        _save_cache_to_disk(stamped)


def start_mouse_listener(
    vendor_id: int = 0x24AE, product_id: int = 0x1411
) -> MouseBatteryListener:
    global _MOUSE_LISTENER
    with _MOUSE_LISTENER_LOCK:
        if _MOUSE_LISTENER is None:
            _MOUSE_LISTENER = MouseBatteryListener(vendor_id, product_id)
            _MOUSE_LISTENER.start()
        return _MOUSE_LISTENER


def stop_mouse_listener() -> None:
    global _MOUSE_LISTENER
    with _MOUSE_LISTENER_LOCK:
        if _MOUSE_LISTENER is not None:
            _MOUSE_LISTENER.stop()
            _MOUSE_LISTENER = None


def read_mouse_battery(
    vendor_id: int = 0x24AE,
    product_id: int = 0x1411,
    timeout_seconds: float = 8.0,
    max_cache_age_seconds: float = 86400.0,
) -> RapooStatus | None:
    """Return the latest Report 7 reading, listening briefly if needed.

    The resident listener normally already holds the value; the short listen is
    only a fallback for the first call before any broadcast has arrived.
    """
    with _MOUSE_CACHE_LOCK:
        entry = _MOUSE_CACHE.get((vendor_id, product_id))
    if entry is not None:
        status, stored_at = entry
        if time.monotonic() - stored_at <= max_cache_age_seconds:
            return replace(status, cached=True)

    fresh = _listen_mouse_report(vendor_id, product_id, timeout_seconds)
    if fresh is not None:
        stamped = replace(
            fresh, captured_clock=datetime.now().strftime("%H:%M"), cached=False
        )
        with _MOUSE_CACHE_LOCK:
            _MOUSE_CACHE[(vendor_id, product_id)] = (stamped, time.monotonic())
        return stamped

    with _MOUSE_CACHE_LOCK:
        entry = _MOUSE_CACHE.get((vendor_id, product_id))
    if entry is None:
        return None
    status, stored_at = entry
    if time.monotonic() - stored_at > max_cache_age_seconds:
        return None
    return replace(status, cached=True)


def _listen_mouse_report(
    vendor_id: int,
    product_id: int,
    timeout_seconds: float,
) -> RapooStatus | None:
    for device in hid.HidDeviceFilter(
        vendor_id=vendor_id, product_id=product_id
    ).get_devices():
        try:
            device.open()
            if not any(
                report.report_id == RAPOO_REPORT_ID
                for report in device.find_input_reports()
            ):
                continue

            received = threading.Event()
            statuses: list[RapooStatus] = []

            def handle_report(data: list[int]) -> None:
                status = parse_rapoo_status([int(value) for value in data])
                if status is None:
                    return
                statuses.append(
                    RapooStatus(
                        vendor_id=device.vendor_id,
                        product_id=device.product_id,
                        device_id=status.device_id,
                        dpi_index=status.dpi_index,
                        dpi_x=status.dpi_x,
                        dpi_y=status.dpi_y,
                        active_state=status.active_state,
                        battery_percent=status.battery_percent,
                    )
                )
                received.set()

            device.set_raw_data_handler(handle_report)
            received.wait(timeout_seconds)
            device.set_raw_data_handler(None)
            if statuses:
                return statuses[-1]
        except (OSError, hid.HIDError):
            continue
        finally:
            device.close()
    return None


KEYBOARD_VENDOR_ID = 0x0C45
KEYBOARD_PRODUCT_ID = 0xFEFE

# The vendor stream repeats a 3-report cycle; the battery-ish value sits at [26]
# of the type-0x10 report and jitters by a few points, so it is median-filtered.
_KEYBOARD_REPORT_TYPE = 0x10
_KEYBOARD_BATTERY_INDEX = 26
_KEYBOARD_HISTORY = 5

_KEYBOARD_VALUES: list[int] = []
_KEYBOARD_CLOCK = ""
_KEYBOARD_REPORTS = 0
_KEYBOARD_LOCK = threading.Lock()
_KEYBOARD_LISTENER = None
_KEYBOARD_LISTENER_LOCK = threading.Lock()


def parse_keyboard_battery(raw: list[int]) -> int | None:
    """Return the raw battery-ish byte of a type-0x10 vendor report."""
    if len(raw) <= _KEYBOARD_BATTERY_INDEX:
        return None
    if raw[2] != _KEYBOARD_REPORT_TYPE:
        return None
    value = raw[_KEYBOARD_BATTERY_INDEX]
    if not 0 <= value <= 100:
        return None
    return value


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


_KEYBOARD_CACHE_KEY = f"{KEYBOARD_VENDOR_ID:04X}:{KEYBOARD_PRODUCT_ID:04X}"


def _save_keyboard_reading(percent: int, clock: str) -> None:
    payload: dict[str, object] = {}
    try:
        existing = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            payload = existing
    except (OSError, ValueError):
        payload = {}
    payload[_KEYBOARD_CACHE_KEY] = {
        "battery": percent,
        "captured_clock": clock,
        "saved_at": time.time(),
    }
    try:
        _CACHE_FILE.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def _load_keyboard_reading() -> None:
    """Restore the last reading so an idle keyboard still shows a value."""
    global _KEYBOARD_CLOCK
    try:
        payload = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    entry = payload.get(_KEYBOARD_CACHE_KEY) if isinstance(payload, dict) else None
    if not isinstance(entry, dict):
        return
    try:
        percent = int(entry["battery"])
        age = max(0.0, time.time() - float(entry["saved_at"]))
    except (KeyError, TypeError, ValueError):
        return
    if age > 86400 or not 0 <= percent <= 100:
        return
    with _KEYBOARD_LOCK:
        _KEYBOARD_VALUES.extend([percent] * _KEYBOARD_HISTORY)
        _KEYBOARD_CLOCK = str(entry.get("captured_clock", ""))


class KeyboardBroadcastListener:
    """Passively record the vendor stream; never sends a report."""

    def __init__(self, vendor_id: int, product_id: int) -> None:
        self.vendor_id = vendor_id
        self.product_id = product_id
        self._stop = threading.Event()
        self._thread = None
        self.connected = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="keyboard-battery-listener", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            interface = self._find_interface()
            if interface is None:
                self.connected = False
                self._stop.wait(5)
                continue
            self.connected = True
            try:
                read_input_reports(interface, self._handle, self._stop)
            except Exception:
                pass
            finally:
                self.connected = False
            if not self._stop.is_set():
                self._stop.wait(3)

    def _find_interface(self):
        for interface in enumerate_hid_interfaces():
            if interface.vid_pid != f"{self.vendor_id:04X}:{self.product_id:04X}":
                continue
            if interface.usage_page != 0xFF60 or interface.usage != 0x61:
                continue
            if interface.input_report_length < 2:
                continue
            return interface
        return None

    def _handle(self, data: list[int]) -> None:
        global _KEYBOARD_CLOCK, _KEYBOARD_REPORTS
        value = parse_keyboard_battery([int(v) for v in data])
        if value is None:
            return
        with _KEYBOARD_LOCK:
            _KEYBOARD_VALUES.append(value)
            del _KEYBOARD_VALUES[:-_KEYBOARD_HISTORY]
            _KEYBOARD_CLOCK = datetime.now().strftime("%H:%M")
            _KEYBOARD_REPORTS += 1
            smoothed = _median(_KEYBOARD_VALUES)
        _save_keyboard_reading(smoothed, _KEYBOARD_CLOCK)


def start_keyboard_listener(
    vendor_id: int = KEYBOARD_VENDOR_ID,
    product_id: int = KEYBOARD_PRODUCT_ID,
) -> KeyboardBroadcastListener:
    global _KEYBOARD_LISTENER
    with _KEYBOARD_LISTENER_LOCK:
        if _KEYBOARD_LISTENER is None:
            _KEYBOARD_LISTENER = KeyboardBroadcastListener(vendor_id, product_id)
            _KEYBOARD_LISTENER.start()
        return _KEYBOARD_LISTENER


def stop_keyboard_listener() -> None:
    global _KEYBOARD_LISTENER
    with _KEYBOARD_LISTENER_LOCK:
        if _KEYBOARD_LISTENER is not None:
            _KEYBOARD_LISTENER.stop()
            _KEYBOARD_LISTENER = None


_load_keyboard_reading()


def read_keyboard_battery() -> tuple[int, str] | None:
    """Return the median of recent readings, or None before any report."""
    with _KEYBOARD_LOCK:
        if not _KEYBOARD_VALUES:
            return None
        return _median(_KEYBOARD_VALUES), _KEYBOARD_CLOCK
