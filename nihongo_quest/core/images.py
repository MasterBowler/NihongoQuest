"""Learner-attached meaning illustrations for vocabulary and kanji.

Files live under ``userdata/images/{vocab|kanji}/``. Vocab keys are hashed so
characters like ``:`` stay filesystem-safe; kanji use ``U+XXXX`` code points.
A small JSON index maps item ids → filenames so we can look them up quickly
and leave room for future ComfyUI metadata (prompt, seed, …).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from nihongo_quest.core.progress import KANJI, VOCAB
from nihongo_quest.paths import IMAGES, KANJI_IMAGES, VOCAB_IMAGES

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
INDEX_NAME = "index.json"


class ImageStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or IMAGES
        self.vocab_dir = self.root / "vocab" if root else VOCAB_IMAGES
        self.kanji_dir = self.root / "kanji" if root else KANJI_IMAGES
        self.vocab_dir.mkdir(parents=True, exist_ok=True)
        self.kanji_dir.mkdir(parents=True, exist_ok=True)
        self._index = self._load_index()

    def _index_path(self) -> Path:
        return self.root / INDEX_NAME

    def _load_index(self) -> dict:
        path = self._index_path()
        if not path.exists():
            return {VOCAB: {}, KANJI: {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {VOCAB: {}, KANJI: {}}
        data.setdefault(VOCAB, {})
        data.setdefault(KANJI, {})
        return data

    def _save_index(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path().write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _stem(kind: str, item: str) -> str:
        if kind == KANJI:
            return f"U+{ord(item):04X}"
        return hashlib.sha1(item.encode("utf-8")).hexdigest()[:20]

    def _dir(self, kind: str) -> Path:
        return self.kanji_dir if kind == KANJI else self.vocab_dir

    def path(self, kind: str, item: str) -> Path | None:
        """Absolute path of an attached image, or None."""
        entry = self._index.get(kind, {}).get(item)
        if entry:
            path = self._dir(kind) / entry["file"]
            if path.exists():
                return path
        # Recover from loose files if the index was deleted.
        stem = self._stem(kind, item)
        for path in self._dir(kind).glob(stem + ".*"):
            if path.suffix.lower() in ALLOWED_EXT:
                self._index.setdefault(kind, {})[item] = {
                    "file": path.name,
                    "source": "recovered",
                }
                self._save_index()
                return path
        return None

    def has(self, kind: str, item: str) -> bool:
        return self.path(kind, item) is not None

    def set_image(self, kind: str, item: str, source: Path, *, source_tag: str = "manual") -> Path:
        """Copy ``source`` into the store and register it. Returns the stored path."""
        source = Path(source)
        ext = source.suffix.lower()
        if ext not in ALLOWED_EXT:
            raise ValueError(f"Unsupported image type: {ext}")
        if not source.exists():
            raise FileNotFoundError(source)
        self.clear(kind, item)
        dest = self._dir(kind) / f"{self._stem(kind, item)}{ext}"
        shutil.copy2(source, dest)
        self._index.setdefault(kind, {})[item] = {
            "file": dest.name,
            "source": source_tag,
            "original_name": source.name,
        }
        self._save_index()
        return dest

    def clear(self, kind: str, item: str) -> None:
        entry = self._index.get(kind, {}).pop(item, None)
        stem = self._stem(kind, item)
        for path in self._dir(kind).glob(stem + ".*"):
            path.unlink(missing_ok=True)
        if entry:
            leftover = self._dir(kind) / entry.get("file", "")
            leftover.unlink(missing_ok=True)
        self._save_index()

    def meta(self, kind: str, item: str) -> dict | None:
        return self._index.get(kind, {}).get(item)
