"""Kanji stroke animation and handwriting practice canvas."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from nihongo_quest.core import strokes as S
from nihongo_quest.ui import theme as T


class StrokeCanvas(QWidget):
    """Shows KanjiVG strokes and optionally accepts drawing for judgement."""

    stroke_judged = Signal(bool, str)   # ok, reason
    character_done = Signal(bool)       # True if every stroke matched

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(280, 280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._paths: list[str] = []
        self._polylines: list[list[tuple[float, float]]] = []
        self._done = 0
        self._drawing: list[QPointF] = []
        self._user_strokes: list[list[QPointF]] = []
        self._write_mode = False
        self._guide = True
        self._anim_i = -1
        self._anim_t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.setMouseTracking(True)

    def set_character(self, paths: list[str] | tuple[str, ...], *, write: bool = False,
                      guide: bool = True) -> None:
        self._paths = list(paths)
        self._polylines = [list(S.stroke_points(d, 40)) for d in self._paths]
        self._done = 0
        self._drawing = []
        self._user_strokes = []
        self._write_mode = write
        self._guide = guide
        self._anim_i = -1
        self._timer.stop()
        self.update()

    def clear_drawing(self) -> None:
        self._done = 0
        self._drawing = []
        self._user_strokes = []
        self.update()

    def animate(self) -> None:
        if not self._paths:
            return
        self._write_mode = False
        self._done = 0
        self._anim_i = 0
        self._anim_t = 0.0
        self._timer.start()

    def _tick(self) -> None:
        self._anim_t += 0.035
        if self._anim_t >= 1.0:
            self._anim_t = 0.0
            self._anim_i += 1
            if self._anim_i >= len(self._paths):
                self._timer.stop()
                self._anim_i = -1
                self._done = len(self._paths)
        self.update()

    def _map(self, pt: tuple[float, float]) -> QPointF:
        side = min(self.width(), self.height()) - 24
        ox = (self.width() - side) / 2
        oy = (self.height() - side) / 2
        return QPointF(ox + pt[0] / S.BOX * side, oy + pt[1] / S.BOX * side)

    def _unmap(self, p: QPointF) -> tuple[float, float]:
        side = min(self.width(), self.height()) - 24
        ox = (self.width() - side) / 2
        oy = (self.height() - side) / 2
        return ((p.x() - ox) / side * S.BOX, (p.y() - oy) / side * S.BOX)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 24
        ox = (self.width() - side) / 2
        oy = (self.height() - side) / 2
        # washi square
        p.setBrush(QColor(T.WASHI))
        p.setPen(QPen(QColor(T.WASHI_DIM), 2))
        p.drawRoundedRect(ox, oy, side, side, 12, 12)
        # guide cross
        p.setPen(QPen(QColor("#D9C7AE"), 1, Qt.DashLine))
        p.drawLine(ox + side / 2, oy + 8, ox + side / 2, oy + side - 8)
        p.drawLine(ox + 8, oy + side / 2, ox + side - 8, oy + side / 2)

        for i, pts in enumerate(self._polylines):
            if not pts:
                continue
            path = QPainterPath(self._map(pts[0]))
            for pt in pts[1:]:
                path.lineTo(self._map(pt))
            if i < self._done:
                p.setPen(QPen(QColor("#3A2E28"), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPath(path)
            elif self._anim_i == i:
                # partial animation
                n = max(2, int(len(pts) * self._anim_t))
                anim = QPainterPath(self._map(pts[0]))
                for pt in pts[1:n]:
                    anim.lineTo(self._map(pt))
                p.setPen(QPen(QColor(T.SEAL), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPath(anim)
            elif self._guide and (not self._write_mode or i == self._done):
                color = QColor(T.SEAL if i == self._done and self._write_mode else "#C4B19A")
                width = 4 if i == self._done and self._write_mode else 2
                p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPath(path)

        # user ink
        p.setPen(QPen(QColor("#1A1520"), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for stroke in self._user_strokes:
            if len(stroke) < 2:
                continue
            path = QPainterPath(stroke[0])
            for pt in stroke[1:]:
                path.lineTo(pt)
            p.drawPath(path)
        if len(self._drawing) >= 2:
            path = QPainterPath(self._drawing[0])
            for pt in self._drawing[1:]:
                path.lineTo(pt)
            p.drawPath(path)
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self._write_mode or event.button() != Qt.LeftButton:
            return
        self._drawing = [event.position()]

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._drawing:
            return
        self._drawing.append(event.position())
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if not self._drawing or event.button() != Qt.LeftButton:
            return
        drawn = [self._unmap(pt) for pt in self._drawing]
        self._user_strokes.append(list(self._drawing))
        self._drawing = []
        if self._done >= len(self._polylines):
            self.update()
            return
        target = self._polylines[self._done]
        judgement = S.judge_stroke(drawn, target)
        if judgement.ok:
            self._done += 1
            self.stroke_judged.emit(True, "")
            if self._done >= len(self._polylines):
                self.character_done.emit(True)
        else:
            # keep the ink briefly but don't advance
            self.stroke_judged.emit(False, judgement.reason)
            if len(self._user_strokes) > self._done:
                self._user_strokes.pop()
        self.update()
