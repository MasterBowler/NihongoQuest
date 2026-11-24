"""Right-rail EN→RO lookup pane (English immersion helper — not the JA lexicon)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from nihongo_quest.core.translate import translate_en_to_ro
from nihongo_quest.ui import theme as T
from nihongo_quest.ui.services import AppServices


class _LookupWorker(QThread):
    finished_ok = Signal(str, str)  # en, ro
    finished_err = Signal(str, str)  # en, message

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self.text = text

    def run(self) -> None:
        try:
            ro = translate_en_to_ro(self.text)
            if not ro:
                self.finished_err.emit(self.text, "No Romanian gloss returned.")
            else:
                self.finished_ok.emit(self.text, ro)
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(self.text, str(exc))


class EnRoPane(QWidget):
    """Dictionary-style rail for English words/phrases → Romanian."""

    def __init__(self, services: AppServices, parent=None) -> None:
        super().__init__(parent)
        self.svc = services
        self._worker: _LookupWorker | None = None
        self._query = ""
        self._context = ""
        self.setObjectName("ContextRail")
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        title = QLabel("EN → RO")
        title.setObjectName("PanelTitle")
        root.addWidget(title)

        hint = QLabel(
            "Click an English word in Immersion Anime softsubs "
            "(or select a phrase) to look it up here."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{T.FOG_DIM}; font-size:12px;")
        root.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 8, 0)
        self.body_layout.setSpacing(10)
        scroll.setWidget(self.body)
        root.addWidget(scroll, 1)

        self.empty = QLabel("No English word selected.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(f"color:{T.FOG_DIM}; padding:40px;")
        self.body_layout.addWidget(self.empty)
        self.body_layout.addStretch(1)

        self.svc.english_changed.connect(self.refresh)

    def refresh(self) -> None:
        en, context = self.svc.selected_english()
        self._query = (en or "").strip()
        self._context = (context or "").strip()
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self._query:
            empty = QLabel("No English word selected.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color:{T.FOG_DIM}; padding:40px;")
            self.body_layout.addWidget(empty)
            self.body_layout.addStretch(1)
            return

        card = QFrame()
        card.setObjectName("Washi")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 16, 16, 16)
        head = QLabel(self._query)
        head.setAlignment(Qt.AlignCenter)
        head.setFont(QFont("Zen Maru Gothic", 28))
        head.setStyleSheet("color:#2A1E14;")
        head.setWordWrap(True)
        lay.addWidget(head)
        self.ro_lab = QLabel("Looking up…")
        self.ro_lab.setAlignment(Qt.AlignCenter)
        self.ro_lab.setWordWrap(True)
        self.ro_lab.setStyleSheet(f"color:{T.GOLD_SOFT}; font-size:18px;")
        lay.addWidget(self.ro_lab)
        self.body_layout.addWidget(card)

        if self._context and self._context.lower() != self._query.lower():
            ctx_title = QLabel("Context")
            ctx_title.setObjectName("PanelTitle")
            self.body_layout.addWidget(ctx_title)
            ctx = QLabel(self._context)
            ctx.setWordWrap(True)
            ctx.setStyleSheet(f"color:{T.FOG}; font-size:13px;")
            self.body_layout.addWidget(ctx)

        note = QLabel("Machine gloss (MyMemory) — treat as a draft, not a dictionary.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{T.FOG_DIM}; font-size:11px;")
        self.body_layout.addWidget(note)

        actions = QHBoxLayout()
        speak = QPushButton("♪ Speak EN")
        speak.clicked.connect(lambda: self.svc.speak_text(self._query))
        actions.addWidget(speak)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._lookup)
        actions.addWidget(refresh)
        actions.addStretch(1)
        self.body_layout.addLayout(actions)
        self.body_layout.addStretch(1)

        self._lookup()

    def _lookup(self) -> None:
        if not self._query:
            return
        if self._worker and self._worker.isRunning():
            return
        self.ro_lab.setText("Looking up…")
        self._worker = _LookupWorker(self._query, self)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.finished_err.connect(self._on_err)
        self._worker.start()

    def _on_ok(self, en: str, ro: str) -> None:
        if en.strip().lower() != self._query.lower():
            return
        self.ro_lab.setText(ro)

    def _on_err(self, en: str, message: str) -> None:
        if en.strip().lower() != self._query.lower():
            return
        self.ro_lab.setText(f"(no gloss)\n{message}")
