"""Immersion · Manga — page images + manga OCR overlays + active-region dictionary."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from nihongo_quest.core.immersion.manga_ocr import (
    MangaBlock,
    manga_ocr_available,
    ocr_manga_crop,
    ocr_manga_page,
)
from nihongo_quest.core.immersion.tokenize import LexiconMatcher
from nihongo_quest.ui import theme as T
from nihongo_quest.ui.panes.immersion_shared import (
    TranslateWorker, romaji_from_line, save_immersion_phrase,
)
from nihongo_quest.ui.services import AppServices
from nihongo_quest.ui.widgets.clickable_japanese import ClickableJapanese
from nihongo_quest.ui.widgets.manga_page_view import MangaPageView

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


class _OcrPageWorker(QThread):
    finished_ok = Signal(object)  # list[MangaBlock]
    finished_err = Signal(str)

    def __init__(self, image: QImage, parent=None) -> None:
        super().__init__(parent)
        self.image = image.copy()

    def run(self) -> None:
        try:
            blocks = ocr_manga_page(self.image)
            self.finished_ok.emit(blocks)
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))


class _OcrCropWorker(QThread):
    finished_ok = Signal(str)
    finished_err = Signal(str)

    def __init__(self, image: QImage, parent=None) -> None:
        super().__init__(parent)
        self.image = image.copy()

    def run(self) -> None:
        try:
            text = ocr_manga_crop(self.image)
            self.finished_ok.emit(text or "")
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))


class MangaMode(QWidget):
    def __init__(self, services: AppServices, matcher: LexiconMatcher, parent=None) -> None:
        super().__init__(parent)
        self.svc = services
        self._matcher = matcher
        self._pages: list[Path] = []
        self._index = -1
        self._jp = ""
        self._selection = ""
        self._ocr_worker: _OcrPageWorker | None = None
        self._crop_worker: _OcrCropWorker | None = None
        self._translate_worker: TranslateWorker | None = None
        self._source_image: QImage | None = None
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        tools = QHBoxLayout()
        self.open_btn = QPushButton("Open images / folder…")
        self.open_btn.setObjectName("Primary")
        self.open_btn.clicked.connect(self._open)
        tools.addWidget(self.open_btn)
        self.paste_btn = QPushButton("Paste image")
        self.paste_btn.clicked.connect(self._paste)
        tools.addWidget(self.paste_btn)
        self.prev_btn = QPushButton("◀ Prev")
        self.prev_btn.clicked.connect(lambda: self._goto(self._index - 1))
        tools.addWidget(self.prev_btn)
        self.next_btn = QPushButton("Next ▶")
        self.next_btn.clicked.connect(lambda: self._goto(self._index + 1))
        tools.addWidget(self.next_btn)
        self.pos_lab = QLabel("No pages")
        self.pos_lab.setStyleSheet(f"color:{T.FOG_DIM};")
        tools.addWidget(self.pos_lab, 1)
        self.ocr_btn = QPushButton("OCR page")
        self.ocr_btn.clicked.connect(self._run_ocr)
        tools.addWidget(self.ocr_btn)
        root.addLayout(tools)

        body = QHBoxLayout()
        body.setSpacing(10)

        self.page_view = MangaPageView()
        self.page_view.setMinimumWidth(280)
        self.page_view.region_activated.connect(self._on_region_activated)
        self.page_view.crop_requested.connect(self._on_crop_requested)
        self.page_view.setStyleSheet(
            f"background:{T.INK_DEEP}; border:1px solid #243049; border-radius:8px;"
        )
        body.addWidget(self.page_view, 3)

        side = QVBoxLayout()
        side.setSpacing(8)
        self.jp_view = ClickableJapanese()
        self.jp_view.set_lexicon(matcher._forms, matcher._max_len)
        self.jp_view.setMinimumWidth(260)
        self.jp_view.word_clicked.connect(self._on_word)
        self.jp_view.phrase_selected.connect(self._on_phrase)
        side.addWidget(self.jp_view, 1)

        self.romaji_lab = QLabel()
        self.romaji_lab.setAlignment(Qt.AlignCenter)
        self.romaji_lab.setWordWrap(True)
        self.romaji_lab.setStyleSheet(f"color:{T.GOLD_SOFT}; font-size:14px;")
        side.addWidget(self.romaji_lab)

        self.en_lab = QLabel()
        self.en_lab.setAlignment(Qt.AlignCenter)
        self.en_lab.setWordWrap(True)
        self.en_lab.setStyleSheet(f"color:{T.FOG}; font-size:15px;")
        side.addWidget(self.en_lab)

        actions = QHBoxLayout()
        self.save_btn = QPushButton("Save phrase")
        self.save_btn.setObjectName("Primary")
        self.save_btn.clicked.connect(self._save)
        actions.addWidget(self.save_btn)
        self.speak_btn = QPushButton("♪")
        self.speak_btn.setFixedWidth(48)
        self.speak_btn.clicked.connect(self._speak)
        actions.addWidget(self.speak_btn)
        self.translate_btn = QPushButton("Translate")
        self.translate_btn.clicked.connect(self._translate)
        actions.addWidget(self.translate_btn)
        actions.addStretch(1)
        side.addLayout(actions)

        side_wrap = QWidget()
        side_wrap.setLayout(side)
        side_wrap.setMinimumWidth(280)
        side_wrap.setMaximumWidth(420)
        body.addWidget(side_wrap, 0)
        root.addLayout(body, 1)

        if manga_ocr_available():
            status_text = "Manga OCR ready — open a page to detect text regions."
        else:
            status_text = (
                "Manga OCR packages not installed "
                "(manga-ocr / comic-text-detector). Install deps to enable."
            )
        self.status = QLabel(status_text)
        self.status.setStyleSheet(f"color:{T.FOG_DIM};")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        QShortcut(QKeySequence(Qt.Key_Left), self, lambda: self._goto(self._index - 1))
        QShortcut(QKeySequence(Qt.Key_Right), self, lambda: self._goto(self._index + 1))
        self._sync_nav()
        self._clear_active()

    # -- page loading --------------------------------------------------------

    def _open(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Open manga pages",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;All files (*.*)",
        )
        if files:
            self._set_pages([Path(f) for f in files])
            return
        folder = QFileDialog.getExistingDirectory(self, "Open manga folder")
        if folder:
            paths = sorted(
                p for p in Path(folder).iterdir()
                if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
            )
            if not paths:
                self.svc.toast.emit("No images in that folder.")
                return
            self._set_pages(paths)

    def _paste(self) -> None:
        clip = QGuiApplication.clipboard()
        if clip is None or not clip.mimeData() or not clip.mimeData().hasImage():
            self.svc.toast.emit("Clipboard has no image.")
            return
        image = QImage(clip.image())
        if image.isNull():
            self.svc.toast.emit("Clipboard has no image.")
            return
        self._pages = []
        self._index = 0
        self.pos_lab.setText("Pasted page")
        self._show_qimage(image)
        self._run_ocr_image(image)
        self._sync_nav()

    def _set_pages(self, paths: list[Path]) -> None:
        self._pages = paths
        self._goto(0)

    def _goto(self, index: int) -> None:
        if not self._pages:
            return
        index = max(0, min(index, len(self._pages) - 1))
        self._index = index
        path = self._pages[index]
        self.pos_lab.setText(f"{index + 1} / {len(self._pages)}  ·  {path.name}")
        image = QImage(str(path))
        if image.isNull():
            self.status.setText(f"Could not load {path.name}")
            return
        self._show_qimage(image)
        self._run_ocr_image(image)
        self._sync_nav()

    def _show_qimage(self, image: QImage) -> None:
        self._source_image = image.copy()
        self.page_view.set_page(QPixmap.fromImage(self._source_image))
        self.page_view.set_blocks([])
        self._clear_active()

    def _sync_nav(self) -> None:
        n = len(self._pages)
        self.prev_btn.setEnabled(n > 1 and self._index > 0)
        self.next_btn.setEnabled(n > 1 and self._index < n - 1)
        busy = self._ocr_busy() or self._crop_busy()
        self.ocr_btn.setEnabled(
            not busy and (bool(self._pages) or self._source_image is not None)
        )

    def _ocr_busy(self) -> bool:
        return bool(self._ocr_worker and self._ocr_worker.isRunning())

    def _crop_busy(self) -> bool:
        return bool(self._crop_worker and self._crop_worker.isRunning())

    # -- page OCR ------------------------------------------------------------

    def _run_ocr(self) -> None:
        if 0 <= self._index < len(self._pages):
            image = QImage(str(self._pages[self._index]))
            if not image.isNull():
                self._run_ocr_image(image)
                return
        if self._source_image is not None and not self._source_image.isNull():
            self._run_ocr_image(self._source_image)
            return
        self.svc.toast.emit("No page to OCR.")

    def _run_ocr_image(self, image: QImage) -> None:
        if self._ocr_busy():
            return
        if not manga_ocr_available():
            self.status.setText(
                "Manga OCR unavailable — install manga-ocr and comic-text-detector."
            )
            return
        self.status.setText(
            "Loading models / running OCR… (first run may download ~400MB+)"
        )
        self._ocr_worker = _OcrPageWorker(image, self)
        self._ocr_worker.finished_ok.connect(self._on_ocr_blocks)
        self._ocr_worker.finished_err.connect(self._on_ocr_fail)
        self._ocr_worker.finished.connect(self._sync_nav)
        self._ocr_worker.start()
        self._sync_nav()

    def _on_ocr_blocks(self, blocks: object) -> None:
        block_list: list[MangaBlock] = list(blocks) if blocks else []
        self.page_view.set_blocks(block_list)
        self._clear_active()
        n = len(block_list)
        if n:
            self.status.setText(
                f"OCR ready — {n} region{'s' if n != 1 else ''}. "
                "Click a bubble or drag to crop."
            )
        else:
            self.status.setText("OCR found no text regions — try drag-crop.")

    def _on_ocr_fail(self, message: str) -> None:
        self.status.setText("OCR failed.")
        QMessageBox.warning(self, "OCR failed", message)

    # -- active region / crop ------------------------------------------------

    def _clear_active(self) -> None:
        self._jp = ""
        self._selection = ""
        self.jp_view.clear_text()
        self.romaji_lab.clear()
        self.en_lab.clear()

    def _set_active_text(self, text: str, *, status: str | None = None) -> None:
        text = (text or "").strip()
        self._jp = text
        self._selection = text
        self.en_lab.clear()
        if text:
            self.jp_view.set_text(text, align="center", font_pt=20)
            self.romaji_lab.setText(romaji_from_line(text, self._matcher))
            if status:
                self.status.setText(status)
        else:
            self.jp_view.clear_text()
            self.romaji_lab.clear()
            if status:
                self.status.setText(status)

    def _on_region_activated(self, block: object) -> None:
        text = getattr(block, "text", "") or ""
        self._set_active_text(
            text,
            status="Region selected — click words, translate, or save.",
        )

    def _on_crop_requested(self, rect: QRect) -> None:
        if self._source_image is None or self._source_image.isNull():
            return
        if self._crop_busy() or self._ocr_busy():
            return
        if not manga_ocr_available():
            self.status.setText("Manga OCR unavailable for crop.")
            return
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        if w <= 0 or h <= 0:
            return
        crop = self._source_image.copy(x, y, w, h)
        if crop.isNull():
            return
        self.status.setText("Running OCR on crop…")
        self._crop_worker = _OcrCropWorker(crop, self)
        self._crop_worker.finished_ok.connect(self._on_crop_ok)
        self._crop_worker.finished_err.connect(self._on_crop_fail)
        self._crop_worker.finished.connect(self._sync_nav)
        self._crop_worker.start()
        self._sync_nav()

    def _on_crop_ok(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self.page_view.clear_selection()
            self._set_active_text(
                text,
                status="Crop OCR ready — click words, translate, or save.",
            )
        else:
            self._set_active_text("", status="Crop OCR found no text.")

    def _on_crop_fail(self, message: str) -> None:
        self.status.setText("Crop OCR failed.")
        QMessageBox.warning(self, "Crop OCR failed", message)

    # -- side panel actions --------------------------------------------------

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
        name = self._pages[self._index].name if 0 <= self._index < len(self._pages) else "paste"
        save_immersion_phrase(
            self.svc,
            jp=jp,
            en=self.en_lab.text(),
            source=f"manga:{name}",
            matcher=self._matcher,
            parent=self,
        )

    def _speak(self) -> None:
        text = (self._selection or self._jp).strip()
        if text:
            self.svc.speak_text(text)

    def _translate(self) -> None:
        text = self._jp.strip()
        if not text:
            self.svc.toast.emit("No Japanese text to translate.")
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

    # -- drag / drop ---------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime and (mime.hasUrls() or mime.hasImage()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime is None:
            return
        if mime.hasUrls():
            paths = []
            for url in mime.urls():
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.is_dir():
                        paths.extend(
                            sorted(
                                q for q in p.iterdir()
                                if q.is_file() and q.suffix.lower() in _IMAGE_EXTS
                            )
                        )
                    elif p.suffix.lower() in _IMAGE_EXTS:
                        paths.append(p)
            if paths:
                self._set_pages(paths)
                event.acceptProposedAction()
                return
        if mime.hasImage():
            image = QImage(mime.imageData())
            if not image.isNull():
                self._pages = []
                self._index = 0
                self.pos_lab.setText("Dropped page")
                self._show_qimage(image)
                self._run_ocr_image(image)
                event.acceptProposedAction()
