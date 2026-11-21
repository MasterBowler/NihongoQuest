"""Circular magnifier that follows the cursor (zoom loop)."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from nihongo_quest.ui import theme as T


class MagnifierLoupe(QWidget):
    """Hold a hotkey to inspect UI under the cursor at 2× (configurable)."""

    def __init__(self, parent=None, *, diameter: int = 240, factor: float = 2.25) -> None:
        super().__init__(
            parent,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._diameter = diameter
        self._factor = factor
        self._pix = QPixmap()
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self.resize(diameter, diameter)
        self.hide()

    def set_factor(self, factor: float) -> None:
        self._factor = max(1.5, min(4.0, float(factor)))

    def start(self) -> None:
        self._timer.start()
        self.show()
        self._tick()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def toggle(self) -> None:
        if self.active:
            self.stop()
        else:
            self.start()

    def _tick(self) -> None:
        pos = QCursor.pos()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        # Sample a square around the cursor, then paint it scaled into the circle.
        sample = int(self._diameter / self._factor)
        half = sample // 2
        region = QRect(pos.x() - half, pos.y() - half, sample, sample)
        self._pix = screen.grabWindow(0, region.x(), region.y(), region.width(), region.height())
        # Keep the loupe offset so it does not cover the exact point being inspected.
        offset = QPoint(self._diameter // 2 + 28, -self._diameter // 2 - 12)
        self.move(pos + offset)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        d = self._diameter
        clip = QPainterPath()
        clip.addEllipse(2, 2, d - 4, d - 4)
        p.setClipPath(clip)
        if not self._pix.isNull():
            p.drawPixmap(QRect(0, 0, d, d), self._pix)
        else:
            p.fillRect(self.rect(), QColor(T.INK))
        p.setClipping(False)
        pen = QPen(QColor(T.GOLD), 3)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(2, 2, d - 4, d - 4)
        # Crosshair
        p.setPen(QPen(QColor(T.SEAL), 1, Qt.DashLine))
        c = d // 2
        p.drawLine(c, 12, c, d - 12)
        p.drawLine(12, c, d - 12, c)
        p.end()
