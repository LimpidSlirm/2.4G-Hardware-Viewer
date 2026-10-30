from __future__ import annotations

import threading

from dataclasses import dataclass

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


def read_mouse_battery_candidates(
    timeout_seconds: float = 8.0,
) -> list[BatteryReading]:
    readings: list[BatteryReading] = []
    devices = hid.HidDeviceFilter(vendor_id=0x24AE, product_id=0x1411).get_devices()
    for device in devices:
        try:
            device.open()
            if not any(
                report.report_id == 7 for report in device.find_input_reports()
            ):
                continue

            received = threading.Event()
            battery_values: list[int] = []

            def handle_report(data: list[int]) -> None:
                if len(data) > 8 and data[0] == 7 and 0 <= data[8] <= 100:
                    battery_values.append(int(data[8]))
                    received.set()

            device.set_raw_data_handler(handle_report)
            received.wait(timeout_seconds)
            device.set_raw_data_handler(None)
            if battery_values:
                readings.append(
                    BatteryReading(
                        vendor_id=device.vendor_id,
                        product_id=device.product_id,
                        report_id=7,
                        values=(battery_values[-1],),
                        source="厂商输入报告（24AE:1411 / Report 7）",
                    )
                )
        except (OSError, hid.HIDError):
            continue
        finally:
            device.close()
    return readings
