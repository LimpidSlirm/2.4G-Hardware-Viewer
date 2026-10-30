from __future__ import annotations

import sys
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QPoint, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QProgressBar,
    QPushButton,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .battery_protocols import read_mouse_battery, read_vendor_battery_candidates
from .device_discovery import DeviceDiscoveryError, DeviceRecord, discover_devices

TITLE_COLOR = "#eef4fb"
SUBTITLE_COLOR = "#93a3b8"
SECTION_COLOR = "#8ab4e8"
NAME_COLOR = "#e6edf7"
META_COLOR = "#8a9bb1"
DETAIL_COLOR = "#c8d4e3"
AMBER_COLOR = "#fbbf24"
RED_COLOR = "#f87171"
GREEN_COLOR = "#4ade80"
GREEN_TEXT = "#6ee7a0"


def _status_color(status: str) -> str:
    normalized = status.upper()
    if normalized in {"OK", "已读取"}:
        return GREEN_COLOR
    if normalized == "候选":
        return AMBER_COLOR
    return RED_COLOR


def _source_text(device: DeviceRecord) -> str:
    if device.instance_id == "mouse-input-report":
        return "厂商 HID 报告"
    if device.instance_id == "vendor-feature-report":
        return "厂商 HID 报告（候选）"
    return device.transport



class DeviceDiscoveryThread(QThread):
    devices_found = Signal(list)
    discovery_failed = Signal(str)

    def run(self) -> None:
        try:
            devices = discover_devices()
            for reading in read_vendor_battery_candidates():
                devices.append(
                    DeviceRecord(
                        category="键盘",
                        name="无线键盘",
                        status="候选",
                        instance_id="vendor-feature-report",
                        battery_percent=reading.values[0],
                    )
                )
            mouse_status = read_mouse_battery()
            if mouse_status is not None:
                devices.append(
                    DeviceRecord(
                        category="鼠标",
                        name=f"无线鼠标（{mouse_status.dpi_x} DPI）",
                        status="已读取",
                        instance_id="mouse-input-report",
                        battery_percent=mouse_status.battery_percent,
                    )
                )
            self.devices_found.emit(devices)
        except DeviceDiscoveryError as exc:
            self.discovery_failed.emit(str(exc))


def _device_key(device: DeviceRecord) -> tuple[str, str, str]:
    return (device.category, device.name.casefold(), device.status.casefold())


class DeviceRow(QFrame):
    clicked = Signal(DeviceRecord)

    _BAR_STYLE = f"""
        QProgressBar {{
            background-color: rgba(148, 163, 184, 55);
            border: none;
            border-radius: 3px;
        }}
        QProgressBar::chunk {{
            background-color: #22c55e;
            border-radius: 3px;
        }}
    """

    def __init__(self, device: DeviceRecord, selected: bool = False) -> None:
        super().__init__()
        self._device = device
        self.setObjectName("deviceRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_selected(selected)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 8)
        layout.setSpacing(5)

        header = QHBoxLayout()
        header.setSpacing(7)
        dot = self._prepare(QLabel("●"))
        dot.setStyleSheet(f"color: {_status_color(device.status)}; font-size: 9px;")
        header.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)

        self._name = self._prepare(QLabel(device.name))
        self._name.setStyleSheet(f"color: {NAME_COLOR}; font-size: 12px;")
        self._name.setWordWrap(True)
        self._name.setMinimumWidth(0)
        self._name.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        header.addWidget(self._name, 1)

        if device.battery_percent is not None:
            percent = self._prepare(QLabel(f"{device.battery_percent}%"))
            percent.setStyleSheet(
                f"color: {GREEN_TEXT}; font-size: 12px; font-weight: 600;"
            )
            header.addWidget(percent, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        parts = [part for part in (device.vid_pid, _source_text(device)) if part]
        if device.battery_percent is None:
            parts.append("电量未公开")
        meta = self._prepare(QLabel(" · ".join(parts)))
        meta.setStyleSheet(f"color: {META_COLOR}; font-size: 10px;")
        layout.addWidget(meta)

        if device.battery_percent is None:
            return

        bar = self._prepare(QProgressBar())
        bar.setRange(0, 100)
        bar.setValue(max(0, min(100, device.battery_percent)))
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        bar.setStyleSheet(self._BAR_STYLE)
        layout.addWidget(bar)

    def _prepare(self, widget: QLabel | QProgressBar) -> QLabel | QProgressBar:
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        widget.setMinimumWidth(0)
        return widget

    def set_selected(self, selected: bool) -> None:
        background = "rgba(35, 46, 61, 235)" if selected else "rgba(29, 37, 49, 190)"
        border = "rgba(74, 222, 128, 150)" if selected else "rgba(148, 163, 184, 40)"
        self.setStyleSheet(
            f"#deviceRow {{ background-color: {background};"
            f" border: 1px solid {border}; border-radius: 7px; }}"
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._device)
            event.accept()
            return
        super().mousePressEvent(event)


class OverlayWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._drag_offset: Optional[QPoint] = None
        self._opacity = 0.92
        self._detail_key: Optional[tuple[str, str, str]] = None
        self._device_rows: dict[tuple[str, str, str], DeviceRow] = {}
        self.setWindowTitle("Hardware Viewer")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(self._opacity)
        self.setFixedWidth(500)
        self._build_ui()
        self.resize(500, 300)
        self._discovery_thread: Optional[DeviceDiscoveryThread] = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_devices)
        self._refresh_timer.start(300000)
        self.refresh_devices()

    def _build_ui(self) -> None:
        panel = QWidget(self)
        panel.setObjectName("panel")
        panel.setStyleSheet(
            f"""
            QWidget#panel {{
                background-color: rgba(17, 23, 32, 228);
                border: 1px solid rgba(148, 163, 184, 70);
                border-radius: 12px;
            }}
            QLabel {{
                color: {NAME_COLOR};
            }}
            """
        )

        title = QLabel("2.4G Hardware Viewer")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {TITLE_COLOR};")
        self._subtitle = QLabel("正在读取设备…")
        self._subtitle.setStyleSheet(f"color: {SUBTITLE_COLOR}; font-size: 11px;")
        self._battery_summary = QLabel()
        self._battery_summary.setVisible(False)
        self._device_layout = QVBoxLayout()
        self._device_layout.setSpacing(6)
        self._selected_device = QLabel()
        self._selected_device.setWordWrap(True)
        self._selected_device.setMinimumWidth(0)
        self._selected_device.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._selected_device.setStyleSheet(
            f"color: {DETAIL_COLOR}; background-color: rgba(27, 35, 46, 220);"
            " border: 1px solid rgba(148, 163, 184, 45);"
            " border-radius: 7px; padding: 8px; font-size: 11px;"
        )
        self._selected_device.setVisible(False)
        self._refresh_info = QLabel("每 5 分钟自动刷新")
        self._refresh_info.setStyleSheet(f"color: {META_COLOR}; font-size: 10px;")
        self._refresh_button = QPushButton("刷新")
        self._refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_button.setStyleSheet(
            f"""
            QPushButton {{
                color: {DETAIL_COLOR};
                background-color: rgba(45, 58, 76, 200);
                border: 1px solid rgba(148, 163, 184, 80);
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: rgba(60, 78, 100, 230);
                border: 1px solid rgba(148, 163, 184, 130);
            }}
            QPushButton:pressed {{
                background-color: rgba(38, 49, 64, 230);
            }}
            QPushButton:disabled {{
                color: #64748b;
                background-color: rgba(38, 48, 62, 140);
                border: 1px solid rgba(148, 163, 184, 40);
            }}
            """
        )
        self._refresh_button.clicked.connect(self.refresh_devices)
        hint = QLabel("拖动移动 · 点击行查看详情 · Esc 关闭")
        hint.setStyleSheet(f"color: #6b7c92; font-size: 10px;")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)
        layout.addWidget(title)
        layout.addWidget(self._subtitle)
        layout.addWidget(self._battery_summary)
        device_container = QWidget()
        device_container.setLayout(self._device_layout)
        layout.addWidget(device_container, 1)
        layout.addWidget(self._selected_device)
        controls = QHBoxLayout()
        controls.addWidget(self._refresh_info)
        controls.addStretch(1)
        controls.addWidget(self._refresh_button)
        layout.addLayout(controls)
        layout.addWidget(hint)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(panel)
        self.setMinimumHeight(300)
        self.setMaximumHeight(720)

    def refresh_devices(self) -> None:
        if self._discovery_thread is not None and self._discovery_thread.isRunning():
            return
        self._refresh_button.setEnabled(False)
        self._subtitle.setText("正在读取 Windows 设备...")
        self._discovery_thread = DeviceDiscoveryThread(self)
        self._discovery_thread.devices_found.connect(self._display_devices)
        self._discovery_thread.discovery_failed.connect(self._display_discovery_error)
        self._discovery_thread.finished.connect(self._discovery_finished)
        self._discovery_thread.start()

    def _display_devices(self, discovered_devices: list[DeviceRecord]) -> None:
        devices = self._unique_display_devices(discovered_devices)
        online_count = sum(device.status.upper() == "OK" for device in devices)
        readable_battery_count = sum(
            device.battery_percent is not None for device in devices
        )
        unknown_battery_count = len(devices) - readable_battery_count
        self._subtitle.setText(
            f"{len(devices)} 个设备 · {online_count} 个在线"
        )
        self._battery_summary.setText(
            f"电量：已读取 {readable_battery_count} · 未公开 {unknown_battery_count}"
        )
        self._refresh_info.setText(
            f"更新 {datetime.now().strftime('%H:%M:%S')} · 每 5 分钟 · 透明度 {round(self._opacity * 100)}%"
        )
        self._replace_device_rows(devices)

    def _display_discovery_error(self, message: str) -> None:
        self._subtitle.setText("设备读取失败")
        self._battery_summary.setText("电量：读取失败")
        self._refresh_info.setText(
            f"失败 {datetime.now().strftime('%H:%M:%S')} · 每 5 分钟 · 透明度 {round(self._opacity * 100)}%"
        )
        self._replace_device_rows([f"错误：{message}"])

    def _discovery_finished(self) -> None:
        self._refresh_button.setEnabled(True)
        if self._discovery_thread is not None:
            self._discovery_thread.deleteLater()
            self._discovery_thread = None

    @staticmethod
    def _unique_display_devices(devices: list[DeviceRecord]) -> list[DeviceRecord]:
        unique_devices: list[DeviceRecord] = []
        seen: set[tuple[str, str, str]] = set()
        for device in devices:
            key = _device_key(device)
            if key in seen:
                continue
            seen.add(key)
            unique_devices.append(device)
        return unique_devices

    def _replace_device_rows(self, devices: list[DeviceRecord] | list[str]) -> None:
        while self._device_layout.count():
            item = self._device_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._device_rows.clear()

        if not devices:
            self._add_device_label("未发现设备", f"color: {META_COLOR}; font-size: 11px;")
            self._hide_details()
            self._fit_height()
            return
        if isinstance(devices[0], str):
            for row in devices:
                self._add_device_label(str(row), f"color: {RED_COLOR}; font-size: 11px;")
            self._hide_details()
            self._fit_height()
            return

        category_order = ("音频设备", "键盘", "鼠标")
        for category in category_order:
            category_devices = [
                device for device in devices if device.category == category
            ]
            if not category_devices:
                continue
            self._add_device_label(
                f"{category} · {len(category_devices)}",
                f"color: {SECTION_COLOR}; font-size: 10px; font-weight: 600;",
            )
            for device in category_devices:
                self._add_device_row(device)

        self._restore_details(devices)
        self._fit_height()

    def _fit_height(self) -> None:
        self.adjustSize()

    def _add_device_row(self, device: DeviceRecord) -> DeviceRow:
        key = _device_key(device)
        row = DeviceRow(device, selected=key == self._detail_key)
        row.clicked.connect(self._show_device_details)
        self._device_rows[key] = row
        self._device_layout.addWidget(row)
        return row

    def _restore_details(self, devices: list[DeviceRecord]) -> None:
        if self._detail_key is None:
            return
        for device in devices:
            if _device_key(device) == self._detail_key:
                self._selected_device.setText(self._detail_text(device))
                self._selected_device.setVisible(True)
                return
        self._hide_details()

    def _hide_details(self) -> None:
        if self._detail_key is not None:
            row = self._device_rows.get(self._detail_key)
            if row is not None:
                row.set_selected(False)
        self._detail_key = None
        self._selected_device.setVisible(False)
        self._fit_height()

    def _show_device_details(self, device: DeviceRecord) -> None:
        key = _device_key(device)
        if self._detail_key == key:
            self._hide_details()
            return
        previous = self._device_rows.get(self._detail_key) if self._detail_key else None
        if previous is not None:
            previous.set_selected(False)
        self._detail_key = key
        row = self._device_rows.get(key)
        if row is not None:
            row.set_selected(True)
        self._selected_device.setText(self._detail_text(device))
        self._selected_device.setVisible(True)
        self._fit_height()

    @staticmethod
    def _detail_text(device: DeviceRecord) -> str:
        battery = (
            f"{device.battery_percent}%"
            if device.battery_percent is not None
            else "未公开"
        )
        source = _source_text(device)
        link = f"连接 {source}"
        if device.vid_pid:
            link = f"{link} · VID:PID {device.vid_pid}"
        instance = device.instance_id.replace("\\", "\\\u200b")
        return (
            f"{device.name}\n"
            f"电量 {battery} · 状态 {device.status}\n"
            f"{link}\n"
            f"ID {instance}"
        )

    def _add_device_label(self, text: str, style: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(style)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._device_layout.addWidget(label)
        return label

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        if self._discovery_thread is not None and self._discovery_thread.isRunning():
            self._discovery_thread.wait(11000)
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        if event.key() == Qt.Key.Key_F5:
            self.refresh_devices()
            return
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            change = 0.05 if event.key() == Qt.Key.Key_Up else -0.05
            self._opacity = min(1.0, max(0.35, self._opacity + change))
            self.setWindowOpacity(self._opacity)
            self._refresh_info.setText(
                f"每 5 分钟自动刷新 · 透明度 {round(self._opacity * 100)}%"
            )
            return
        super().keyPressEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = OverlayWindow()
    available_geometry = app.primaryScreen().availableGeometry()
    position = available_geometry.topLeft() + QPoint(40, 40)
    window.move(position)
    window.show()

    if "--smoke-test" in sys.argv:
        if window._discovery_thread is not None:
            window._discovery_thread.finished.connect(app.quit)
        else:
            QTimer.singleShot(100, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
