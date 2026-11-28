"""Immersion hub — Anime (VLC + softsubs), Manga (OCR), Novel (text/EPUB)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

from nihongo_quest.core import kana as K
from nihongo_quest.core.immersion.cues import Cue, CueTrack
from nihongo_quest.core.immersion.ffprobe import (
    FFmpegError, SubtitleTrack, extract_subtitle_track, ffmpeg_available, list_subtitle_tracks,
)
from nihongo_quest.core.immersion.lmstudio import translate_ja_to_en_lm
from nihongo_quest.core.immersion.subs import parse_subtitle_file
from nihongo_quest.core.immersion.tokenize import LexiconMatcher
from nihongo_quest.core.immersion.vlc_external import ExternalVlc, find_vlc_exe
from nihongo_quest.ui import theme as T
from nihongo_quest.ui.panes.immersion_manga import MangaMode
from nihongo_quest.ui.panes.immersion_novel import NovelMode
from nihongo_quest.ui.services import AppServices
from nihongo_quest.ui.widgets.clickable_english import ClickableEnglish
from nihongo_quest.ui.widgets.clickable_japanese import ClickableJapanese


def _format_ms(ms: int) -> str:
    ms = max(0, int(ms))
    s, milli = divmod(ms, 1000)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _romaji_from_line(text: str, matcher: LexiconMatcher | None) -> str:
    if not text:
        return ""
    if matcher is None:
        kana_only = "".join(c for c in K.kata_to_hira(text) if K.is_kana(c) or c == "ー")
        return K.to_romaji(kana_only, final_wa=True) if kana_only else ""
    bits: list[str] = []
    for tok in matcher.tokenize(text):
        if tok.word is not None:
            bits.append(tok.word.romaji or K.to_romaji(tok.word.kana, final_wa=True))
        else:
            piece = "".join(c for c in K.kata_to_hira(tok.text) if K.is_kana(c) or c == "ー")
            if piece:
                bits.append(K.to_romaji(piece, final_wa=True))
    return " ".join(b for b in bits if b)


class _ProbeWorker(QThread):
    finished_ok = Signal(object)
    finished_err = Signal(str)

    def __init__(self, path: Path, ffmpeg_path: str, parent=None) -> None:
        super().__init__(parent)
        self.path = path
        self.ffmpeg_path = ffmpeg_path

    def run(self) -> None:
        try:
            self.finished_ok.emit(list_subtitle_tracks(self.path, self.ffmpeg_path))
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))


class _ExtractWorker(QThread):
    finished_ok = Signal(object, object)
    finished_err = Signal(str)

    def __init__(
        self,
        path: Path,
        ja: SubtitleTrack | None,
        en: SubtitleTrack | None,
        ffmpeg_path: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.ja = ja
        self.en = en
        self.ffmpeg_path = ffmpeg_path

    def run(self) -> None:
        try:
            tmp = Path(tempfile.mkdtemp(prefix="nq_immersion_"))
            ja_track = en_track = None
            if self.ja is not None:
                out = extract_subtitle_track(self.path, self.ja, dest_dir=tmp, ffmpeg_path=self.ffmpeg_path)
                ja_track = CueTrack(parse_subtitle_file(out), language=self.ja.language, title=self.ja.title)
            if self.en is not None:
                out = extract_subtitle_track(self.path, self.en, dest_dir=tmp, ffmpeg_path=self.ffmpeg_path)
                en_track = CueTrack(parse_subtitle_file(out), language=self.en.language, title=self.en.title)
            self.finished_ok.emit(ja_track, en_track)
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))


class _TranslateWorker(QThread):
    finished_ok = Signal(str)
    finished_err = Signal(str)

    def __init__(self, text: str, base_url: str, model: str, parent=None) -> None:
        super().__init__(parent)
        self.text = text
        self.base_url = base_url
        self.model = model

    def run(self) -> None:
        try:
            out = translate_ja_to_en_lm(self.text, base_url=self.base_url, model=self.model)
            if not out:
                self.finished_err.emit("LM Studio returned no translation (is the server running?).")
            else:
                self.finished_ok.emit(out)
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))


class _VlcLaunchWorker(QThread):
    finished_ok = Signal()
    finished_err = Signal(str)

    def __init__(self, vlc: ExternalVlc, path: Path, parent=None) -> None:
        super().__init__(parent)
        self.vlc = vlc
        self.path = path

    def run(self) -> None:
        try:
            self.vlc.start(self.path)
            self.finished_ok.emit()
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))


class ImmersionPane(QWidget):
    def __init__(self, services: AppServices, parent=None) -> None:
        super().__init__(parent)
        self.svc = services
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._media_path: Path | None = None
        self._tracks: list[SubtitleTrack] = []
        self._ja_cues: CueTrack | None = None
        self._en_cues: CueTrack | None = None
        self._last_ja = ""
        self._last_en = ""
        self._selection_jp = ""
        self._probe_worker: _ProbeWorker | None = None
        self._extract_worker: _ExtractWorker | None = None
        self._translate_worker: _TranslateWorker | None = None
        self._launch_worker: _VlcLaunchWorker | None = None
        self._matcher = LexiconMatcher(services.content)
        self._vlc = ExternalVlc()
        self._duration_ms = 0
        self._position_ms = 0
        self._seeking = False
        self._playing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("浸 透 · Immersion")
        title.setObjectName("SectionTitle")
        head.addWidget(title, 1)
        self.mode_anime = QPushButton("Anime")
        self.mode_manga = QPushButton("Manga")
        self.mode_novel = QPushButton("Novel")
        self.mode_anime.clicked.connect(lambda: self._set_mode(0))
        self.mode_manga.clicked.connect(lambda: self._set_mode(1))
        self.mode_novel.clicked.connect(lambda: self._set_mode(2))
        for b in (self.mode_anime, self.mode_manga, self.mode_novel):
            head.addWidget(b)
        root.addLayout(head)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_anime_page())          # 0
        self.stack.addWidget(MangaMode(services, self._matcher))  # 1
        self.stack.addWidget(NovelMode(services, self._matcher))  # 2
        self._set_mode(0)

        self._tick = QTimer(self)
        self._tick.setInterval(250)
        self._tick.timeout.connect(self._on_tick)

        self._space = QShortcut(QKeySequence(Qt.Key_Space), self)
        self._space.setContext(Qt.WidgetWithChildrenShortcut)
        self._space.setAutoRepeat(False)
        self._space.activated.connect(self._toggle_pause)

    def _set_mode(self, index: int) -> None:
        index = max(0, min(index, self.stack.count() - 1))
        # Pause anime polling when leaving anime; don't kill VLC (user may keep watching).
        if index != 0:
            self.release_for_navigation()
        self.stack.setCurrentIndex(index)
        space = getattr(self, "_space", None)
        if space is not None:
            # Space pauses anime only while that mode is showing and focused.
            space.setEnabled(index == 0)
        for i, btn in enumerate((self.mode_anime, self.mode_manga, self.mode_novel)):
            btn.setObjectName("Primary" if i == index else "")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _ffmpeg_path(self) -> str:
        return str(self.svc.progress.setting("ffmpeg_path") or "")

    def _build_anime_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        tools = QHBoxLayout()
        self.open_btn = QPushButton("Open video…")
        self.open_btn.setObjectName("Primary")
        self.open_btn.clicked.connect(self._open_video)
        tools.addWidget(self.open_btn)
        self.close_btn = QPushButton("Close video")
        self.close_btn.clicked.connect(self._close_video)
        self.close_btn.setEnabled(False)
        tools.addWidget(self.close_btn)
        tools.addWidget(QLabel("JA subs"))
        self.ja_box = QComboBox()
        self.ja_box.setMinimumWidth(160)
        self.ja_box.currentIndexChanged.connect(self._reload_tracks)
        tools.addWidget(self.ja_box, 1)
        tools.addWidget(QLabel("EN subs"))
        self.en_box = QComboBox()
        self.en_box.setMinimumWidth(160)
        self.en_box.currentIndexChanged.connect(self._reload_tracks)
        tools.addWidget(self.en_box, 1)
        self.load_subs_btn = QPushButton("Load tracks")
        self.load_subs_btn.clicked.connect(self._reload_tracks)
        tools.addWidget(self.load_subs_btn)
        lay.addLayout(tools)

        stage = QFrame()
        stage.setStyleSheet("background:#0E1524; border:1px solid #243049; border-radius:8px;")
        stage.setMinimumHeight(160)
        sl = QVBoxLayout(stage)
        self.stage_hint = QLabel(
            "Video plays in a separate VLC window (keeps this app responsive).\n"
            "Move VLC to your other screen if you like — subs stay synced here.\n"
            "In-app embedding was removed because it froze Qt on Windows."
        )
        self.stage_hint.setAlignment(Qt.AlignCenter)
        self.stage_hint.setStyleSheet(f"color:{T.FOG_DIM}; padding:20px;")
        self.stage_hint.setWordWrap(True)
        sl.addStretch(1)
        sl.addWidget(self.stage_hint)
        sl.addStretch(1)
        lay.addWidget(stage, 2)

        transport = QHBoxLayout()
        self.play_btn = QPushButton("Play / Pause")
        self.play_btn.clicked.connect(self._toggle_pause)
        self.play_btn.setEnabled(False)
        transport.addWidget(self.play_btn)
        self.time_lab = QLabel("0:00 / 0:00")
        self.time_lab.setStyleSheet(f"color:{T.FOG_DIM};")
        transport.addWidget(self.time_lab)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._seek_released)
        transport.addWidget(self.seek, 1)
        lay.addLayout(transport)

        vlc = find_vlc_exe()
        self.status = QLabel(
            "Open an MKV/MP4 with soft subtitle tracks. Requires VLC + ffmpeg."
            + (f"  VLC: {vlc}" if vlc else "  VLC.exe not found.")
        )
        self.status.setStyleSheet(f"color:{T.FOG_DIM};")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.jp_view = ClickableJapanese()
        self.jp_view.set_lexicon(self._matcher._forms, self._matcher._max_len)
        self.jp_view.word_clicked.connect(self._on_word)
        self.jp_view.phrase_selected.connect(self._on_phrase_sel)
        lay.addWidget(self.jp_view)

        self.romaji_lab = QLabel()
        self.romaji_lab.setAlignment(Qt.AlignCenter)
        self.romaji_lab.setWordWrap(True)
        self.romaji_lab.setStyleSheet(f"color:{T.GOLD_SOFT}; font-size:14px;")
        lay.addWidget(self.romaji_lab)

        self.en_view = ClickableEnglish()
        self.en_view.word_clicked.connect(self._on_en_word)
        self.en_view.phrase_selected.connect(self._on_en_phrase)
        lay.addWidget(self.en_view)

        actions = QHBoxLayout()
        self.save_btn = QPushButton("Save phrase")
        self.save_btn.setObjectName("Primary")
        self.save_btn.clicked.connect(self._save_phrase)
        actions.addWidget(self.save_btn)
        self.speak_btn = QPushButton("♪")
        self.speak_btn.setFixedWidth(48)
        self.speak_btn.clicked.connect(self._speak)
        actions.addWidget(self.speak_btn)
        self.translate_btn = QPushButton("Translate line (LM Studio)")
        self.translate_btn.clicked.connect(self._translate_line)
        actions.addWidget(self.translate_btn)
        actions.addStretch(1)
        lay.addLayout(actions)
        return page

    def release_for_navigation(self) -> None:
        """Pause polling when leaving; leave VLC window alone (user may keep watching)."""
        self._tick.stop()

    def _force_release_embed(self) -> None:
        self._close_video()

    # ------------------------------------------------------------------ open / tracks
    def _open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open video",
            "",
            "Video (*.mkv *.mp4 *.m4v *.webm *.avi *.mov);;All files (*.*)",
        )
        if not path:
            return
        self._load_media(Path(path))

    def _load_media(self, path: Path) -> None:
        if not self._vlc.available:
            QMessageBox.warning(
                self, "VLC required",
                "Install VLC (videolan.org) so Immersion can open a separate player window.\n"
                "In-process embedding was removed because it froze the app on Windows.",
            )
            return

        self._close_video()
        self._media_path = path
        self._ja_cues = None
        self._en_cues = None
        self._last_ja = ""
        self._last_en = ""
        self.jp_view.clear_text()
        self.romaji_lab.clear()
        self.en_view.clear_text()
        self.ja_box.blockSignals(True)
        self.en_box.blockSignals(True)
        self.ja_box.clear()
        self.en_box.clear()
        self.ja_box.addItem("(none)", None)
        self.en_box.addItem("(none)", None)
        self.ja_box.blockSignals(False)
        self.en_box.blockSignals(False)

        self.stage_hint.setText(
            f"Starting VLC for:\n{path.name}\n\n"
            "Drag the VLC window to your other screen if you want."
        )
        self.status.setText("Launching VLC…")
        self.close_btn.setEnabled(True)
        self.play_btn.setEnabled(False)

        if self._launch_worker and self._launch_worker.isRunning():
            return
        self._launch_worker = _VlcLaunchWorker(self._vlc, path, self)
        self._launch_worker.finished_ok.connect(self._on_vlc_ready)
        self._launch_worker.finished_err.connect(self._on_vlc_fail)
        self._launch_worker.start()

        if ffmpeg_available(self._ffmpeg_path()):
            self._probe_worker = _ProbeWorker(path, self._ffmpeg_path(), self)
            self._probe_worker.finished_ok.connect(self._on_probe_ready)
            self._probe_worker.finished_err.connect(self._on_probe_fail)
            self._probe_worker.start()
        else:
            self.status.setText("VLC starting — ffmpeg missing, so subs won’t load yet.")

    def _on_vlc_ready(self) -> None:
        self.play_btn.setEnabled(True)
        self._playing = True
        self._tick.start()
        name = self._media_path.name if self._media_path else "video"
        self.stage_hint.setText(
            f"Playing in VLC:\n{name}\n\n"
            "Use Play/Pause & seek here — Japanese / romaji / English update below.\n"
            "Close video dismisses the VLC window."
        )
        self.status.setText("VLC running (separate window).")
        self.svc.toast.emit(f"VLC opened · {name}")

    def _on_vlc_fail(self, message: str) -> None:
        self.status.setText("Could not start VLC.")
        QMessageBox.warning(self, "VLC", message)

    def _on_probe_ready(self, tracks: object) -> None:
        self._tracks = list(tracks) if tracks else []
        text_tracks = [t for t in self._tracks if t.is_text]
        self.ja_box.blockSignals(True)
        self.en_box.blockSignals(True)
        self.ja_box.clear()
        self.en_box.clear()
        self.ja_box.addItem("(none)", None)
        self.en_box.addItem("(none)", None)
        ja_idx = 0  # (none) unless a Japanese track is found
        en_idx = 0
        for i, t in enumerate(text_tracks):
            self.ja_box.addItem(t.label, t)
            self.en_box.addItem(t.label, t)
            lang = (t.language or "").lower()
            title = (t.title or "").lower()
            # Combo indices are offset by the leading "(none)" row.
            if lang in {"jpn", "ja", "jp"} or "jap" in title or "japanese" in title:
                ja_idx = i + 1
            if lang in {"eng", "en"} or "eng" in title or "english" in title:
                en_idx = i + 1
        self.ja_box.setCurrentIndex(ja_idx)
        if en_idx:
            self.en_box.setCurrentIndex(en_idx)
        elif text_tracks and ja_idx == 0:
            # EN-only (or unlabeled) file: use the first text track as English.
            self.en_box.setCurrentIndex(1)
        self.ja_box.blockSignals(False)
        self.en_box.blockSignals(False)
        name = self._media_path.name if self._media_path else "video"
        if not text_tracks:
            self.status.setText(
                f"{name}: no text subtitle tracks (ASS/SRT). PGS/VobSub not supported."
            )
            return
        self.status.setText(f"{name}: {len(text_tracks)} text sub track(s). Extracting…")
        self._reload_tracks()

    def _on_probe_fail(self, message: str) -> None:
        self.status.setText("Subtitle probe failed.")
        QMessageBox.warning(self, "Subtitle probe failed", message)

    def _reload_tracks(self) -> None:
        if self._media_path is None:
            return
        if self._extract_worker and self._extract_worker.isRunning():
            return
        ja: SubtitleTrack | None = self.ja_box.currentData()
        en: SubtitleTrack | None = self.en_box.currentData()
        if ja is None and en is None:
            self._ja_cues = None
            self._en_cues = None
            self._last_ja = ""
            self._last_en = ""
            self.jp_view.clear_text()
            self.romaji_lab.clear()
            self.en_view.clear_text()
            self.status.setText("No subtitle tracks selected.")
            return
        self.status.setText("Extracting subtitle tracks…")
        self._extract_worker = _ExtractWorker(
            self._media_path, ja, en, self._ffmpeg_path(), self,
        )
        self._extract_worker.finished_ok.connect(self._on_cues_ready)
        self._extract_worker.finished_err.connect(self._on_cues_fail)
        self._extract_worker.start()

    def _on_cues_ready(self, ja: CueTrack | None, en: CueTrack | None) -> None:
        self._ja_cues = ja
        self._en_cues = en
        n_ja = len(ja.cues) if ja else 0
        n_en = len(en.cues) if en else 0
        self.status.setText(f"Subtitles ready — JA {n_ja} cues · EN {n_en} cues.")
        self._refresh_cues(force=True)

    def _on_cues_fail(self, message: str) -> None:
        self.status.setText("Subtitle extract failed.")
        QMessageBox.warning(self, "Subtitle extract failed", message)

    # ------------------------------------------------------------------ playback
    def _toggle_pause(self) -> None:
        if self.stack.currentIndex() != 0 or not self._vlc.running:
            return
        self._vlc.toggle_pause()

    def _seek_released(self) -> None:
        self._seeking = False
        if not self._vlc.running or self._duration_ms <= 0:
            return
        ratio = self.seek.value() / 1000.0
        self._vlc.seek_ms(int(self._duration_ms * ratio))
        self._refresh_cues(force=True)

    def _close_video(self) -> None:
        self._tick.stop()
        self._vlc.stop()
        self._media_path = None
        self._ja_cues = None
        self._en_cues = None
        self._last_ja = ""
        self._last_en = ""
        self._duration_ms = 0
        self._position_ms = 0
        self._playing = False
        self.seek.setValue(0)
        self.time_lab.setText("0:00 / 0:00")
        self.jp_view.clear_text()
        self.romaji_lab.clear()
        self.en_view.clear_text()
        self.play_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.stage_hint.setText(
            "Video closed.\nOpen a video to launch VLC again.\n"
            "In-app embedding stays disabled (it froze Qt)."
        )
        self.status.setText("Video closed.")
        self.svc.toast.emit("VLC closed.")

    def _on_tick(self) -> None:
        if not self._vlc.running:
            self._tick.stop()
            self.play_btn.setEnabled(False)
            self.status.setText("VLC window closed.")
            return
        st = self._vlc.status()
        if st is None:
            return
        self._playing = st.is_playing
        if st.length_ms > 0:
            self._duration_ms = st.length_ms
        self._position_ms = st.time_ms
        self.time_lab.setText(f"{_format_ms(st.time_ms)} / {_format_ms(self._duration_ms)}")
        if not self._seeking and self._duration_ms > 0:
            self.seek.blockSignals(True)
            self.seek.setValue(int(1000 * st.time_ms / self._duration_ms))
            self.seek.blockSignals(False)
        self._refresh_cues()

    def _refresh_cues(self, force: bool = False) -> None:
        t = self._position_ms
        ja_cue: Cue | None = self._ja_cues.at(t) if self._ja_cues else None
        en_cue: Cue | None = self._en_cues.at(t) if self._en_cues else None
        ja_text = ja_cue.text if ja_cue else ""
        en_text = en_cue.text if en_cue else ""
        if ja_text != self._last_ja or force:
            self._last_ja = ja_text
            self._selection_jp = ja_text
            if ja_text:
                self.jp_view.set_text(ja_text)
                self.romaji_lab.setText(_romaji_from_line(ja_text, self._matcher))
            else:
                self.jp_view.clear_text()
                self.romaji_lab.clear()
        if en_text != self._last_en or force:
            self._last_en = en_text
            if en_text:
                self.en_view.set_text(en_text)
            else:
                self.en_view.clear_text()

    # ------------------------------------------------------------------ lexicon / phrases
    def _on_word(self, word) -> None:
        if word is not None:
            self.svc.select_word(word)
            self._selection_jp = word.word

    def _on_phrase_sel(self, text: str) -> None:
        self._selection_jp = text
        hit = self._matcher.lookup(text)
        if hit is not None:
            self.svc.select_word(hit)

    def _on_en_word(self, word: str) -> None:
        self.svc.select_english(word, context=self.en_view.text())

    def _on_en_phrase(self, text: str) -> None:
        phrase = (text or "").strip()
        if phrase:
            self.svc.select_english(phrase, context=self.en_view.text())

    def _save_phrase(self) -> None:
        jp = (self.jp_view.selected_phrase() or self._selection_jp or self._last_ja).strip()
        if not jp:
            self.svc.toast.emit("Nothing to save.")
            return
        en = self.en_view.text().strip()
        name = self._media_path.name if self._media_path else "video"
        source = f"anime:{name}@{_format_ms(self._position_ms)}"
        reading = ""
        romaji = _romaji_from_line(jp, self._matcher)
        bits = [tok.word.kana for tok in self._matcher.tokenize(jp) if tok.word is not None]
        if bits:
            reading = " ".join(bits)
        try:
            from nihongo_quest.core import progress as P
            phrase = self.svc.progress.phrases.add(
                jp, en, reading=reading, romaji=romaji, source=source,
            )
            self.svc.progress.introduce(P.PHRASE, phrase.id, self.svc.now())
            self.svc.notify_progress()
            self.svc.toast.emit("Phrase saved.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Save failed", str(exc))

    def _speak(self) -> None:
        text = (self._selection_jp or self._last_ja).strip()
        if text:
            self.svc.speak_text(text)

    def _translate_line(self) -> None:
        text = self._last_ja.strip()
        if not text:
            self.svc.toast.emit("No Japanese line to translate.")
            return
        if self._translate_worker and self._translate_worker.isRunning():
            return
        if not bool(self.svc.progress.setting("lmstudio_enabled")):
            self.svc.toast.emit("Enable LM Studio in Settings first.")
            return
        base = str(self.svc.progress.setting("lmstudio_url") or "http://127.0.0.1:1234/v1")
        model = str(self.svc.progress.setting("lmstudio_model") or "")
        self.status.setText("Translating via LM Studio…")
        self._translate_worker = _TranslateWorker(text, base, model, self)
        self._translate_worker.finished_ok.connect(self._on_translated)
        self._translate_worker.finished_err.connect(self._on_translate_fail)
        self._translate_worker.start()

    def _on_translated(self, en: str) -> None:
        self.en_view.set_text(en)
        self.status.setText("LM Studio translation filled (draft).")
        self.svc.toast.emit("Translated.")

    def _on_translate_fail(self, message: str) -> None:
        self.status.setText("LM Studio translation failed.")
        QMessageBox.warning(self, "LM Studio", message)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.release_for_navigation()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._close_video()
        super().closeEvent(event)
