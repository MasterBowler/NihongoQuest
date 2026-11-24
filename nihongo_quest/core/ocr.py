"""Japanese OCR via Windows.Media.Ocr (needs the Japanese OCR language pack).

Subtitle-style screenshots often include pink furigana above the line. Feeding
that straight to OCR makes Windows mix the two layers (e.g. 録音 → 録者, plus a
stray 「ほん」 line). We preprocess to keep bright white glyph pixels, upscale,
then pick the tallest text line by bounding box — the same engine Snipping Tool
uses, with layout-aware cleanup on top.
"""
from __future__ import annotations

import asyncio
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage


class OcrError(RuntimeError):
    pass


_CJK_SPACE = re.compile(
    r"(?<=[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff])\s+(?=[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff])"
)
_HAS_KANJI = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_HAS_KANA = re.compile(r"[\u3040-\u30ff]")
_MOSTLY_KANA = re.compile(r"^[\u3040-\u30ffー・\s\-]+$")


@dataclass(frozen=True)
class OcrLine:
    text: str
    y: float
    height: float
    width: float


@dataclass
class OcrResult:
    text: str
    reading: str = ""
    lines: list[OcrLine] = field(default_factory=list)
    note: str = ""


def tidy_ocr_text(text: str) -> str:
    """Collapse the spaces Windows OCR inserts between Japanese characters."""
    text = (text or "").replace("\r\n", "\n").strip()
    text = _CJK_SPACE.sub("", text)
    # Also drop leftover spaces between any CJK-ish runs.
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" ", "") if _HAS_KANA.search(text) or _HAS_KANJI.search(text) else text
    return text


def _is_pink_furigana(c: QColor) -> bool:
    r, g, b = c.red(), c.green(), c.blue()
    if r < 140 or b < 120:
        return False
    # Saturated pink / magenta used for ruby text.
    if (r - g) > 15 and b > g - 10 and g < 220:
        return True
    # Soft pink-tinted outline near furigana.
    if r > 180 and b > 160 and g > 150 and (r - g) > 8 and (b - g) > 5:
        return True
    return False


def _is_main_glyph(c: QColor) -> bool:
    """Near-white subtitle ink (not pink furigana)."""
    r, g, b = c.red(), c.green(), c.blue()
    if _is_pink_furigana(c):
        return False
    if min(r, g, b) > 195 and max(r, g, b) - min(r, g, b) < 40:
        return True
    if min(r, g, b) > 175 and abs(r - g) < 28 and abs(g - b) < 28 and abs(r - b) < 28:
        return True
    return False


def preprocess_subtitle(image: QImage, *, scale: float = 2.0) -> QImage:
    """Isolate white main-text glyphs and upscale for cleaner OCR."""
    if image.isNull():
        return image
    mask = QImage(image.size(), QImage.Format_RGB32)
    mask.fill(QColor(28, 32, 38))
    for y in range(image.height()):
        for x in range(image.width()):
            if _is_main_glyph(QColor(image.pixel(x, y))):
                mask.setPixelColor(x, y, QColor(255, 255, 255))
    if scale != 1.0:
        w = max(1, int(mask.width() * scale))
        h = max(1, int(mask.height() * scale))
        mask = mask.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        # Re-threshold after smooth scale so glyphs stay crisp for OCR.
        crisp = QImage(mask.size(), QImage.Format_RGB32)
        crisp.fill(QColor(28, 32, 38))
        for y in range(mask.height()):
            for x in range(mask.width()):
                c = QColor(mask.pixel(x, y))
                if c.red() > 140:
                    crisp.setPixelColor(x, y, QColor(255, 255, 255))
        return crisp
    return mask


def _score_main_line(line: OcrLine) -> tuple:
    """Prefer the real dialogue line over tiny furigana crumbs."""
    t = line.text
    kanji = len(_HAS_KANJI.findall(t))
    kana = len(_HAS_KANA.findall(t))
    return (line.height, kanji * 3 + kana + len(t), -line.y)


def select_main_text(lines: list[OcrLine]) -> str:
    usable = [ln for ln in lines if ln.text and (len(ln.text) >= 4 or _HAS_KANJI.search(ln.text))]
    if not usable:
        usable = [ln for ln in lines if ln.text]
    if not usable:
        return ""
    best = max(usable, key=_score_main_line)
    # Merge other similarly tall lines on the same band (multi-line subs).
    band = [ln for ln in usable if abs(ln.height - best.height) <= best.height * 0.35
            and abs(ln.y - best.y) <= best.height * 1.2]
    band.sort(key=lambda ln: ln.y)
    return "\n".join(ln.text for ln in band)


def select_furigana_reading(lines: list[OcrLine], main: str) -> str:
    """Best-effort ruby text from shorter lines sitting above the main line."""
    if not lines or not main:
        return ""
    main_lines = [ln for ln in lines if ln.text in main.split("\n")]
    if not main_lines:
        return ""
    top = min(ln.y for ln in main_lines)
    main_h = max(ln.height for ln in main_lines)
    rubies = []
    for ln in lines:
        if ln.height >= main_h * 0.7:
            continue
        if ln.y >= top - 1:
            continue
        if not _MOSTLY_KANA.match(ln.text.replace("・", "")):
            continue
        if len(ln.text) < 1:
            continue
        rubies.append(ln)
    rubies.sort(key=lambda ln: ln.y)
    # Incomplete ruby (単発「ほん」) is more confusing than helpful for the reading box.
    joined = " ".join(ln.text for ln in rubies).strip()
    if not joined or len(joined) < max(4, len(_HAS_KANJI.findall(main))):
        return ""
    return joined


async def _recognize_file(path: Path, language: str = "ja") -> list[OcrLine]:
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage import FileAccessMode, StorageFile

    engine = OcrEngine.try_create_from_language(Language(language))
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrError(
            "No OCR engine available. Install the Japanese OCR language pack "
            "in Windows Settings → Time & language → Language & region."
        )

    file = await StorageFile.get_file_from_path_async(str(path.resolve()))
    stream = await file.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)
    lines: list[OcrLine] = []
    for line in result.lines:
        words = list(line.words)
        text = tidy_ocr_text(line.text or "")
        if not text:
            continue
        if words:
            y = float(min(w.bounding_rect.y for w in words))
            h = float(max(w.bounding_rect.height for w in words))
            wdt = float(sum(w.bounding_rect.width for w in words))
        else:
            y = h = wdt = 0.0
        lines.append(OcrLine(text=text, y=y, height=h, width=wdt))
    return lines


def _ocr_path(path: Path, language: str = "ja") -> list[OcrLine]:
    return asyncio.run(_recognize_file(path, language))


def ocr_image(image: QImage, language: str = "ja") -> str:
    """Back-compat: return main Japanese text only."""
    return ocr_capture(image, language).text


def ocr_capture(image: QImage, language: str = "ja") -> OcrResult:
    """OCR a screenshot, preferring subtitle main-text over furigana noise."""
    if image.isNull():
        raise OcrError("Empty image")

    prepared = preprocess_subtitle(image, scale=2.0)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        if not prepared.save(str(path), "PNG"):
            raise OcrError("Could not encode image as PNG")
        lines = _ocr_path(path, language)
        text = select_main_text(lines)
        reading = ""
        note = "preprocessed subtitle mask"
        # If preprocessing somehow failed, fall back to raw image + tallest line.
        if not text or len(text) < 3:
            if not image.save(str(path), "PNG"):
                raise OcrError("Could not encode image as PNG")
            raw_lines = _ocr_path(path, language)
            text = select_main_text(raw_lines)
            reading = select_furigana_reading(raw_lines, text)
            lines = raw_lines
            note = "raw fallback"
        return OcrResult(text=text, reading=reading, lines=lines, note=note)
    finally:
        path.unlink(missing_ok=True)


def join_page_lines(lines: list[OcrLine]) -> str:
    """Top-to-bottom page text (manga / document), not a single subtitle line."""
    usable = [ln for ln in lines if (ln.text or "").strip()]
    usable.sort(key=lambda ln: (ln.y, -ln.height))
    return "\n".join(ln.text.strip() for ln in usable if ln.text.strip())


def preprocess_page(image: QImage, *, scale: float = 2.0) -> QImage:
    """Upscale a page for OCR without subtitle white-mask assumptions."""
    if image.isNull() or scale == 1.0:
        return image
    w = max(1, int(image.width() * scale))
    h = max(1, int(image.height() * scale))
    return image.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def ocr_page(image: QImage, language: str = "ja") -> OcrResult:
    """OCR a manga/document page — keep all lines, not just the tallest."""
    if image.isNull():
        raise OcrError("Empty image")
    prepared = preprocess_page(image, scale=2.0)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        if not prepared.save(str(path), "PNG"):
            raise OcrError("Could not encode image as PNG")
        lines = _ocr_path(path, language)
        text = join_page_lines(lines)
        if not text:
            if not image.save(str(path), "PNG"):
                raise OcrError("Could not encode image as PNG")
            lines = _ocr_path(path, language)
            text = join_page_lines(lines)
        return OcrResult(text=text, reading="", lines=lines, note="page")
    finally:
        path.unlink(missing_ok=True)


def ocr_file(path: Path | str, language: str = "ja") -> str:
    image = QImage(str(path))
    if image.isNull():
        raise OcrError(f"Could not load image: {path}")
    return ocr_image(image, language)


def ocr_available(language: str = "ja") -> bool:
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        return OcrEngine.try_create_from_language(Language(language)) is not None
    except Exception:  # noqa: BLE001
        return False


def translate_ja_to_en(text: str, timeout: float = 8.0) -> str:
    """Best-effort free translation (MyMemory). Returns '' on failure.

    Machine glosses will not match polished video subtitles — treat as a draft.
    """
    from nihongo_quest.core.translate import translate_ja_to_en as _tr

    return _tr(text, timeout=timeout)
