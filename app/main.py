from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QVBoxLayout,
    QWidget,
)

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
        self.setMinimumSize(420, 260)
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
        self._device_layout.setSpacing(3)
        hint = QLabel("拖动窗口移动  |  每 5 秒刷新  |  Esc 关闭")
        hint.setStyleSheet("color: #8290a5; font-size: 11px;")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)
        layout.addWidget(title)
        layout.addWidget(self._subtitle)
        layout.addLayout(self._device_layout)
        layout.addStretch(1)
        layout.addWidget(hint)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(panel)

    def refresh_devices(self) -> None:
        try:
            devices = discover_devices()
        except DeviceDiscoveryError as exc:
            self._subtitle.setText("设备读取失败")
            self._replace_device_rows([f"错误：{exc}"])
            return

        self._subtitle.setText(f"已发现 {len(devices)} 个 Windows 设备")
        rows = [
            f"{device.category}  |  {device.name}  |  {device.status}"
            for device in devices
        ]
        self._replace_device_rows(rows or ["未发现目标设备"])

    def _replace_device_rows(self, rows: list[str]) -> None:
        while self._device_layout.count():
            item = self._device_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for row in rows:
            label = QLabel(row)
            label.setStyleSheet("color: #d7e0ed; font-size: 11px;")
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
