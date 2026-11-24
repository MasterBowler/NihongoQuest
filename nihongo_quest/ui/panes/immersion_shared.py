"""Shared Immersion helpers (romaji, phrase save, translate worker)."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QMessageBox, QWidget

from nihongo_quest.core import kana as K
from nihongo_quest.core import progress as P
from nihongo_quest.core.immersion.lmstudio import translate_ja_to_en_lm
from nihongo_quest.core.immersion.tokenize import LexiconMatcher
from nihongo_quest.core.ocr import translate_ja_to_en
from nihongo_quest.ui.services import AppServices


def romaji_from_line(text: str, matcher: LexiconMatcher | None) -> str:
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


def reading_from_line(text: str, matcher: LexiconMatcher) -> str:
    bits = [tok.word.kana for tok in matcher.tokenize(text) if tok.word is not None]
    return " ".join(bits)


def save_immersion_phrase(
    svc: AppServices,
    *,
    jp: str,
    en: str,
    source: str,
    matcher: LexiconMatcher,
    parent: QWidget | None = None,
) -> bool:
    jp = (jp or "").strip()
    if not jp:
        svc.toast.emit("Nothing to save.")
        return False
    try:
        phrase = svc.progress.phrases.add(
            jp,
            en.strip(),
            reading=reading_from_line(jp, matcher),
            romaji=romaji_from_line(jp, matcher),
            source=source,
        )
        svc.progress.introduce(P.PHRASE, phrase.id, svc.now())
        svc.notify_progress()
        svc.toast.emit("Phrase saved.")
        return True
    except Exception as exc:  # noqa: BLE001
        if parent is not None:
            QMessageBox.warning(parent, "Save failed", str(exc))
        else:
            svc.toast.emit(str(exc))
        return False


class TranslateWorker(QThread):
    finished_ok = Signal(str)
    finished_err = Signal(str)

    def __init__(
        self,
        text: str,
        *,
        prefer_lm: bool,
        lm_url: str,
        lm_model: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.text = text
        self.prefer_lm = prefer_lm
        self.lm_url = lm_url
        self.lm_model = lm_model

    def run(self) -> None:
        try:
            out = ""
            if self.prefer_lm:
                out = translate_ja_to_en_lm(
                    self.text, base_url=self.lm_url, model=self.lm_model,
                )
            if not out:
                out = translate_ja_to_en(self.text)
            if not out:
                self.finished_err.emit("No translation (offline / LM Studio not running).")
            else:
                self.finished_ok.emit(out)
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))
