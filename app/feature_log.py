"""Long-running logger for the 3554:FA09 keyboard Feature Report 6.

The report currently reads [6, 0, 2, 100, 100, 100, 53, 21]. Which of those
bytes is the battery is still unproven, and a full-charge keyboard keeps every
candidate at 100, so the fields can only be told apart once the level drops.
Run this in the background while using the keyboard, then compare the rows.

Usage:
    python -m app.feature_log
    python -m app.feature_log --interval 60 --output keyboard1.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

from .hid_inventory import enumerate_hid_interfaces, read_feature_report

VENDOR_ID = 0x3554
PRODUCT_ID = 0xFA09
USAGE_PAGE = 0xFF04
REPORT_ID = 6
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "keyboard1_feature_log.csv"


def find_interface():
    for interface in enumerate_hid_interfaces():
        if interface.vid_pid != f"{VENDOR_ID:04X}:{PRODUCT_ID:04X}":
            continue
        if interface.usage_page != USAGE_PAGE:
            continue
        if interface.feature_report_length <= 0:
            continue
        return interface
    return None


def read_row() -> list[int] | None:
    interface = find_interface()
    if interface is None:
        return None
    data = read_feature_report(interface, REPORT_ID)
    if data is None:
        return None
    return [int(value) for value in data]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval", type=float, default=60.0, help="seconds between samples"
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="CSV output path"
    )
    parser.add_argument(
        "--count", type=int, default=0, help="stop after N samples (0 = run forever)"
    )
    args = parser.parse_args()

    columns = ["timestamp"] + [f"byte{i}" for i in range(8)]
    write_header = not args.output.exists()
    previous: list[int] | None = None
    taken = 0

    print(f"记录 {VENDOR_ID:04X}:{PRODUCT_ID:04X} Feature Report {REPORT_ID}")
    print(f"间隔 {args.interval:g}s，输出 {args.output}")
    if previous is None:
        print("按 Ctrl+C 结束。电量变化后对比各行即可定位字段。")

    try:
        while True:
            row = read_row()
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with args.output.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                if write_header:
                    writer.writerow(columns)
                    write_header = False
                if row is None:
                    writer.writerow([stamp] + ["NA"] * 8)
                    print(f"{stamp}  设备不可用或读取失败")
                else:
                    writer.writerow([stamp] + [str(v) for v in row])
                    if row != previous:
                        marker = "  <- 变化" if previous is not None else ""
                        print(f"{stamp}  {row}{marker}")
                        previous = row
            taken += 1
            if args.count and taken >= args.count:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n已停止。")

    print(f"共记录 {taken} 条 -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
