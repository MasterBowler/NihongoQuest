"""Furigana (ruby) text rendering for Japanese headwords and example sentences."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from nihongo_quest.ui import theme as T


class FuriganaLabel(QWidget):
    """Draws a sequence of (base, reading) segments with readings above kanji."""

    def __init__(self, parent=None, *, base_pt: int = 48, ruby_pt: int = 14,
                 base_color: str = T.INK_TEXT, ruby_color: str = "#6A5544",
                 align: Qt.AlignmentFlag = Qt.AlignCenter) -> None:
        super().__init__(parent)
        self._segments: list[tuple[str, str]] = []
        self._base_pt = base_pt
        self._ruby_pt = ruby_pt
        self._base_color = QColor(base_color)
        self._ruby_color = QColor(ruby_color)
        self._align = align
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(base_pt + ruby_pt + 16)

    def set_segments(self, segments: list[tuple[str, str]]) -> None:
        self._segments = list(segments)
        self.update()
        self.updateGeometry()

    def set_plain(self, text: str) -> None:
        self.set_segments([(text, "")])

    def set_colors(self, base: str, ruby: str) -> None:
        self._base_color = QColor(base)
        self._ruby_color = QColor(ruby)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._segments:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        base = QFont("Klee One", self._base_pt)
        ruby = QFont("Zen Maru Gothic", self._ruby_pt)
        p.setFont(base)
        metrics = p.fontMetrics()
        widths = []
        for base_txt, reading in self._segments:
            bw = metrics.horizontalAdvance(base_txt)
            if reading:
                p.setFont(ruby)
                rw = p.fontMetrics().horizontalAdvance(reading)
                p.setFont(base)
                widths.append(max(bw, rw + 4))
            else:
                widths.append(bw)
        total = sum(widths)
        if self._align & Qt.AlignLeft:
            x = 8.0
        elif self._align & Qt.AlignRight:
            x = self.width() - total - 8.0
        else:
            x = (self.width() - total) / 2
        # Vertically center the word block inside whatever height we were given.
        block_h = metrics.ascent() + metrics.descent() + self._ruby_pt + 12
        baseline = (self.height() + block_h) / 2 - metrics.descent() - 4
        ruby_y = baseline - metrics.ascent() - 4
        for (base_txt, reading), w in zip(self._segments, widths):
            p.setFont(base)
            p.setPen(QPen(self._base_color))
            bw = p.fontMetrics().horizontalAdvance(base_txt)
            bx = x + (w - bw) / 2
            p.drawText(QRectF(bx, baseline - metrics.ascent(), bw + 2, metrics.height() + 4),
                       Qt.AlignBottom | Qt.AlignLeft, base_txt)
            if reading:
                p.setFont(ruby)
                p.setPen(QPen(self._ruby_color))
                rw = p.fontMetrics().horizontalAdvance(reading)
                rx = x + (w - rw) / 2
                p.drawText(int(rx), int(ruby_y), reading)
            x += w
        p.end()
