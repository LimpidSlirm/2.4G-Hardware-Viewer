from __future__ import annotations

import sys
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QPoint, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .device_discovery import DeviceDiscoveryError, DeviceRecord, discover_devices


class DeviceDiscoveryThread(QThread):
    devices_found = Signal(list)
    discovery_failed = Signal(str)

    def run(self) -> None:
        try:
            self.devices_found.emit(discover_devices())
        except DeviceDiscoveryError as exc:
            self.discovery_failed.emit(str(exc))


class DeviceLabel(QLabel):
    clicked = Signal(DeviceRecord)

    def __init__(self, device: DeviceRecord, text: str, style: str) -> None:
        super().__init__(text)
        self._device = device
        self.setStyleSheet(style)
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._device)
        super().mousePressEvent(event)


class OverlayWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._drag_offset: Optional[QPoint] = None
        self._opacity = 0.92
        self.setWindowTitle("2.4G Hardware Viewer")
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
        self._refresh_timer.start(5000)
        self.refresh_devices()

    def _build_ui(self) -> None:
        panel = QWidget(self)
        panel.setObjectName("panel")
        panel.setStyleSheet(
            """
            QWidget#panel {
                background-color: rgba(24, 28, 36, 220);
                border: 1px solid rgba(160, 180, 210, 150);
                border-radius: 12px;
            }
            QLabel {
                color: #f1f5f9;
            }
            """
        )

        title = QLabel("2.4G Hardware Viewer")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        self._subtitle = QLabel("正在读取 Windows 设备...")
        self._subtitle.setStyleSheet("color: #aab6c8;")
        self._device_layout = QVBoxLayout()
        self._device_layout.setSpacing(4)
        self._selected_device = QLabel("点击设备查看详情")
        self._selected_device.setWordWrap(True)
        self._selected_device.setMinimumWidth(0)
        self._selected_device.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._selected_device.setStyleSheet(
            "color: #b7c5d8; background: rgba(36, 45, 59, 180);"
            " border-radius: 5px; padding: 6px;"
        )
        self._refresh_info = QLabel("自动刷新间隔：5 秒")
        self._refresh_info.setStyleSheet("color: #8290a5; font-size: 11px;")
        self._refresh_button = QPushButton("立即刷新")
        self._refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_button.setStyleSheet(
            """
            QPushButton {
                color: #d7e0ed;
                background-color: rgba(68, 89, 116, 180);
                border: 1px solid rgba(160, 180, 210, 130);
                border-radius: 5px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: rgba(88, 116, 150, 210);
            }
            """
        )
        self._refresh_button.clicked.connect(self.refresh_devices)
        hint = QLabel("拖动窗口移动  |  Esc 关闭")
        hint.setStyleSheet("color: #8290a5; font-size: 11px;")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)
        layout.addWidget(title)
        layout.addWidget(self._subtitle)
        layout.addLayout(self._device_layout)
        layout.addStretch(1)
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
        self._subtitle.setText(
            f"已发现 {len(devices)} 个设备  |  正常 {online_count}"
        )
        self._refresh_info.setText(
            f"刷新：{datetime.now().strftime('%H:%M:%S')}  |  透明度：{round(self._opacity * 100)}%"
        )
        self._replace_device_rows(devices)

    def _display_discovery_error(self, message: str) -> None:
        self._subtitle.setText("设备读取失败")
        self._refresh_info.setText(
            f"失败：{datetime.now().strftime('%H:%M:%S')}  |  透明度：{round(self._opacity * 100)}%"
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
            key = (device.category, device.name.casefold(), device.status.casefold())
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

        if not devices:
            self._add_device_label("未发现目标设备", "color: #d7e0ed;")
            return
        if isinstance(devices[0], str):
            for row in devices:
                self._add_device_label(str(row), "color: #ffb4ab;")
            return

        category_order = ("耳机/音频", "键盘", "鼠标")
        for category in category_order:
            category_devices = [
                device for device in devices if device.category == category
            ]
            if not category_devices:
                continue
            self._add_device_label(
                f"{category} ({len(category_devices)})",
                "color: #91c8ff; font-weight: 600;",
            )
            for device in category_devices:
                color = "#a7e3b1" if device.status.upper() == "OK" else "#ffb4ab"
                label = DeviceLabel(
                    device,
                    f"  {device.name}  ·  {device.status}",
                    f"color: {color}; font-size: 11px;",
                )
                label.setToolTip(f"Windows 实例 ID：\n{device.instance_id}")
                label.clicked.connect(self._show_device_details)
                self._device_layout.addWidget(label)

    def _show_device_details(self, device: DeviceRecord) -> None:
        self._selected_device.setText(
            f"选中：{device.name}\n"
            f"类别：{device.category}  |  状态：{device.status}\n"
            f"实例 ID：{device.instance_id.replace('\\\\', '\\\\\u200b')}"
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
                f"刷新间隔：5 秒  |  透明度：{round(self._opacity * 100)}%"
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
