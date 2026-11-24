"""Where things live on disk."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _app_root() -> Path:
    # PyInstaller onedir / onefile: bundled data lives under sys._MEIPASS.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def _writable_root() -> Path:
    """Folder next to the .exe when frozen; repo root otherwise."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT = _app_root()
DATA = ROOT / "data"
CONTENT_DB = DATA / "content.db"
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"

# Everything that belongs to the learner (progress, settings, cached audio).
# Override with NIHONGO_QUEST_HOME, e.g. to keep it in a synced folder.
USER = Path(os.environ.get("NIHONGO_QUEST_HOME") or (_writable_root() / "userdata"))
PROGRESS_DB = USER / "progress.db"
AUDIO_CACHE = USER / "audio"
SFX_CACHE = USER / "sfx"
BACKUPS = USER / "backups"
# Meaning illustrations you (or later ComfyUI) attach to words / kanji.
IMAGES = USER / "images"
VOCAB_IMAGES = IMAGES / "vocab"
KANJI_IMAGES = IMAGES / "kanji"
