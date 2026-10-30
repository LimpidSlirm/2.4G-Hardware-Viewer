from __future__ import annotations

import threading
import time

from dataclasses import dataclass, replace
from datetime import datetime

from pywinusb import hid


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


def read_mouse_battery(
    vendor_id: int = 0x24AE,
    product_id: int = 0x1411,
    timeout_seconds: float = 8.0,
    max_cache_age_seconds: float = 86400.0,
) -> RapooStatus | None:
    """Listen for the passive Report 7 broadcast. Never sends a report.

    The mouse broadcasts at irregular intervals and stays silent while asleep,
    so the last valid reading is reused instead of dropping back to unknown.
    """
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
