"""Soft falling sakura petals for atmosphere (optional, toggled in settings)."""
from __future__ import annotations

import random

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from nihongo_quest.ui import theme as T


class PetalField(QWidget):
    def __init__(self, parent=None, count: int = 28) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._rng = random.Random(7)
        self._petals = [self._spawn(True) for _ in range(count)]
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._step)
        self._enabled = True

    def set_enabled(self, on: bool) -> None:
        self._enabled = on
        self.setVisible(on)
        if on:
            self._timer.start()
        else:
            self._timer.stop()
            self.update()

    def start(self) -> None:
        if self._enabled:
            self._timer.start()

    def _spawn(self, anywhere: bool = False) -> dict:
        return {
            "x": self._rng.uniform(0, max(self.width(), 1)),
            "y": self._rng.uniform(0, max(self.height(), 1)) if anywhere else -20,
            "r": self._rng.uniform(3, 7),
            "vx": self._rng.uniform(-0.4, 0.6),
            "vy": self._rng.uniform(0.6, 1.6),
            "a": self._rng.uniform(0, 6.28),
            "spin": self._rng.uniform(-0.05, 0.05),
            "alpha": self._rng.randint(60, 140),
        }

    def _step(self) -> None:
        w, h = max(self.width(), 1), max(self.height(), 1)
        for p in self._petals:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["a"] += p["spin"]
            if p["y"] > h + 20 or p["x"] < -20 or p["x"] > w + 20:
                p.update(self._spawn(False))
                p["x"] = self._rng.uniform(0, w)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._enabled:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(T.SAKURA)
        for p in self._petals:
            color.setAlpha(p["alpha"])
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.save()
            painter.translate(p["x"], p["y"])
            painter.rotate(p["a"] * 57.3)
            painter.drawEllipse(int(-p["r"]), int(-p["r"] * 0.55), int(p["r"] * 2), int(p["r"] * 1.1))
            painter.restore()
        painter.end()
