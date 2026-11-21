"""Japanese TTS with optional online Neural voices and a local Windows fallback.

Preferred path: Microsoft Edge neural voices via ``edge-tts`` (Nanami / Keita),
cached as MP3 under ``userdata/audio``. Offline path: Qt TextToSpeech using the
installed Japanese SAPI voice (Haruka / Ayumi / …).
"""
from __future__ import annotations

import asyncio
import hashlib
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtTextToSpeech import QTextToSpeech

VOICE_IDS = {
    "nanami": "ja-JP-NanamiNeural",
    "keita": "ja-JP-KeitaNeural",
    "offline": None,
}


class Speaker(QObject):
    """Say Japanese text. Safe to call from the UI thread; downloads happen off-thread."""

    ready = Signal()
    failed = Signal(str)
    _play_path = Signal(str)

    def __init__(self, cache_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.voice = "nanami"
        self.rate = 0                      # percent, -50 .. +50
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._tts = QTextToSpeech(self)
        self._pick_local_voice()
        self._lock = threading.Lock()
        self._busy = False
        self._play_path.connect(self._on_ready)

    def _pick_local_voice(self) -> None:
        for v in self._tts.availableVoices():
            if str(v.locale().name()).lower().startswith("ja"):
                self._tts.setVoice(v)
                return

    def configure(self, voice: str = "nanami", rate: int = 0, volume: float = 1.0) -> None:
        self.voice = voice if voice in VOICE_IDS else "nanami"
        self.rate = max(-50, min(50, int(rate)))
        self._audio.setVolume(max(0.0, min(1.0, float(volume))))
        # Qt rate is roughly -1 .. +1
        self._tts.setRate(self.rate / 50.0)

    def stop(self) -> None:
        self._player.stop()
        self._tts.stop()

    def say(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.stop()
        if self.voice == "offline" or VOICE_IDS.get(self.voice) is None:
            self._tts.say(text)
            return
        path = self._cache_path(text)
        if path.exists() and path.stat().st_size > 0:
            self._play_file(path)
            return
        with self._lock:
            if self._busy:
                return
            self._busy = True
        threading.Thread(target=self._fetch_then_play, args=(text, path), daemon=True).start()

    def _cache_path(self, text: str) -> Path:
        key = f"{self.voice}|{self.rate}|{text}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.mp3"

    def _play_file(self, path: Path) -> None:
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()

    def _fetch_then_play(self, text: str, path: Path) -> None:
        try:
            self._synthesize(text, path)
            self._play_path.emit(str(path))
        except Exception as exc:  # noqa: BLE001 - surface any TTS failure to the UI
            self.failed.emit(str(exc))
            # Fall back to local voice so the learner still hears something.
            self._tts.say(text)
        finally:
            with self._lock:
                self._busy = False

    def _synthesize(self, text: str, path: Path) -> None:
        import edge_tts

        voice = VOICE_IDS[self.voice] or "ja-JP-NanamiNeural"
        rate = f"{self.rate:+d}%"
        tmp = path.with_suffix(".tmp")

        async def _run() -> None:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await communicate.save(str(tmp))

        asyncio.run(_run())
        tmp.replace(path)

    @Slot(str)
    def _on_ready(self, path: str) -> None:
        self._play_file(Path(path))
        self.ready.emit()
