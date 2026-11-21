"""Clickable Japanese line with longest-match lexicon tokens."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import QTextBrowser

from nihongo_quest.core.content import Word
from nihongo_quest.core.immersion.tokenize import Token, tokenize_japanese
from nihongo_quest.ui import theme as T


class ClickableJapanese(QTextBrowser):
    """Renders a Japanese string as clickable spans; emits word/phrase selections."""

    word_clicked = Signal(object)   # Word | None
    phrase_selected = Signal(str)   # selected plain text

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setMinimumHeight(64)
        self.setStyleSheet(
            f"QTextBrowser {{ background:{T.WASHI}; color:#2A1E14; border-radius:12px; padding:10px; }}"
        )
        font = QFont("Klee One", 22)
        self.setFont(font)
        self._tokens: list[Token] = []
        self._forms: dict[str, Word] = {}
        self._max_len = 12
        self.anchorClicked.connect(self._on_anchor)

    def set_lexicon(self, forms: dict[str, Word], max_len: int = 12) -> None:
        self._forms = forms
        self._max_len = max_len

    def set_text(self, text: str) -> None:
        text = text or ""
        self._tokens = tokenize_japanese(text, self._forms, self._max_len)
        parts: list[str] = []
        for i, tok in enumerate(self._tokens):
            esc = (
                tok.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\n", "<br/>")
            )
            if tok.word is not None:
                parts.append(
                    f'<a href="tok:{i}" style="color:#1A2438; text-decoration:none; '
                    f'border-bottom:1px solid #C45C4A;">{esc}</a>'
                )
            else:
                parts.append(f'<span style="color:#2A1E14;">{esc}</span>')
        self.setHtml(
            f'<div style="font-size:22pt; line-height:1.55; text-align:center;">{"".join(parts)}</div>'
        )

    def clear_text(self) -> None:
        self._tokens = []
        self.clear()

    def selected_phrase(self) -> str:
        return self.textCursor().selectedText().replace("\u2029", "\n").strip()

    def _on_anchor(self, url) -> None:
        href = url.toString()
        if not href.startswith("tok:"):
            return
        try:
            idx = int(href.split(":", 1)[1])
        except ValueError:
            return
        if 0 <= idx < len(self._tokens):
            self.word_clicked.emit(self._tokens[idx].word)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton:
            return
        selected = self.selected_phrase()
        if len(selected) >= 2:
            self.phrase_selected.emit(selected)
