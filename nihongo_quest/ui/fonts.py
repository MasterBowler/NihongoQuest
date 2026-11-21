"""Load the bundled Japanese display fonts into the Qt font database."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase

from nihongo_quest.paths import FONTS

_FILES = (
    "DelaGothicOne-Regular.ttf",
    "DotGothic16-Regular.ttf",
    "KleeOne-SemiBold.ttf",
    "ZenMaruGothic-Medium.ttf",
    "ZenMaruGothic-Bold.ttf",
    "ZenMaruGothic-Black.ttf",
)


def load_fonts(folder: Path | None = None) -> list[str]:
    folder = folder or FONTS
    loaded: list[str] = []
    for name in _FILES:
        path = folder / name
        if not path.exists():
            continue
        fid = QFontDatabase.addApplicationFont(str(path))
        if fid >= 0:
            loaded.extend(QFontDatabase.applicationFontFamilies(fid))
    return loaded
