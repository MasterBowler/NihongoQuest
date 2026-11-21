"""Pitch-accent diagram (low/high mora steps)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from nihongo_quest.core import kana as K
from nihongo_quest.ui import theme as T


class PitchDiagram(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._morae: list[str] = []
        self._pattern: list[bool] = []
        self._name = ""
        self.setMinimumHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_pitch(self, kana: str, accent: int) -> None:
        morae = K.split_morae(kana)
        self._morae = morae
        self._pattern = K.pitch_pattern(len(morae), accent) if morae else []
        self._name = K.pitch_name(len(morae), accent) if morae else ""
        self.update()

    def clear(self) -> None:
        self._morae, self._pattern, self._name = [], [], ""
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._morae or not self._pattern:
            p.setPen(QColor(T.FOG_DIM))
            p.setFont(QFont("Zen Maru Gothic", 11))
            p.drawText(self.rect(), Qt.AlignCenter, "pitch unknown")
            p.end()
            return
        n = len(self._morae)
        margin_x = 20
        usable = max(self.width() - 2 * margin_x, 40)
        step = usable / max(n, 1)
        low_y, high_y = self.height() - 28, 18
        pts = []
        for i, high in enumerate(self._pattern[:n]):
            x = margin_x + step * i + step / 2
            y = high_y if high else low_y
            pts.append(QPointF(x, y))
        pen = QPen(QColor(T.GOLD), 2.5)
        p.setPen(pen)
        for i in range(len(pts) - 1):
            p.drawLine(pts[i], pts[i + 1])
        for pt in pts:
            p.setBrush(QColor(T.GOLD_SOFT))
            p.drawEllipse(pt, 4, 4)
        p.setFont(QFont("Klee One", 13))
        p.setPen(QColor(T.FOG))
        for i, m in enumerate(self._morae):
            x = margin_x + step * i
            p.drawText(int(x), self.height() - 6, int(step), 18, Qt.AlignHCenter, m)
        if self._name:
            p.setFont(QFont("Zen Maru Gothic", 10))
            p.setPen(QColor(T.FOG_DIM))
            p.drawText(8, 14, self._name)
        p.end()
