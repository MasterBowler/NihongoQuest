"""Shared runtime: content, progress, TTS, and UI signals."""
from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from nihongo_quest.audio import Speaker
from nihongo_quest.core import kana as K
from nihongo_quest.core.content import Content, Kanji, Word
from nihongo_quest.core.images import ImageStore
from nihongo_quest.core.progress import KANJI, VOCAB, Progress
from nihongo_quest.paths import AUDIO_CACHE, BACKUPS, CONTENT_DB, PROGRESS_DB, USER


@dataclass
class Selection:
    kind: str | None = None   # vocab | kanji
    item: str | None = None


class AppServices(QObject):
    selection_changed = Signal()
    english_changed = Signal()
    rail_mode_changed = Signal(str)  # "ja" | "en_ro"
    progress_changed = Signal()
    settings_changed = Signal()
    images_changed = Signal()
    toast = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        USER.mkdir(parents=True, exist_ok=True)
        self.content = Content(CONTENT_DB)
        self.progress = Progress(PROGRESS_DB, self.content)
        self.progress.backup(BACKUPS)
        self.images = ImageStore()
        self.speaker = Speaker(AUDIO_CACHE, self)
        self.apply_voice_settings()
        self.selection = Selection()
        self._selection_history: list[Selection] = []
        self._english_word = ""
        self._english_context = ""

    def now(self) -> float:
        return time.time()

    def apply_voice_settings(self) -> None:
        self.speaker.configure(
            voice=str(self.progress.setting("voice")),
            rate=int(self.progress.setting("speech_rate")),
            volume=1.0,
        )

    def speak_word(self, word: Word) -> None:
        self.speaker.say(word.tts or word.word)

    def speak_text(self, text: str) -> None:
        self.speaker.say(text)

    def speak_kanji(self, kanji: Kanji) -> None:
        """Prefer on-yomi, else kun (okurigana stripped)."""
        if kanji.on:
            self.speak_text(K.kata_to_hira(kanji.on[0]))
            return
        if kanji.kun:
            self.speak_text(kanji.kun[0].split(".")[0].split("-")[0])
            return
        self.speak_text(kanji.ch)

    def select_word(self, word: Word | None, *, remember: bool = False) -> None:
        if remember:
            self._push_history()
        else:
            self._selection_history.clear()
        if word is None:
            self.selection = Selection()
        else:
            self.selection = Selection(VOCAB, word.key)
        self.selection_changed.emit()
        self.set_rail_mode("ja")

    def select_kanji(self, kanji: Kanji | str | None, *, remember: bool = False) -> None:
        if remember:
            self._push_history()
        else:
            self._selection_history.clear()
        if kanji is None:
            self.selection = Selection()
        elif isinstance(kanji, str):
            self.selection = Selection(KANJI, kanji)
        else:
            self.selection = Selection(KANJI, kanji.ch)
        self.selection_changed.emit()
        self.set_rail_mode("ja")

    def select_english(self, word: str, *, context: str = "") -> None:
        """Look up an English word/phrase in the EN→RO rail (Immersion helper)."""
        self._english_word = (word or "").strip()
        self._english_context = (context or "").strip()
        self.english_changed.emit()
        if self._english_word:
            self.set_rail_mode("en_ro")

    def selected_english(self) -> tuple[str, str]:
        return self._english_word, self._english_context

    def rail_mode(self) -> str:
        mode = str(self.progress.setting("rail_mode") or "ja")
        return mode if mode in {"ja", "en_ro"} else "ja"

    def set_rail_mode(self, mode: str) -> None:
        mode = mode if mode in {"ja", "en_ro"} else "ja"
        if self.rail_mode() == mode:
            self.rail_mode_changed.emit(mode)
            return
        self.progress.set_setting("rail_mode", mode)
        self.rail_mode_changed.emit(mode)

    def can_go_back(self) -> bool:
        return bool(self._selection_history)

    def go_back(self) -> bool:
        if not self._selection_history:
            return False
        self.selection = self._selection_history.pop()
        self.selection_changed.emit()
        return True

    def clear_selection_history(self) -> None:
        self._selection_history.clear()

    def _push_history(self) -> None:
        cur = self.selection
        if not cur.kind or not cur.item:
            return
        if self._selection_history and self._selection_history[-1] == cur:
            return
        self._selection_history.append(Selection(cur.kind, cur.item))
        if len(self._selection_history) > 40:
            self._selection_history = self._selection_history[-40:]

    def selected_word(self) -> Word | None:
        if self.selection.kind != VOCAB or not self.selection.item:
            return None
        return self.content.word_by_key(self.selection.item)

    def selected_kanji(self) -> Kanji | None:
        if self.selection.kind != KANJI or not self.selection.item:
            return None
        return self.content.kanji(self.selection.item)

    def notify_progress(self) -> None:
        self.progress_changed.emit()

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self.speaker.stop()
        try:
            self.progress.backup(BACKUPS)
        except Exception:  # noqa: BLE001
            pass
        self.progress.close()
