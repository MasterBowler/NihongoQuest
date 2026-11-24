"""Unit tests for manga OCR helpers — engine is mocked (no model download / GPU)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from nihongo_quest.core.immersion import manga_ocr as mo


def _reset_engine_singletons() -> None:
    mo._page_engine = None
    mo._mocr_singleton = None


def test_blocks_from_mokuro_sort_top_then_right_to_left() -> None:
    # Same y-band: larger x0 (right) should come before smaller x0 (left).
    # Lower y0 comes after higher blocks.
    result = {
        "blocks": [
            {"box": [10, 100, 50, 140], "lines": ["下左"], "vertical": True},
            {"box": [200, 10, 240, 50], "lines": ["上右"], "vertical": True},
            {"box": [80, 10, 120, 50], "lines": ["上左"], "vertical": False},
            {"box": [180, 100, 220, 140], "lines": ["下右"], "vertical": True},
        ]
    }
    blocks = mo._blocks_from_mokuro_result(result)
    assert [b.text for b in blocks] == ["上右", "上左", "下右", "下左"]
    assert blocks[0].vertical is True
    assert blocks[1].vertical is False
    assert blocks[0].lines == ["上右"]


def test_blocks_from_mokuro_empty_page() -> None:
    assert mo._blocks_from_mokuro_result({}) == []
    assert mo._blocks_from_mokuro_result({"blocks": []}) == []
    assert mo._blocks_from_mokuro_result({"blocks": None}) == []


def test_blocks_from_mokuro_skips_bad_box_joins_lines() -> None:
    result = {
        "blocks": [
            {"box": [1, 2], "lines": ["too short"]},
            {"box": [0, 0, 10, 10], "lines": ["一", "", "二", None]},
        ]
    }
    blocks = mo._blocks_from_mokuro_result(result)
    assert len(blocks) == 1
    assert blocks[0].text == "一\n二"
    assert blocks[0].lines == ["一", "二"]


def test_ocr_manga_page_empty_engine_result(tmp_path: Path) -> None:
    _reset_engine_singletons()
    img = tmp_path / "blank.png"
    Image.new("RGB", (32, 48), color=(255, 255, 255)).save(img)

    fake_engine = MagicMock(return_value={"img_width": 32, "img_height": 48, "blocks": []})
    try:
        with patch.object(mo, "_get_page_engine", return_value=fake_engine):
            blocks = mo.ocr_manga_page(img)
        assert blocks == []
        fake_engine.assert_called_once()
        called_path = Path(fake_engine.call_args[0][0])
        assert called_path == img
    finally:
        _reset_engine_singletons()


def test_ocr_manga_page_maps_engine_blocks(tmp_path: Path) -> None:
    _reset_engine_singletons()
    img = tmp_path / "page.png"
    Image.new("RGB", (100, 100), color=(240, 240, 240)).save(img)

    fake_engine = MagicMock(
        return_value={
            "blocks": [
                {"box": [10.0, 20.0, 40.0, 60.0], "lines": ["こんにちは"], "vertical": False},
            ]
        }
    )
    try:
        with patch.object(mo, "_get_page_engine", return_value=fake_engine):
            blocks = mo.ocr_manga_page(img)
        assert len(blocks) == 1
        b = blocks[0]
        assert b.text == "こんにちは"
        assert (b.x0, b.y0, b.x1, b.y1) == (10.0, 20.0, 40.0, 60.0)
    finally:
        _reset_engine_singletons()


def test_ocr_manga_crop_strips_whitespace() -> None:
    _reset_engine_singletons()
    fake_mocr = MagicMock(return_value="  ありがとう  \n")
    pil = Image.new("RGB", (16, 16), color=(0, 0, 0))
    try:
        with patch.object(mo, "_get_mocr", return_value=fake_mocr):
            assert mo.ocr_manga_crop(pil) == "ありがとう"
            fake_mocr.assert_called_once()
            # Empty / None from model → empty string
            fake_mocr.return_value = None
            assert mo.ocr_manga_crop(pil) == ""
            fake_mocr.return_value = "   "
            assert mo.ocr_manga_crop(pil) == ""
    finally:
        _reset_engine_singletons()


def test_manga_ocr_available_false_when_import_fails() -> None:
    import sys

    blocked = {
        "manga_ocr": None,
        "comic_text_detector": None,
        "comic_text_detector.inference": None,
    }
    with patch.dict(sys.modules, blocked):
        assert mo.manga_ocr_available() is False


def test_manga_ocr_available_returns_bool() -> None:
    assert isinstance(mo.manga_ocr_available(), bool)
