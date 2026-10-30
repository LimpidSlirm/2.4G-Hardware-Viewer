from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

FULL_COLOR = QColor("#22c55e")
MID_COLOR = QColor("#fbbf24")
LOW_COLOR = QColor("#ef4444")
SHELL_COLOR = QColor("#cbd5e1")


def battery_color(percent: int) -> QColor:
    if percent >= 60:
        return FULL_COLOR
    if percent >= 25:
        return MID_COLOR
    return LOW_COLOR


def make_battery_icon(percent: int | None) -> QIcon:
    """Small battery glyph for the notification area."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(SHELL_COLOR, 4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(4, 16, 48, 32), 5, 5)
    painter.drawRoundedRect(QRectF(52, 25, 8, 14), 3, 3)

    if percent is not None:
        clamped = max(0, min(100, percent))
        inner_width = max(1.0, 42.0 * clamped / 100.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(battery_color(clamped))
        painter.drawRoundedRect(QRectF(8, 20, inner_width, 24), 3, 3)
        if clamped == 0:
            painter.setPen(QPen(LOW_COLOR, 4))
            painter.drawLine(10, 42, 50, 22)
    painter.end()
    return QIcon(pixmap)
