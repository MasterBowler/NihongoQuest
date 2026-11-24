"""Clickable English line — for Immersion EN softsubs → EN→RO lookups."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import QTextBrowser

from nihongo_quest.ui import theme as T

# Keep apostrophes inside words (don't, it's); strip other punctuation as separate tokens.
_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|[^\sA-Za-z]+|\s+")


def tokenize_english(text: str) -> list[str]:
    return [m.group(0) for m in _TOKEN.finditer(text or "")]


def is_english_word(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z]+(?:'[A-Za-z]+)?", token or ""))


class ClickableEnglish(QTextBrowser):
    """Renders an English string as clickable word spans."""

    word_clicked = Signal(str)       # single word
    phrase_selected = Signal(str)    # drag-selected text

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setMinimumHeight(48)
        self.setStyleSheet(
            f"QTextBrowser {{ background:transparent; color:{T.FOG}; "
            f"border:none; padding:4px; }}"
        )
        font = QFont("Zen Maru Gothic", 15)
        self.setFont(font)
        self._tokens: list[str] = []
        self._plain = ""
        self.anchorClicked.connect(self._on_anchor)

    def set_text(self, text: str, *, align: str = "center", font_pt: int = 15) -> None:
        self._plain = text or ""
        self._tokens = tokenize_english(self._plain)
        parts: list[str] = []
        for i, tok in enumerate(self._tokens):
            esc = (
                tok.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\n", "<br/>")
            )
            if is_english_word(tok):
                parts.append(
                    f'<a href="en:{i}" style="color:{T.FOG}; text-decoration:none; '
                    f'border-bottom:1px solid #5A7A9A;">{esc}</a>'
                )
            else:
                parts.append(f'<span style="color:{T.FOG};">{esc}</span>')
        align = align if align in {"center", "left", "right"} else "center"
        self.setHtml(
            f'<div style="font-size:{font_pt}pt; line-height:1.45; text-align:{align};">'
            f'{"".join(parts)}</div>'
        )

    def clear_text(self) -> None:
        self._tokens = []
        self._plain = ""
        self.clear()

    def text(self) -> str:
        return self._plain

    def selected_phrase(self) -> str:
        return self.textCursor().selectedText().replace("\u2029", "\n").strip()

    def _on_anchor(self, url) -> None:
        href = url.toString()
        if not href.startswith("en:"):
            return
        try:
            idx = int(href.split(":", 1)[1])
        except ValueError:
            return
        if 0 <= idx < len(self._tokens) and is_english_word(self._tokens[idx]):
            self.word_clicked.emit(self._tokens[idx])

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton:
            return
        selected = self.selected_phrase()
        if len(selected) >= 2:
            self.phrase_selected.emit(selected)
