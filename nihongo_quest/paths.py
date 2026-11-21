"""Where things live on disk."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONTENT_DB = DATA / "content.db"
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"

# Everything that belongs to the learner (progress, settings, cached audio).
# Override with NIHONGO_QUEST_HOME, e.g. to keep it in a synced folder.
USER = Path(os.environ.get("NIHONGO_QUEST_HOME") or ROOT / "userdata")
PROGRESS_DB = USER / "progress.db"
AUDIO_CACHE = USER / "audio"
SFX_CACHE = USER / "sfx"
BACKUPS = USER / "backups"
# Meaning illustrations you (or later ComfyUI) attach to words / kanji.
IMAGES = USER / "images"
VOCAB_IMAGES = IMAGES / "vocab"
KANJI_IMAGES = IMAGES / "kanji"
