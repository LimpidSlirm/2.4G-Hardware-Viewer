from __future__ import annotations

import sys
from dataclasses import replace
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

from .autostart import (
    create_desktop_shortcut,
    install_autostart,
    remove_autostart,
    remove_desktop_shortcut,
)
from .single_instance import (
    acquire_single_instance,
    clear_reveal_request,
    request_reveal,
    take_reveal_request,
)
from .settings import clear_window_state, load_window_state, save_window_state
from .battery_protocols import (
    KEYBOARD_PRODUCT_ID,
    KEYBOARD_VENDOR_ID,
    read_keyboard_battery,
    read_mouse_battery,
    start_keyboard_listener,
    start_mouse_listener,
    stop_keyboard_listener,
    stop_mouse_listener,
)
from .device_discovery import DeviceDiscoveryError, DeviceRecord, discover_devices
from .hotkey import MOD_ALT, MOD_CONTROL, GlobalHotkey

FULL_WIDTH = 500
MINI_WIDTH = 210
HOTKEY_ID = 0x2A17
HOTKEY_VK_B = 0x42

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

DeviceKey = tuple[str, str, str, str]


def _status_color(status: str) -> str:
    normalized = status.upper()
    if normalized in {"OK", "已读取"}:
        return GREEN_COLOR
    if normalized == "候选":
        return AMBER_COLOR
    return RED_COLOR


def _meta_text(device: DeviceRecord, readings: tuple[tuple[str, int, str], ...]) -> str:
    if not readings:
        return "电量未公开"
    sources = list(dict.fromkeys(source for _label, _percent, source in readings))
    return " / ".join(sources)


def _primary_member(members: list[DeviceRecord]) -> DeviceRecord:
    """The MI_00 interface carries the device's main function."""
    for member in members:
        if "MI_00" in member.instance_id.upper():
            return member
    return members[0]


def _merged_name(
    member: DeviceRecord,
    categories: set[str],
    roles: set[str],
) -> str:
    if member.category == "音频设备":
        return member.name
    if roles == {"键盘", "鼠标"}:
        return "无线键鼠接收器"
    if roles == {"键盘"}:
        return "无线键盘"
    if roles == {"鼠标"}:
        return "无线鼠标"
    if {"键盘", "鼠标"} <= categories:
        return f"无线{member.category}"
    return f"无线{member.category}"


def _merge_by_device(
    devices: list[DeviceRecord],
    readings_by_device: dict[str, list[tuple[str, int, str]]],
) -> list[DeviceRecord]:
    """Collapse every HID collection of one physical device into a single row."""
    groups: dict[str, list[DeviceRecord]] = {}
    for device in devices:
        key = device.vid_pid or f"{device.category}|{device.name}"
        groups.setdefault(key, []).append(device)

    merged: list[DeviceRecord] = []
    for members in groups.values():
        primary = _primary_member(members)
        categories = {member.category for member in members}
        readings = list(readings_by_device.get(primary.vid_pid or "", ()))
        merged.append(
            replace(
                primary,
                category=primary.category,
                name=_merged_name(
                    primary, categories, {reading[0] for reading in readings}
                ),
                battery_percent=readings[0][1] if readings else None,
                battery_source=readings[0][2] if readings else None,
                battery_readings=tuple(readings),
            )
        )
    return merged



class DeviceDiscoveryThread(QThread):
    devices_found = Signal(list)
    discovery_failed = Signal(str)

    def run(self) -> None:
        try:
            devices = discover_devices()
            readings: dict[str, list[tuple[str, int, str]]] = {}

            keyboard_battery = read_keyboard_battery()
            if keyboard_battery is not None:
                percent, clock = keyboard_battery
                key = f"{KEYBOARD_VENDOR_ID:04X}:{KEYBOARD_PRODUCT_ID:04X}"
                readings.setdefault(key, []).append(
                    ("键盘", percent, f"厂商广播 · {clock}")
                )

            mouse_status = read_mouse_battery()
            if mouse_status is not None:
                source = "厂商 HID 报告"
                if mouse_status.cached:
                    source = f"厂商 HID 报告 · 缓存 {mouse_status.captured_clock}"
                key = f"{mouse_status.vendor_id:04X}:{mouse_status.product_id:04X}"
                readings.setdefault(key, []).append(
                    ("鼠标", mouse_status.battery_percent, source)
                )

            self.devices_found.emit(_merge_by_device(devices, readings))
        except DeviceDiscoveryError as exc:
            self.discovery_failed.emit(str(exc))


def _device_key(device: DeviceRecord) -> DeviceKey:
    # VID:PID keeps two different keyboards or mice from collapsing into one row,
    # while interfaces of the same device still dedupe.
    return (
        device.category,
        device.name.casefold(),
        device.status.casefold(),
        device.vid_pid or "",
    )


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

        readings = device.battery_readings
        if not readings and device.battery_percent is not None:
            readings = (
                (
                    "电量",
                    device.battery_percent,
                    device.battery_source or device.transport,
                ),
            )

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

        if len(readings) == 1:
            percent = self._prepare(QLabel(f"{readings[0][1]}%"))
            percent.setStyleSheet(
                f"color: {GREEN_TEXT}; font-size: 12px; font-weight: 600;"
            )
            header.addWidget(percent, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        parts = [part for part in (device.vid_pid, _meta_text(device, readings)) if part]
        meta = self._prepare(QLabel(" · ".join(parts)))
        meta.setStyleSheet(f"color: {META_COLOR}; font-size: 10px;")
        layout.addWidget(meta)

        for label, percent_value, _source in readings:
            if len(readings) == 1:
                line = QHBoxLayout()
                line.setSpacing(0)
            else:
                line = QHBoxLayout()
                line.setSpacing(6)
                tag = self._prepare(QLabel(label))
                tag.setStyleSheet(f"color: {META_COLOR}; font-size: 10px;")
                tag.setFixedWidth(28)
                line.addWidget(tag)
            bar = self._prepare(QProgressBar())
            bar.setRange(0, 100)
            bar.setValue(max(0, min(100, percent_value)))
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            bar.setStyleSheet(self._BAR_STYLE)
            line.addWidget(bar, 1)
            if len(readings) > 1:
                value = self._prepare(QLabel(f"{percent_value}%"))
                value.setStyleSheet(
                    f"color: {GREEN_TEXT}; font-size: 10px; font-weight: 600;"
                )
                value.setFixedWidth(34)
                value.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                line.addWidget(value)
            layout.addLayout(line)

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
        self._detail_key: Optional[DeviceKey] = None
        self._device_rows: dict[DeviceKey, DeviceRow] = {}
        self.setWindowTitle("Hardware Viewer")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            # Tool windows get WS_EX_TOOLWINDOW, which keeps this overlay out of
            # the taskbar button area and out of Alt+Tab.
            | Qt.WindowType.Tool
        )
        # Qt.Tool windows default to WA_QuitOnClose = False, so closing the
        # overlay left a headless process holding the single-instance slot and
        # every later launch looked like it did nothing.
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(self._opacity)
        self._compact = True
        self.setFixedWidth(MINI_WIDTH)
        self._build_ui()
        self._apply_mode()
        self._discovery_thread: Optional[DeviceDiscoveryThread] = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_devices)
        self._refresh_timer.start(300000)
        self._last_mouse_clock: Optional[str] = None
        # The mouse reports rarely, so poll the listener cache and refresh the
        # view as soon as a new reading lands instead of waiting five minutes.
        self._mouse_watch = QTimer(self)
        self._mouse_watch.timeout.connect(self._watch_mouse_reading)
        self._mouse_watch.start(3000)
        # A second launch writes a small marker file instead of talking over IPC;
        # polling it here is enough and cannot get stuck mid-handshake.
        self._reveal_watch = QTimer(self)
        self._reveal_watch.timeout.connect(self._watch_reveal_request)
        self._reveal_watch.start(800)
        self.refresh_devices()

    def _watch_reveal_request(self) -> None:
        if take_reveal_request():
            self.reveal()

    def _watch_mouse_reading(self) -> None:
        status = read_mouse_battery(timeout_seconds=0.0)
        if status is None:
            return
        clock = f"{status.captured_clock}|{status.battery_percent}"
        if clock == self._last_mouse_clock:
            return
        if self._discovery_thread is not None and self._discovery_thread.isRunning():
            # A refresh is already in flight; keep the pending value so the next
            # tick retries instead of dropping this reading.
            return
        self._last_mouse_clock = clock
        self.refresh_devices()

    def _build_ui(self) -> None:
        panel = QWidget(self)
        panel.setObjectName("panel")
        self._panel = panel
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
        hint = QLabel("拖动移动 · 点击行查看详情 · Ctrl+Alt+B 切换 · Esc 关闭")
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

        self._mini_layout = QVBoxLayout()
        self._mini_layout.setSpacing(5)
        mini_panel = QWidget(self)
        mini_panel.setObjectName("miniPanel")
        mini_panel.setStyleSheet(
            f"""
            QWidget#miniPanel {{
                background-color: rgba(17, 23, 32, 235);
                border: 1px solid rgba(148, 163, 184, 70);
                border-radius: 10px;
            }}
            QLabel {{
                color: {NAME_COLOR};
            }}
            """
        )
        mini_layout = QVBoxLayout(mini_panel)
        mini_layout.setContentsMargins(10, 8, 10, 8)
        mini_layout.setSpacing(4)
        mini_layout.addLayout(self._mini_layout)
        self._mini_panel = mini_panel
        outer_layout.addWidget(mini_panel)
        self.setMinimumHeight(60)

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
            bool(device.battery_readings) or device.battery_percent is not None
            for device in devices
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
        self._render_mini(devices)
        self._replace_device_rows(devices)

    def _display_discovery_error(self, message: str) -> None:
        self._subtitle.setText("设备读取失败")
        self._battery_summary.setText("电量：读取失败")
        self._refresh_info.setText(
            f"失败 {datetime.now().strftime('%H:%M:%S')} · 每 5 分钟 · 透明度 {round(self._opacity * 100)}%"
        )
        self._render_mini([])
        self._replace_device_rows([f"错误：{message}"])

    def _discovery_finished(self) -> None:
        self._refresh_button.setEnabled(True)
        if self._discovery_thread is not None:
            self._discovery_thread.deleteLater()
            self._discovery_thread = None

    @staticmethod
    def _unique_display_devices(devices: list[DeviceRecord]) -> list[DeviceRecord]:
        unique_devices: list[DeviceRecord] = []
        seen: set[DeviceKey] = set()
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
            self._schedule_fit()
            return
        if isinstance(devices[0], str):
            for row in devices:
                self._add_device_label(str(row), f"color: {RED_COLOR}; font-size: 11px;")
            self._hide_details()
            self._schedule_fit()
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
        self._schedule_fit()

    def _active_panel(self) -> QWidget:
        return self._mini_panel if self._compact else self._panel

    def _fit_height(self) -> None:
        panel = self._active_panel()
        panel_layout = panel.layout()
        if panel_layout is not None:
            panel_layout.activate()
        screen = self.screen()
        available = screen.availableGeometry().height() if screen else 1080
        limit = max(320, available - 80)
        hint = panel.sizeHint().height()
        if panel_layout is not None:
            margins = panel_layout.contentsMargins()
            needed = (
                panel_layout.minimumSize().height()
                + margins.top()
                + margins.bottom()
            )
            hint = max(hint, needed)
        target = max(self.minimumHeight(), min(limit, hint))
        if target != self.height():
            self.resize(self.width(), target)

    def _schedule_fit(self) -> None:
        # Row widgets report their real size only after the event loop has laid
        # them out, so fit once now and once on the next tick.
        self._fit_height()
        QTimer.singleShot(0, self._fit_height)

    def _apply_mode(self) -> None:
        self._mini_panel.setVisible(self._compact)
        self._panel.setVisible(not self._compact)
        self.setFixedWidth(MINI_WIDTH if self._compact else FULL_WIDTH)
        self._schedule_fit()

    def toggle_mode(self) -> None:
        self._compact = not self._compact
        self._apply_mode()
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def _render_mini(self, devices: list[DeviceRecord]) -> None:
        while self._mini_layout.count():
            item = self._mini_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
            elif item.layout() is not None:
                child = item.layout()
                while child.count():
                    entry = child.takeAt(0)
                    if entry.widget() is not None:
                        entry.widget().deleteLater()

        rows: list[tuple[str, int]] = []
        for device in devices:
            for label, percent, _source in device.battery_readings:
                rows.append((label, percent))
            if not device.battery_readings and device.battery_percent is not None:
                rows.append((device.name, device.battery_percent))

        if not rows:
            empty = QLabel("暂无电量")
            empty.setStyleSheet(f"color: {META_COLOR}; font-size: 10px;")
            self._mini_layout.addWidget(empty)
            return
        for label, percent in rows:
            self._mini_layout.addWidget(self._mini_row(label, percent))

    def _mini_row(self, label: str, percent: int) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        tag = QLabel(label)
        tag.setStyleSheet(f"color: {META_COLOR}; font-size: 10px;")
        tag.setFixedWidth(30)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(max(0, min(100, percent)))
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        bar.setStyleSheet(DeviceRow._BAR_STYLE)
        value = QLabel(f"{percent}%")
        value.setStyleSheet(
            f"color: {GREEN_TEXT}; font-size: 11px; font-weight: 600;"
        )
        value.setFixedWidth(36)
        value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(tag)
        layout.addWidget(bar, 1)
        layout.addWidget(value)
        return row

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
        self._schedule_fit()

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
        self._schedule_fit()

    @staticmethod
    def _detail_text(device: DeviceRecord) -> str:
        readings = device.battery_readings
        if readings:
            battery = " / ".join(
                f"{label} {percent}%（{source}）"
                if "候选" in source
                else f"{label} {percent}%"
                for label, percent, source in readings
            )
        elif device.battery_percent is not None:
            battery = f"{device.battery_percent}%"
        else:
            battery = "未公开"
        link = f"连接 {device.transport}"
        if device.vid_pid:
            link = f"{link} · VID:PID {device.vid_pid}"
        device_id = device.instance_id.replace("\\", "\\\u200b")
        return (
            f"{device.name}\n"
            f"电量 {battery} · 状态 {device.status}\n"
            f"{link}\n"
            f"ID {device_id}"
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
        self._persist_position()
        super().mouseReleaseEvent(event)

    def reveal(self) -> None:
        """Show the overlay and bring it to the front (used by a second launch)."""
        if not self.isVisible():
            self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _persist_position(self) -> None:
        point = self.frameGeometry().topLeft()
        save_window_state(point.x(), point.y(), self._compact)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_mode()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def closeEvent(self, event) -> None:
        self._persist_position()
        self._refresh_timer.stop()
        self._mouse_watch.stop()
        self._reveal_watch.stop()
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


def _restore_position(window: "OverlayWindow", app: QApplication) -> None:
    """Place the window where it was left, if that spot still exists."""
    state = load_window_state()
    if state is not None:
        point = QPoint(state.x, state.y)
        for screen in app.screens():
            geometry = screen.availableGeometry()
            # Keep the top-left corner reachable: a saved spot on a monitor that
            # has since been unplugged would otherwise park the window off-screen.
            if geometry.contains(point):
                window.move(point)
                if state.compact != window._compact:
                    window._compact = state.compact
                    window._apply_mode()
                return
    position = app.primaryScreen().availableGeometry().topLeft() + QPoint(40, 40)
    window.move(position)


def main() -> int:
    if "--install-autostart" in sys.argv:
        print(f"已设置开机自启：{install_autostart()}")
        return 0
    if "--remove-autostart" in sys.argv:
        print("已取消开机自启" if remove_autostart() else "当前没有开机自启项")
        return 0
    if "--create-shortcut" in sys.argv:
        print(f"已创建桌面快捷方式：{create_desktop_shortcut()}")
        return 0
    if "--remove-shortcut" in sys.argv:
        print("已删除桌面快捷方式" if remove_desktop_shortcut() else "桌面没有快捷方式")
        return 0
    if "--setup" in sys.argv:
        print(f"开机自启：{install_autostart()}")
        print(f"桌面快捷方式：{create_desktop_shortcut()}")
        return 0
    if "--reset-position" in sys.argv:
        print("已清除记住的窗口位置" if clear_window_state() else "没有记住的位置")
        return 0

    app = QApplication(sys.argv)
    if not acquire_single_instance():
        # Hand the request to the running instance and leave; otherwise a second
        # click on the shortcut would appear to do nothing at all.
        request_reveal()
        return 0
    clear_reveal_request()
    start_mouse_listener()
    start_keyboard_listener()
    window = OverlayWindow()
    _restore_position(window, app)
    window.show()

    hotkey = GlobalHotkey(
        HOTKEY_ID, MOD_CONTROL | MOD_ALT, HOTKEY_VK_B, window.toggle_mode
    )
    app.installNativeEventFilter(hotkey)

    if "--smoke-test" in sys.argv:
        if window._discovery_thread is not None:
            window._discovery_thread.finished.connect(app.quit)
        else:
            QTimer.singleShot(100, app.quit)

    exit_code = app.exec()
    stop_mouse_listener()
    stop_keyboard_listener()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
