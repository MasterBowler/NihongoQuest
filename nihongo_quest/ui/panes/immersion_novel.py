"""Immersion · Novel — text / EPUB reader + clickable dictionary."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from nihongo_quest.core.immersion.epub import EpubChapter, load_epub
from nihongo_quest.core.immersion.textload import load_text_file, split_paragraphs
from nihongo_quest.core.immersion.tokenize import LexiconMatcher
from nihongo_quest.ui import theme as T
from nihongo_quest.ui.panes.immersion_shared import (
    TranslateWorker, romaji_from_line, save_immersion_phrase,
)
from nihongo_quest.ui.services import AppServices
from nihongo_quest.ui.widgets.clickable_japanese import ClickableJapanese


class _LoadWorker(QThread):
    finished_ok = Signal(object, object)  # chapters: list[EpubChapter] | list[str]-as-one, source name
    finished_err = Signal(str)

    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self.path = path

    def run(self) -> None:
        try:
            suffix = self.path.suffix.lower()
            if suffix == ".epub":
                chapters = load_epub(self.path)
                if not chapters:
                    raise ValueError("EPUB had no readable chapters.")
                self.finished_ok.emit(chapters, self.path.name)
            else:
                text = load_text_file(self.path)
                paras = split_paragraphs(text)
                if not paras:
                    raise ValueError("File is empty.")
                chapters = [EpubChapter(title=self.path.stem, paragraphs=paras)]
                self.finished_ok.emit(chapters, self.path.name)
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))


class NovelMode(QWidget):
    def __init__(self, services: AppServices, matcher: LexiconMatcher, parent=None) -> None:
        super().__init__(parent)
        self.svc = services
        self._matcher = matcher
        self._chapters: list[EpubChapter] = []
        self._chapter_i = 0
        self._para_i = 0
        self._source_name = ""
        self._jp = ""
        self._selection = ""
        self._load_worker: _LoadWorker | None = None
        self._translate_worker: TranslateWorker | None = None
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        tools = QHBoxLayout()
        self.open_btn = QPushButton("Open text / EPUB…")
        self.open_btn.setObjectName("Primary")
        self.open_btn.clicked.connect(self._open)
        tools.addWidget(self.open_btn)
        tools.addWidget(QLabel("Chapter"))
        self.chapter_box = QComboBox()
        self.chapter_box.currentIndexChanged.connect(self._on_chapter_changed)
        tools.addWidget(self.chapter_box, 1)
        self.prev_btn = QPushButton("◀ Prev")
        self.prev_btn.clicked.connect(lambda: self._goto_para(self._para_i - 1))
        tools.addWidget(self.prev_btn)
        self.next_btn = QPushButton("Next ▶")
        self.next_btn.clicked.connect(lambda: self._goto_para(self._para_i + 1))
        tools.addWidget(self.next_btn)
        self.pos_lab = QLabel("No book")
        self.pos_lab.setStyleSheet(f"color:{T.FOG_DIM};")
        tools.addWidget(self.pos_lab)
        root.addLayout(tools)

        self.status = QLabel("Open a .txt / .md / .epub light novel. Click words to look them up.")
        self.status.setStyleSheet(f"color:{T.FOG_DIM};")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.jp_view = ClickableJapanese()
        self.jp_view.set_lexicon(matcher._forms, matcher._max_len)
        self.jp_view.setMinimumHeight(180)
        self.jp_view.word_clicked.connect(self._on_word)
        self.jp_view.phrase_selected.connect(self._on_phrase)
        root.addWidget(self.jp_view, 2)

        self.romaji_lab = QLabel()
        self.romaji_lab.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.romaji_lab.setWordWrap(True)
        self.romaji_lab.setStyleSheet(f"color:{T.GOLD_SOFT}; font-size:14px;")
        root.addWidget(self.romaji_lab)

        self.en_lab = QLabel()
        self.en_lab.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.en_lab.setWordWrap(True)
        self.en_lab.setStyleSheet(f"color:{T.FOG}; font-size:15px;")
        root.addWidget(self.en_lab)

        actions = QHBoxLayout()
        self.save_btn = QPushButton("Save phrase")
        self.save_btn.setObjectName("Primary")
        self.save_btn.clicked.connect(self._save)
        actions.addWidget(self.save_btn)
        self.speak_btn = QPushButton("♪")
        self.speak_btn.setFixedWidth(48)
        self.speak_btn.clicked.connect(self._speak)
        actions.addWidget(self.speak_btn)
        self.translate_btn = QPushButton("Translate paragraph")
        self.translate_btn.clicked.connect(self._translate)
        actions.addWidget(self.translate_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        QShortcut(QKeySequence(Qt.Key_Left), self, lambda: self._goto_para(self._para_i - 1))
        QShortcut(QKeySequence(Qt.Key_Right), self, lambda: self._goto_para(self._para_i + 1))
        self._sync_nav()

    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open novel",
            "",
            "Novels (*.txt *.md *.epub);;Text (*.txt *.md);;EPUB (*.epub);;All files (*.*)",
        )
        if path:
            self._load_path(Path(path))

    def _load_path(self, path: Path) -> None:
        if self._load_worker and self._load_worker.isRunning():
            return
        self.status.setText(f"Loading {path.name}…")
        self._load_worker = _LoadWorker(path, self)
        self._load_worker.finished_ok.connect(self._on_loaded)
        self._load_worker.finished_err.connect(self._on_load_fail)
        self._load_worker.start()

    def _on_loaded(self, chapters: object, name: object) -> None:
        self._chapters = list(chapters)  # type: ignore[arg-type]
        self._source_name = str(name)
        self.chapter_box.blockSignals(True)
        self.chapter_box.clear()
        for i, ch in enumerate(self._chapters):
            label = ch.title.strip() or f"Chapter {i + 1}"
            self.chapter_box.addItem(f"{i + 1}. {label[:48]}", i)
        self.chapter_box.blockSignals(False)
        self._chapter_i = 0
        self._para_i = 0
        if self.chapter_box.count():
            self.chapter_box.setCurrentIndex(0)
        self._show_current()
        self.status.setText(
            f"Loaded {self._source_name} · {len(self._chapters)} chapter(s). "
            "← → to move through paragraphs."
        )

    def _on_load_fail(self, message: str) -> None:
        self.status.setText("Load failed.")
        QMessageBox.warning(self, "Open novel", message)

    def _on_chapter_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._chapters):
            return
        self._chapter_i = index
        self._para_i = 0
        self._show_current()

    def _goto_para(self, index: int) -> None:
        if not self._chapters:
            return
        ch = self._chapters[self._chapter_i]
        n = len(ch.paragraphs)
        if n == 0:
            return
        if index < 0:
            if self._chapter_i > 0:
                self._chapter_i -= 1
                self.chapter_box.blockSignals(True)
                self.chapter_box.setCurrentIndex(self._chapter_i)
                self.chapter_box.blockSignals(False)
                self._para_i = len(self._chapters[self._chapter_i].paragraphs) - 1
                self._show_current()
            return
        if index >= n:
            if self._chapter_i + 1 < len(self._chapters):
                self._chapter_i += 1
                self.chapter_box.blockSignals(True)
                self.chapter_box.setCurrentIndex(self._chapter_i)
                self.chapter_box.blockSignals(False)
                self._para_i = 0
                self._show_current()
            return
        self._para_i = index
        self._show_current()

    def _show_current(self) -> None:
        if not self._chapters:
            self.jp_view.clear_text()
            self.romaji_lab.clear()
            self.en_lab.clear()
            self.pos_lab.setText("No book")
            self._sync_nav()
            return
        ch = self._chapters[self._chapter_i]
        paras = ch.paragraphs
        if not paras:
            return
        self._para_i = max(0, min(self._para_i, len(paras) - 1))
        self._jp = paras[self._para_i]
        self._selection = self._jp
        self.jp_view.set_text(self._jp, align="left", font_pt=20)
        self.romaji_lab.setText(romaji_from_line(self._jp, self._matcher))
        self.en_lab.clear()
        self.pos_lab.setText(
            f"Ch {self._chapter_i + 1}/{len(self._chapters)} · "
            f"¶ {self._para_i + 1}/{len(paras)}"
        )
        self._sync_nav()

    def _sync_nav(self) -> None:
        has = bool(self._chapters)
        self.prev_btn.setEnabled(has)
        self.next_btn.setEnabled(has)
        self.chapter_box.setEnabled(has and len(self._chapters) > 1)

    def _on_word(self, word) -> None:
        if word is not None:
            self.svc.select_word(word)
            self._selection = word.word

    def _on_phrase(self, text: str) -> None:
        self._selection = text
        hit = self._matcher.lookup(text)
        if hit is not None:
            self.svc.select_word(hit)

    def _save(self) -> None:
        jp = (self.jp_view.selected_phrase() or self._selection or self._jp).strip()
        src = self._source_name or "novel"
        save_immersion_phrase(
            self.svc,
            jp=jp,
            en=self.en_lab.text(),
            source=f"novel:{src}#c{self._chapter_i + 1}p{self._para_i + 1}",
            matcher=self._matcher,
            parent=self,
        )

    def _speak(self) -> None:
        text = (self._selection or self._jp).strip()
        if text:
            # Speak a shorter slice for long paragraphs.
            self.svc.speak_text(text[:120])

    def _translate(self) -> None:
        text = self._jp.strip()
        if not text:
            self.svc.toast.emit("No paragraph to translate.")
            return
        if self._translate_worker and self._translate_worker.isRunning():
            return
        prefer_lm = bool(self.svc.progress.setting("lmstudio_enabled"))
        self.status.setText("Translating…")
        self._translate_worker = TranslateWorker(
            text,
            prefer_lm=prefer_lm,
            lm_url=str(self.svc.progress.setting("lmstudio_url") or "http://127.0.0.1:1234/v1"),
            lm_model=str(self.svc.progress.setting("lmstudio_model") or ""),
            parent=self,
        )
        self._translate_worker.finished_ok.connect(self._on_translated)
        self._translate_worker.finished_err.connect(self._on_translate_fail)
        self._translate_worker.start()

    def _on_translated(self, en: str) -> None:
        self.en_lab.setText(en)
        self.status.setText("Translation filled (draft).")

    def _on_translate_fail(self, message: str) -> None:
        self.status.setText("Translation failed.")
        QMessageBox.warning(self, "Translate", message)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime and mime.hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if not mime or not mime.hasUrls():
            return
        for url in mime.urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.suffix.lower() in {".txt", ".md", ".epub"}:
                    self._load_path(p)
                    event.acceptProposedAction()
                    return
