"""Light smoke: MangaMode imports and constructs without loading OCR models."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeServices(QObject):
    toast = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.progress = SimpleNamespace(setting=lambda _k: None)


def test_manga_mode_importable() -> None:
    from nihongo_quest.ui.panes.immersion_manga import MangaMode

    assert MangaMode is not None


def test_manga_mode_constructs_without_models(qapp) -> None:
    # Ensure availability check does not pull models; construct UI only.
    with patch(
        "nihongo_quest.ui.panes.immersion_manga.manga_ocr_available",
        return_value=False,
    ):
        from nihongo_quest.ui.panes.immersion_manga import MangaMode
        from nihongo_quest.ui.widgets.manga_page_view import MangaPageView

        matcher = SimpleNamespace(_forms={}, _max_len=1)
        mode = MangaMode(_FakeServices(), matcher)
        assert isinstance(mode.page_view, MangaPageView)
        assert mode.page_view.blocks() == []
        status = mode.status.text().lower()
        assert "not installed" in status or "manga ocr" in status
        assert mode.ocr_btn is not None
        mode.close()
        mode.deleteLater()


def test_manga_mode_status_when_available(qapp) -> None:
    with patch(
        "nihongo_quest.ui.panes.immersion_manga.manga_ocr_available",
        return_value=True,
    ):
        from nihongo_quest.ui.panes.immersion_manga import MangaMode

        matcher = SimpleNamespace(_forms={}, _max_len=1)
        mode = MangaMode(_FakeServices(), matcher)
        assert "ready" in mode.status.text().lower()
        mode.close()
        mode.deleteLater()
