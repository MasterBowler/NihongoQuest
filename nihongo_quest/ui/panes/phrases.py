"""Collect and study custom Japanese phrases (typed or OCR from screenshots)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from nihongo_quest.core import kana as K
from nihongo_quest.core import progress as P
from nihongo_quest.core.ocr import ocr_available, ocr_capture, translate_ja_to_en
from nihongo_quest.core.phrases import Phrase, normalize_jp_input
from nihongo_quest.ui import theme as T
from nihongo_quest.ui.services import AppServices


class _OcrWorker(QThread):
    finished_ok = Signal(str, str, str)   # jp, reading, en
    finished_err = Signal(str)

    def __init__(self, image: QImage, auto_translate: bool, parent=None) -> None:
        super().__init__(parent)
        self.image = image.copy()
        self.auto_translate = auto_translate

    def run(self) -> None:
        try:
            capture = ocr_capture(self.image)
            jp = capture.text
            reading = capture.reading
            en = translate_ja_to_en(jp) if (self.auto_translate and jp) else ""
            self.finished_ok.emit(jp, reading, en)
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))


class PhrasesPane(QWidget):
    open_study = Signal()

    def __init__(self, services: AppServices, parent=None) -> None:
        super().__init__(parent)
        self.svc = services
        self._current_id: str | None = None
        self._ocr_worker: _OcrWorker | None = None
        self._block = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("フレーズ · Phrases")
        title.setObjectName("SectionTitle")
        head.addWidget(title, 1)
        self.study_btn = QPushButton("Study phrases")
        self.study_btn.setObjectName("Primary")
        self.study_btn.clicked.connect(self.open_study.emit)
        head.addWidget(self.study_btn)
        root.addLayout(head)

        hint = QLabel(
            "Type Japanese with IME or romaji, paste a screenshot (Ctrl+V), or drop an image. "
            "OCR uses Windows Japanese OCR (subtitle furigana is filtered when possible)."
            + (" Ready." if ocr_available() else " (Japanese OCR pack not detected.)")
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{T.FOG_DIM};")
        root.addWidget(hint)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # ---- list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search phrases…")
        self.search.textChanged.connect(self.refresh_list)
        ll.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._picked)
        ll.addWidget(self.list, 1)
        self.count_lab = QLabel()
        self.count_lab.setStyleSheet(f"color:{T.FOG_DIM};")
        ll.addWidget(self.count_lab)
        split.addWidget(left)

        # ---- editor
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)

        self.drop = QLabel("Paste or drop a screenshot here for OCR")
        self.drop.setAlignment(Qt.AlignCenter)
        self.drop.setMinimumHeight(88)
        self.drop.setStyleSheet(
            f"background:{T.PANEL}; border:1px dashed #2E3C58; border-radius:12px; color:{T.FOG_DIM};"
        )
        self.drop.setAcceptDrops(True)
        rl.addWidget(self.drop)

        form = QFormLayout()
        form.setSpacing(8)
        self.jp = QPlainTextEdit()
        self.jp.setPlaceholderText("Japanese — IME or romaji (e.g. konnichiwa)")
        self.jp.setFixedHeight(72)
        self.jp.textChanged.connect(self._jp_changed)
        form.addRow("日本語", self.jp)

        self.reading = QLineEdit()
        self.reading.setPlaceholderText("Reading (kana)")
        form.addRow("読み", self.reading)

        self.romaji = QLineEdit()
        self.romaji.setPlaceholderText("Romaji")
        form.addRow("Romaji", self.romaji)

        self.en = QPlainTextEdit()
        self.en.setPlaceholderText("English translation")
        self.en.setFixedHeight(64)
        form.addRow("English", self.en)

        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notes / context (optional)")
        self.notes.setFixedHeight(56)
        form.addRow("Notes", self.notes)
        rl.addLayout(form)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{T.GOLD_SOFT};")
        rl.addWidget(self.status)

        actions = QHBoxLayout()
        self.new_btn = QPushButton("New")
        self.new_btn.clicked.connect(self.clear_form)
        self.save_btn = QPushButton("Save phrase")
        self.save_btn.setObjectName("Primary")
        self.save_btn.clicked.connect(self.save_phrase)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self.delete_phrase)
        self.ocr_btn = QPushButton("OCR image…")
        self.ocr_btn.clicked.connect(self._pick_image)
        self.paste_btn = QPushButton("Paste image")
        self.paste_btn.clicked.connect(self.paste_image)
        self.translate_btn = QPushButton("Translate JA→EN")
        self.translate_btn.clicked.connect(self._translate_now)
        for b in (self.new_btn, self.save_btn, self.delete_btn, self.ocr_btn, self.paste_btn, self.translate_btn):
            actions.addWidget(b)
        actions.addStretch(1)
        rl.addLayout(actions)
        rl.addStretch(1)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)

        QShortcut(QKeySequence.Paste, self, self.paste_image)
        QShortcut(QKeySequence.Save, self, self.save_phrase)

        self.svc.progress_changed.connect(self._refresh_counts)
        self.clear_form()
        self.refresh_list()

    # ------------------------------------------------------------------ list
    def refresh_list(self) -> None:
        q = self.search.text().strip()
        phrases = self.svc.progress.phrases.search(q) if q else self.svc.progress.phrases.all()
        current = self._current_id
        self.list.clear()
        for p in phrases:
            status = self.svc.progress.status(P.PHRASE, p.id)
            item = QListWidgetItem(f"{p.jp}\n{p.en[:80] or '(no translation)'}")
            item.setData(Qt.UserRole, p.id)
            item.setToolTip(f"{p.reading} · {p.romaji}\n{status}")
            self.list.addItem(item)
            if p.id == current:
                self.list.setCurrentItem(item)
        self._refresh_counts()

    def _refresh_counts(self) -> None:
        now = self.svc.now()
        c = self.svc.progress.counts(P.PHRASE, now)
        n = self.svc.progress.phrases.count()
        self.count_lab.setText(
            f"{n} saved  ·  study: {c['review']} due · {c['new']} new · {c['learning']} learning"
        )
        self.study_btn.setText(
            f"Study phrases  ·  {c['review']} due · {c['new']} new"
        )

    def _picked(self, cur: QListWidgetItem | None, _prev=None) -> None:
        if cur is None:
            return
        phrase = self.svc.progress.phrases.get(cur.data(Qt.UserRole))
        if phrase:
            self._load(phrase)

    def _load(self, p: Phrase) -> None:
        self._current_id = p.id
        self._block = True
        self.jp.setPlainText(p.jp)
        self.reading.setText(p.reading)
        self.romaji.setText(p.romaji)
        self.en.setPlainText(p.en)
        self.notes.setPlainText(p.notes)
        self._block = False
        self.status.setText(f"Editing · source: {p.source}")

    def clear_form(self) -> None:
        self._current_id = None
        self._block = True
        self.jp.clear()
        self.reading.clear()
        self.romaji.clear()
        self.en.clear()
        self.notes.clear()
        self._block = False
        self.list.clearSelection()
        self.status.setText("New phrase")

    def _jp_changed(self) -> None:
        if getattr(self, "_block", False):
            return
        text = self.jp.toPlainText()
        # Live romaji→kana only when the field is still ASCII-ish.
        if text and all(ord(c) < 128 for c in text):
            jp, reading, romaji = normalize_jp_input(text)
            # Don't fight the user mid-IME; only fill helpers.
            if reading and not self.reading.text():
                self.reading.setText(reading)
            if romaji:
                self.romaji.setText(romaji)

    def save_phrase(self) -> None:
        raw_jp = self.jp.toPlainText().strip()
        if not raw_jp:
            self.svc.toast.emit("Enter Japanese text first.")
            return
        # If still romaji, convert for storage.
        if all(ord(c) < 128 for c in raw_jp) and any(c.isalpha() for c in raw_jp):
            jp, reading, romaji = normalize_jp_input(raw_jp)
        else:
            jp = raw_jp
            reading = self.reading.text().strip()
            romaji = self.romaji.text().strip()
            if not reading or not romaji:
                _, auto_r, auto_ro = normalize_jp_input(jp)
                reading = reading or auto_r
                romaji = romaji or auto_ro
        en = self.en.toPlainText().strip()
        notes = self.notes.toPlainText().strip()
        book = self.svc.progress.phrases
        if self._current_id:
            p = book.update(
                self._current_id, jp=jp, reading=reading, romaji=romaji, en=en, notes=notes,
            )
        else:
            p = book.add(jp, en, reading=reading, romaji=romaji, notes=notes, source="manual")
            self._current_id = p.id
        self.svc.notify_progress()
        self.svc.toast.emit("Phrase saved.")
        self.refresh_list()
        self._load(p)

    def delete_phrase(self) -> None:
        if not self._current_id:
            return
        if QMessageBox.question(self, "Delete phrase", "Delete this phrase and its SRS card?") != QMessageBox.Yes:
            return
        pid = self._current_id
        self.svc.progress.forget(P.PHRASE, pid)
        self.svc.progress.phrases.delete(pid)
        self.svc.notify_progress()
        self.clear_form()
        self.refresh_list()
        self.svc.toast.emit("Phrase deleted.")

    # ------------------------------------------------------------------ OCR / paste
    def _clipboard_image(self) -> QImage:
        clip = QGuiApplication.clipboard()
        image = QImage()
        if clip is None:
            return image
        mime = clip.mimeData()
        if mime is None:
            return image
        if mime.hasImage():
            image = QImage(clip.image())
        if image.isNull() and mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    image = QImage(url.toLocalFile())
                    if not image.isNull():
                        break
        return image

    def paste_image(self) -> None:
        """Ctrl+V: OCR a screenshot, or paste text into the field that has focus."""
        image = self._clipboard_image()
        if not image.isNull():
            self._run_ocr(image)
            return
        clip = QGuiApplication.clipboard()
        mime = clip.mimeData() if clip is not None else None
        focus = QApplication.focusWidget()
        if mime is not None and mime.hasText() and isinstance(focus, (QLineEdit, QPlainTextEdit)):
            text = mime.text()
            if isinstance(focus, QPlainTextEdit):
                focus.insertPlainText(text)
            else:
                focus.insert(text)
            return
        self.svc.toast.emit("Clipboard has no image.")

    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "OCR image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)",
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            self.svc.toast.emit("Could not load image.")
            return
        self._run_ocr(image)

    def _run_ocr(self, image: QImage) -> None:
        if self._ocr_worker and self._ocr_worker.isRunning():
            self.svc.toast.emit("OCR already running…")
            return
        if not ocr_available():
            QMessageBox.warning(
                self, "OCR unavailable",
                "Windows Japanese OCR is not available.\n"
                "Install it under Settings → Time & language → Language & region → Japanese → Language options → OCR.",
            )
            return
        self.status.setText("Running OCR…")
        self.drop.setText("OCR in progress…")
        auto = bool(self.svc.progress.setting("auto_translate_ocr"))
        self._ocr_worker = _OcrWorker(image, auto, self)
        self._ocr_worker.finished_ok.connect(self._ocr_done)
        self._ocr_worker.finished_err.connect(self._ocr_fail)
        self._ocr_worker.start()

    def _ocr_done(self, jp: str, reading: str, en: str) -> None:
        self.drop.setText("Paste or drop a screenshot here for OCR")
        if not jp:
            self.status.setText("OCR found no text.")
            self.svc.toast.emit("OCR found no Japanese text.")
            return
        self.clear_form()
        self._block = True
        self.jp.setPlainText(jp)
        # Don't invent reading/romaji by stripping kanji → leaves particle soup.
        # Only fill those when OCR returned usable furigana, or the JP is kana-only.
        if reading:
            self.reading.setText(reading)
            self.romaji.setText(K.to_romaji(reading, final_wa=True))
        else:
            _, auto_reading, romaji = normalize_jp_input(jp)
            has_kanji = any("\u3400" <= c <= "\u9fff" or "\uf900" <= c <= "\ufaff" for c in jp)
            if not has_kanji and auto_reading:
                self.reading.setText(auto_reading)
                self.romaji.setText(romaji)
        if en:
            self.en.setPlainText(en)
        self._block = False
        bits = ["OCR ready — edit if needed, then Save."]
        if en:
            bits.append("Translation is a machine draft (not video subtitles).")
        if not reading and any("\u3400" <= c <= "\u9fff" for c in jp):
            bits.append("Add reading manually if you want furigana.")
        self.status.setText(" ".join(bits))
        self.svc.toast.emit("OCR complete.")

    def _ocr_fail(self, message: str) -> None:
        self.drop.setText("Paste or drop a screenshot here for OCR")
        self.status.setText("OCR failed.")
        QMessageBox.warning(self, "OCR failed", message)

    def _translate_now(self) -> None:
        jp = self.jp.toPlainText().strip()
        if not jp:
            return
        self.status.setText("Translating…")
        en = translate_ja_to_en(jp)
        if en:
            self.en.setPlainText(en)
            self.status.setText("Translation filled.")
        else:
            self.status.setText("Translation unavailable (offline or rate-limited).")

    # ------------------------------------------------------------------ drag/drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime and (mime.hasImage() or mime.hasUrls()):
            event.acceptProposedAction()
            self.drop.setStyleSheet(
                f"background:{T.PANEL_RAISED}; border:1px solid {T.GOLD}; border-radius:12px; color:{T.GOLD_SOFT};"
            )

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.drop.setStyleSheet(
            f"background:{T.PANEL}; border:1px dashed #2E3C58; border-radius:12px; color:{T.FOG_DIM};"
        )
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.dragLeaveEvent(event)
        mime = event.mimeData()
        image = QImage()
        if mime.hasImage():
            image = QImage(mime.imageData())
        for url in mime.urls():
            if url.isLocalFile():
                image = QImage(url.toLocalFile())
                if not image.isNull():
                    break
        if not image.isNull():
            self._run_ocr(image)
            event.acceptProposedAction()
