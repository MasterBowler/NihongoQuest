"""Manga page OCR via the mokuro stack (comic-text-detector + manga-ocr).

Prefers ``mokuro.MangaPageOcr`` when importable; otherwise composes the same
detector + ``MangaOcr`` pair. Models load lazily on first OCR call (CPU by
default; CUDA only if already available). Boxes are in original image pixels.
"""
from __future__ import annotations

import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union

_ImageInput = Union[str, Path, Any]

_engine_lock = threading.Lock()
_page_engine: Any | None = None
_mocr_singleton: Any | None = None


@dataclass
class MangaBlock:
    """One detected text region on a manga page (original image pixel space)."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    lines: list[str] = field(default_factory=list)
    vertical: bool = False


def manga_ocr_available() -> bool:
    """True when manga-ocr and the comic-text-detector stack can be imported."""
    try:
        from manga_ocr import MangaOcr  # noqa: F401
        from comic_text_detector.inference import TextDetector  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _prefer_cpu() -> bool:
    """Force CPU unless CUDA is already available (skip MPS)."""
    try:
        import torch

        return not torch.cuda.is_available()
    except Exception:  # noqa: BLE001
        return True


def _get_page_engine() -> Any:
    """Lazy singleton: mokuro ``MangaPageOcr`` (detector + MangaOcr)."""
    global _page_engine, _mocr_singleton
    if _page_engine is not None:
        return _page_engine
    with _engine_lock:
        if _page_engine is not None:
            return _page_engine
        force_cpu = _prefer_cpu()
        try:
            from mokuro import MangaPageOcr

            engine = MangaPageOcr(force_cpu=force_cpu)
            _page_engine = engine
            _mocr_singleton = engine.mocr
            return engine
        except Exception:  # noqa: BLE001
            engine = _ComposePageEngine(force_cpu=force_cpu)
            _page_engine = engine
            _mocr_singleton = engine.mocr
            return engine


def _get_mocr() -> Any:
    """Lazy MangaOcr singleton (shared with page engine when already loaded)."""
    global _mocr_singleton
    if _mocr_singleton is not None:
        return _mocr_singleton
    with _engine_lock:
        if _mocr_singleton is not None:
            return _mocr_singleton
        # Prefer sharing the page-engine OCR model if page OCR ran first.
        if _page_engine is not None and getattr(_page_engine, "mocr", None) is not None:
            _mocr_singleton = _page_engine.mocr
            return _mocr_singleton
        from manga_ocr import MangaOcr

        _mocr_singleton = MangaOcr(force_cpu=_prefer_cpu())
        return _mocr_singleton


class _ComposePageEngine:
    """Fallback page OCR when ``MangaPageOcr`` cannot be constructed."""

    def __init__(self, force_cpu: bool = True) -> None:
        import torch
        from comic_text_detector.inference import TextDetector
        from manga_ocr import MangaOcr
        from mokuro.cache import cache

        if not force_cpu and torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"
        self.text_detector = TextDetector(
            model_path=cache.comic_text_detector,
            input_size=1024,
            device=device,
            act="leaky",
        )
        self.mocr = MangaOcr(force_cpu=force_cpu)
        self.text_height = 64
        self.max_ratio_vert = 16
        self.max_ratio_hor = 8
        self.anchor_window = 2

    def __call__(self, img_path: str | Path) -> dict[str, Any]:
        """Mimic ``MangaPageOcr.__call__`` result shape when possible."""
        try:
            from mokuro.manga_page_ocr import MangaPageOcr as _M

            # Reuse mokuro's line-chunk OCR path with our loaded models.
            proxy = object.__new__(_M)
            proxy.text_height = self.text_height
            proxy.max_ratio_vert = self.max_ratio_vert
            proxy.max_ratio_hor = self.max_ratio_hor
            proxy.anchor_window = self.anchor_window
            proxy.disable_ocr = False
            proxy.text_detector = self.text_detector
            proxy.mocr = self.mocr
            return _M.__call__(proxy, img_path)
        except Exception:  # noqa: BLE001
            return self._simple_ocr(img_path)

    def _simple_ocr(self, img_path: str | Path) -> dict[str, Any]:
        import cv2
        from PIL import Image

        from mokuro.utils import imread

        img = imread(img_path)
        h, w, *_ = img.shape
        result: dict[str, Any] = {
            "img_width": w,
            "img_height": h,
            "blocks": [],
        }
        _mask, _mask_refined, blk_list = self.text_detector(
            img, refine_mode=1, keep_undetected_mask=True
        )
        for blk in blk_list:
            x0, y0, x1, y1 = (int(v) for v in blk.xyxy)
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(w, x1), min(h, y1)
            crop = img[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            if getattr(blk, "vertical", False):
                crop = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
            rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            text = self.mocr(Image.fromarray(rgb))
            result["blocks"].append(
                {
                    "box": [float(x0), float(y0), float(x1), float(y1)],
                    "vertical": bool(getattr(blk, "vertical", False)),
                    "lines": [text] if text else [],
                }
            )
        return result


def _qimage_to_pil(image: Any):
    from PIL import Image

    w, h = image.width(), image.height()
    image = image.convertToFormat(image.Format.Format_RGBA8888)
    ptr = image.bits()
    if hasattr(ptr, "setsize"):
        ptr.setsize(image.sizeInBytes())
    buf = bytes(ptr)
    return Image.frombytes("RGBA", (w, h), buf).convert("RGB")


def _to_pil(image: _ImageInput):
    from PIL import Image

    if isinstance(image, Image.Image):
        return image.convert("RGB")
    if isinstance(image, (str, Path)):
        return Image.open(image).convert("RGB")
    # QImage duck-type (PySide6 / PyQt)
    if hasattr(image, "width") and hasattr(image, "bits") and hasattr(image, "Format"):
        return _qimage_to_pil(image)
    try:
        import numpy as np

        if isinstance(image, np.ndarray):
            arr = image
            if arr.ndim == 2:
                return Image.fromarray(arr).convert("RGB")
            if arr.shape[2] == 4:
                return Image.fromarray(arr, "RGBA").convert("RGB")
            # Assume BGR (OpenCV) when 3-channel uint8 from detector pipeline
            if arr.shape[2] == 3:
                import cv2

                rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
                return Image.fromarray(rgb)
    except Exception:  # noqa: BLE001
        pass
    raise TypeError(f"Unsupported image type for manga OCR: {type(image)!r}")


def _materialize_path(image: _ImageInput) -> tuple[Path, bool]:
    """Return (path, is_temporary). Paths/str pass through; others write a PNG."""
    if isinstance(image, Path):
        return image, False
    if isinstance(image, str):
        return Path(image), False

    pil = _to_pil(image)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    path = Path(tmp.name)
    tmp.close()
    pil.save(path, format="PNG")
    return path, True


def _blocks_from_mokuro_result(result: dict[str, Any]) -> list[MangaBlock]:
    blocks: list[MangaBlock] = []
    for raw in result.get("blocks") or []:
        box = raw.get("box") or [0, 0, 0, 0]
        if len(box) < 4:
            continue
        x0, y0, x1, y1 = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
        lines = [str(t) for t in (raw.get("lines") or []) if t]
        text = "\n".join(lines)
        blocks.append(
            MangaBlock(
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                text=text,
                lines=lines,
                vertical=bool(raw.get("vertical", False)),
            )
        )
    # Reading order: top-to-bottom, then right-to-left (manga)
    blocks.sort(key=lambda b: (b.y0, -b.x0))
    return blocks


def ocr_manga_page(image: _ImageInput) -> list[MangaBlock]:
    """Detect text regions on a page and OCR each block.

    ``image`` may be a filesystem path, ``PIL.Image``, OpenCV BGR ``ndarray``,
    or ``QImage``. Returned boxes are in the original image's pixel space.
    First call loads detector + recognition models (may download ~400MB+).
    """
    engine = _get_page_engine()
    path, is_temp = _materialize_path(image)
    try:
        result = engine(path)
    finally:
        if is_temp:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return _blocks_from_mokuro_result(result)


def ocr_manga_crop(image: _ImageInput) -> str:
    """Run manga-ocr alone on a user crop (no text detector)."""
    mocr = _get_mocr()
    pil = _to_pil(image)
    text = mocr(pil)
    return (text or "").strip()
