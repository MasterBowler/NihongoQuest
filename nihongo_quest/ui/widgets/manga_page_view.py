"""Manga page image with clickable OCR region overlays and drag-to-crop."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from nihongo_quest.ui import theme as T

try:
    from nihongo_quest.core.immersion.manga_ocr import MangaBlock as MangaBlock
except ImportError:
    @dataclass(frozen=True, slots=True)
    class MangaBlock:
        """OCR region in original image pixel space (compatible with manga_ocr)."""

        x0: float
        y0: float
        x1: float
        y1: float
        text: str = ""
        lines: tuple[str, ...] = field(default_factory=tuple)
        vertical: bool = False


@runtime_checkable
class MangaBlockLike(Protocol):
    """Duck type for OCR blocks — any object with image-space box + text fields."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    lines: tuple[str, ...] | list[str]
    vertical: bool


_DRAG_THRESHOLD_PX = 5


def _block_rect(block: MangaBlockLike) -> QRectF:
    return QRectF(
        float(block.x0),
        float(block.y0),
        max(0.0, float(block.x1) - float(block.x0)),
        max(0.0, float(block.y1) - float(block.y0)),
    )


def _contains_xy(block: MangaBlockLike, x: float, y: float) -> bool:
    x0, x1 = sorted((float(block.x0), float(block.x1)))
    y0, y1 = sorted((float(block.y0), float(block.y1)))
    return x0 <= x <= x1 and y0 <= y <= y1


class MangaPageView(QWidget):
    """Fitted page image with translucent OCR hit regions.

    Coordinates
    -----------
    Blocks and crop rects use **original image pixel space** (top-left origin).
    The pixmap is drawn keep-aspect centered in the widget; mouse events are
    mapped through :meth:`widget_to_image` / :meth:`image_to_widget`.
    """

    region_activated = Signal(object)  # MangaBlockLike
    crop_requested = Signal(QRect)  # image-space inclusive pixel rect

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(120, 120)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)

        self._pix = QPixmap()
        self._blocks: list[MangaBlockLike] = []
        self._hover_index = -1
        self._selected_index = -1
        self._outlines_visible = True

        self._press_widget: QPoint | None = None
        self._press_image: QPointF | None = None
        self._rubber_widget: QRect | None = None
        self._dragging = False

    # -- public API ----------------------------------------------------------

    def set_page(self, pixmap: QPixmap | None) -> None:
        """Set the page image (clears selection / hover; keeps blocks)."""
        self._pix = QPixmap() if pixmap is None or pixmap.isNull() else QPixmap(pixmap)
        self._hover_index = -1
        self._selected_index = -1
        self._clear_drag()
        self.update()

    def page(self) -> QPixmap:
        return self._pix

    def set_blocks(self, blocks: Sequence[MangaBlockLike] | None) -> None:
        """Replace OCR hit regions. Boxes must be in image pixel space."""
        self._blocks = list(blocks or ())
        self._hover_index = -1
        if self._selected_index >= len(self._blocks):
            self._selected_index = -1
        self.update()

    def blocks(self) -> list[MangaBlockLike]:
        return list(self._blocks)

    def set_selected_index(self, index: int) -> None:
        if index < 0 or index >= len(self._blocks):
            self._selected_index = -1
        else:
            self._selected_index = index
        self.update()

    def selected_index(self) -> int:
        return self._selected_index

    def selected_block(self) -> MangaBlockLike | None:
        i = self._selected_index
        if 0 <= i < len(self._blocks):
            return self._blocks[i]
        return None

    def set_outlines_visible(self, visible: bool) -> None:
        """Toggle painted box outlines; hit testing stays active either way."""
        visible = bool(visible)
        if visible == self._outlines_visible:
            return
        self._outlines_visible = visible
        self.update()

    def outlines_visible(self) -> bool:
        return self._outlines_visible

    def clear_selection(self) -> None:
        self._selected_index = -1
        self.update()

    # -- fit / coordinate mapping --------------------------------------------

    def fit_rect(self) -> QRectF:
        """Widget-space rectangle where the fitted image is drawn (may be empty)."""
        if self._pix.isNull():
            return QRectF()
        iw, ih = self._pix.width(), self._pix.height()
        if iw <= 0 or ih <= 0:
            return QRectF()
        ww, wh = float(self.width()), float(self.height())
        scale = min(ww / iw, wh / ih)
        fw, fh = iw * scale, ih * scale
        ox = (ww - fw) / 2.0
        oy = (wh - fh) / 2.0
        return QRectF(ox, oy, fw, fh)

    def fit_scale(self) -> float:
        """Uniform scale factor from image pixels → widget pixels (0 if no page)."""
        if self._pix.isNull():
            return 0.0
        iw, ih = self._pix.width(), self._pix.height()
        if iw <= 0 or ih <= 0:
            return 0.0
        return min(self.width() / iw, self.height() / ih)

    def widget_to_image(self, pos: QPoint | QPointF) -> QPointF | None:
        """Map widget coords → image pixel coords, or None if outside the fitted image."""
        fr = self.fit_rect()
        if fr.isEmpty():
            return None
        x = float(pos.x()) if hasattr(pos, "x") else float(pos[0])
        y = float(pos.y()) if hasattr(pos, "y") else float(pos[1])
        if not fr.contains(QPointF(x, y)):
            return None
        scale = self.fit_scale()
        if scale <= 0:
            return None
        return QPointF((x - fr.x()) / scale, (y - fr.y()) / scale)

    def image_to_widget(self, pos: QPoint | QPointF) -> QPointF | None:
        """Map image pixel coords → widget coords, or None if no page."""
        fr = self.fit_rect()
        if fr.isEmpty():
            return None
        scale = self.fit_scale()
        if scale <= 0:
            return None
        x = float(pos.x()) if hasattr(pos, "x") else float(pos[0])
        y = float(pos.y()) if hasattr(pos, "y") else float(pos[1])
        return QPointF(fr.x() + x * scale, fr.y() + y * scale)

    def image_rect_to_widget(self, rect: QRect | QRectF) -> QRectF:
        """Map an image-space rect to widget space (empty if no page)."""
        tl = self.image_to_widget(QPointF(rect.left(), rect.top()))
        br = self.image_to_widget(QPointF(rect.right(), rect.bottom()))
        if tl is None or br is None:
            return QRectF()
        return QRectF(tl, br).normalized()

    # -- painting ------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(T.INK_DEEP))

        fr = self.fit_rect()
        if not self._pix.isNull() and not fr.isEmpty():
            p.drawPixmap(fr.toRect(), self._pix)

            if self._outlines_visible and self._blocks:
                for i, block in enumerate(self._blocks):
                    wr = self.image_rect_to_widget(_block_rect(block))
                    if wr.isEmpty():
                        continue
                    self._paint_hit_rect(p, wr, i)

        if self._rubber_widget is not None and not self._rubber_widget.isNull():
            band = self._rubber_widget.normalized()
            fill = QColor(T.SKY)
            fill.setAlpha(40)
            p.setBrush(fill)
            p.setPen(QPen(QColor(T.SKY), 1, Qt.DashLine))
            p.drawRect(band)

    def _paint_hit_rect(self, p: QPainter, wr: QRectF, index: int) -> None:
        selected = index == self._selected_index
        hovered = index == self._hover_index
        if selected:
            fill = QColor(T.GOLD)
            fill.setAlpha(55)
            border = QColor(T.GOLD_SOFT)
            width = 2.0
        elif hovered:
            fill = QColor(T.SKY)
            fill.setAlpha(45)
            border = QColor(T.SKY)
            width = 1.5
        else:
            fill = QColor(T.SAKURA)
            fill.setAlpha(28)
            border = QColor(T.FOG_DIM)
            border.setAlpha(160)
            width = 1.0
        p.setBrush(fill)
        p.setPen(QPen(border, width))
        p.drawRect(wr)

    # -- hit testing ---------------------------------------------------------

    def _block_at_image(self, ix: float, iy: float) -> int:
        """Return index of the smallest block containing (ix, iy), or -1."""
        best = -1
        best_area = float("inf")
        for i, block in enumerate(self._blocks):
            if not _contains_xy(block, ix, iy):
                continue
            r = _block_rect(block)
            area = r.width() * r.height()
            if area < best_area:
                best_area = area
                best = i
        return best

    def _clear_drag(self) -> None:
        self._press_widget = None
        self._press_image = None
        self._rubber_widget = None
        self._dragging = False

    # -- mouse ---------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position().toPoint()
        img = self.widget_to_image(pos)
        self._press_widget = QPoint(pos)
        self._press_image = img
        self._rubber_widget = None
        self._dragging = False
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()

        if self._press_widget is not None and (event.buttons() & Qt.LeftButton):
            delta = pos - self._press_widget
            if abs(delta.x()) >= _DRAG_THRESHOLD_PX or abs(delta.y()) >= _DRAG_THRESHOLD_PX:
                self._dragging = True
                self._rubber_widget = QRect(self._press_widget, pos).normalized()
                self.update()
            event.accept()
            return

        img = self.widget_to_image(pos)
        new_hover = -1 if img is None else self._block_at_image(img.x(), img.y())
        if new_hover != self._hover_index:
            self._hover_index = new_hover
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return
        pos = event.position().toPoint()
        was_dragging = self._dragging
        press_img = self._press_image
        rubber = self._rubber_widget
        self._clear_drag()

        if was_dragging and rubber is not None:
            tl = self.widget_to_image(rubber.topLeft())
            br = self.widget_to_image(rubber.bottomRight())
            # Clamp corners that fell outside the fitted image to the image edges.
            fr = self.fit_rect()
            scale = self.fit_scale()
            if not fr.isEmpty() and scale > 0:
                def _clamp_widget_to_image(wp: QPoint) -> QPointF:
                    mapped = self.widget_to_image(wp)
                    if mapped is not None:
                        return mapped
                    cx = min(max(float(wp.x()), fr.left()), fr.right())
                    cy = min(max(float(wp.y()), fr.top()), fr.bottom())
                    return QPointF((cx - fr.x()) / scale, (cy - fr.y()) / scale)

                a = tl if tl is not None else _clamp_widget_to_image(rubber.topLeft())
                b = br if br is not None else _clamp_widget_to_image(rubber.bottomRight())
                if self._pix.isNull():
                    self.update()
                    event.accept()
                    return
                x0 = int(max(0, min(a.x(), b.x())))
                y0 = int(max(0, min(a.y(), b.y())))
                x1 = int(min(self._pix.width(), max(a.x(), b.x())))
                y1 = int(min(self._pix.height(), max(a.y(), b.y())))
                if x1 > x0 and y1 > y0:
                    self.crop_requested.emit(QRect(x0, y0, x1 - x0, y1 - y0))
            self.update()
            event.accept()
            return

        # Click: activate region under cursor (or press point).
        img = self.widget_to_image(pos) or press_img
        if img is not None:
            idx = self._block_at_image(img.x(), img.y())
            if idx >= 0:
                self._selected_index = idx
                self.update()
                self.region_activated.emit(self._blocks[idx])
            else:
                self.update()
        else:
            self.update()
        event.accept()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover_index >= 0:
            self._hover_index = -1
            self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.update()
