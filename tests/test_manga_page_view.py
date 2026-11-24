"""Coordinate mapping tests for MangaPageView fit-scale ↔ image space."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRect, QSize
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from nihongo_quest.core.immersion.manga_ocr import MangaBlock
from nihongo_quest.ui.widgets.manga_page_view import MangaPageView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _solid_pixmap(w: int, h: int) -> QPixmap:
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(200, 200, 200))
    return QPixmap.fromImage(img)


def test_fit_scale_letterbox(qapp) -> None:
    view = MangaPageView()
    view.resize(QSize(400, 200))  # wide widget
    view.set_page(_solid_pixmap(100, 100))  # square image
    # Height-limited: scale = 200/100 = 2.0
    assert view.fit_scale() == pytest.approx(2.0)
    fr = view.fit_rect()
    assert fr.width() == pytest.approx(200.0)
    assert fr.height() == pytest.approx(200.0)
    assert fr.x() == pytest.approx(100.0)  # centered horizontally
    assert fr.y() == pytest.approx(0.0)


def test_fit_scale_pillarbox(qapp) -> None:
    view = MangaPageView()
    view.resize(QSize(200, 400))  # tall widget
    view.set_page(_solid_pixmap(100, 100))
    assert view.fit_scale() == pytest.approx(2.0)
    fr = view.fit_rect()
    assert fr.x() == pytest.approx(0.0)
    assert fr.y() == pytest.approx(100.0)  # centered vertically


def test_widget_image_roundtrip(qapp) -> None:
    view = MangaPageView()
    view.resize(QSize(300, 300))
    view.set_page(_solid_pixmap(150, 100))
    # scale = min(300/150, 300/100) = min(2, 3) = 2
    assert view.fit_scale() == pytest.approx(2.0)
    fr = view.fit_rect()
    # Image (75, 50) → widget
    wp = view.image_to_widget(QPointF(75, 50))
    assert wp is not None
    assert wp.x() == pytest.approx(fr.x() + 75 * 2)
    assert wp.y() == pytest.approx(fr.y() + 50 * 2)
    back = view.widget_to_image(wp)
    assert back is not None
    assert back.x() == pytest.approx(75.0)
    assert back.y() == pytest.approx(50.0)


def test_widget_to_image_outside_returns_none(qapp) -> None:
    view = MangaPageView()
    view.resize(QSize(400, 200))
    view.set_page(_solid_pixmap(100, 100))
    # Letterboxed: fitted image is x=100..300; corners outside
    assert view.widget_to_image(QPoint(10, 100)) is None
    assert view.widget_to_image(QPoint(390, 100)) is None
    # Inside fitted area
    mid = view.widget_to_image(QPoint(200, 100))
    assert mid is not None
    assert mid.x() == pytest.approx(50.0)
    assert mid.y() == pytest.approx(50.0)


def test_empty_page_mapping(qapp) -> None:
    view = MangaPageView()
    view.resize(QSize(200, 200))
    assert view.fit_scale() == 0.0
    assert view.fit_rect().isEmpty()
    assert view.widget_to_image(QPoint(50, 50)) is None
    assert view.image_to_widget(QPointF(10, 10)) is None


def test_image_rect_to_widget(qapp) -> None:
    from PySide6.QtCore import QRectF

    view = MangaPageView()
    view.resize(QSize(200, 200))
    view.set_page(_solid_pixmap(100, 100))
    # QRectF edges are continuous (unlike QRect's inclusive right/bottom).
    wr = view.image_rect_to_widget(QRectF(10, 20, 30, 40))
    assert not wr.isEmpty()
    assert wr.width() == pytest.approx(60.0)  # * scale 2
    assert wr.height() == pytest.approx(80.0)
    # QRect maps via inclusive right/bottom → one pixel short of width*scale
    wr_i = view.image_rect_to_widget(QRect(10, 20, 30, 40))
    assert wr_i.width() == pytest.approx(58.0)
    assert wr_i.height() == pytest.approx(78.0)


def test_set_blocks_and_selection(qapp) -> None:
    view = MangaPageView()
    view.resize(QSize(200, 200))
    view.set_page(_solid_pixmap(100, 100))
    blocks = [
        MangaBlock(10, 10, 40, 40, "あ", lines=["あ"], vertical=False),
        MangaBlock(50, 50, 90, 90, "い", lines=["い"], vertical=True),
    ]
    view.set_blocks(blocks)
    assert len(view.blocks()) == 2
    view.set_selected_index(1)
    assert view.selected_index() == 1
    assert view.selected_block() is not None
    assert view.selected_block().text == "い"
    view.set_selected_index(99)
    assert view.selected_index() == -1
    view.clear_selection()
    assert view.selected_index() == -1
