from nihongo_quest.core.ocr import tidy_ocr_text
from nihongo_quest.core.phrases import normalize_jp_input


def test_normalize_romaji_phrase() -> None:
    jp, reading, romaji = normalize_jp_input("konnichiwa")
    assert "こんにちは" in jp.replace(" ", "")
    assert reading
    assert "konnichiwa" in romaji.replace(" ", "")


def test_normalize_keeps_japanese() -> None:
    jp, reading, romaji = normalize_jp_input("お疲れ様です")
    assert jp == "お疲れ様です"


def test_tidy_ocr_spaces() -> None:
    assert tidy_ocr_text("こ ん に ち は") == "こんにちは"
    assert tidy_ocr_text("今日 は いい 天気") == "今日はいい天気"
