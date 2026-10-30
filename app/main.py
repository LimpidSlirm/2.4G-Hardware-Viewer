from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from .device_discovery import DeviceDiscoveryError, DeviceRecord, discover_devices


class OverlayWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._drag_offset: Optional[QPoint] = None
        self.setWindowTitle("2.4G Hardware Viewer")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(460, 300)
        self._build_ui()
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
        self._refresh_info = QLabel("自动刷新间隔：5 秒")
        self._refresh_info.setStyleSheet("color: #8290a5; font-size: 11px;")
        hint = QLabel("拖动窗口移动  |  Esc 关闭")
        hint.setStyleSheet("color: #8290a5; font-size: 11px;")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)
        layout.addWidget(title)
        layout.addWidget(self._subtitle)
        layout.addLayout(self._device_layout)
        layout.addStretch(1)
        layout.addWidget(self._refresh_info)
        layout.addWidget(hint)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(panel)

    def refresh_devices(self) -> None:
        try:
            devices = self._unique_display_devices(discover_devices())
        except DeviceDiscoveryError as exc:
            self._subtitle.setText("设备读取失败")
            self._replace_device_rows([f"错误：{exc}"])
            return

        online_count = sum(device.status.upper() == "OK" for device in devices)
        self._subtitle.setText(
            f"已发现 {len(devices)} 个设备  |  正常 {online_count}"
        )
        self._replace_device_rows(devices)

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
                self._add_device_label(
                    f"  {device.name}  ·  {device.status}",
                    f"color: {color}; font-size: 11px;",
                )

    def _add_device_label(self, text: str, style: str) -> None:
        label = QLabel(text)
        label.setStyleSheet(style)
        label.setWordWrap(True)
        self._device_layout.addWidget(label)

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

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = OverlayWindow()
    window.move(80, 80)
    window.show()

    if "--smoke-test" in sys.argv:
        QTimer.singleShot(100, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
