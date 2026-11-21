"""Right-rail detail view for the currently selected word or kanji."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from nihongo_quest.core import conjugate as C
from nihongo_quest.core import progress as P
from nihongo_quest.core.content import Kanji, Word
from nihongo_quest.ui import theme as T
from nihongo_quest.ui.services import AppServices
from nihongo_quest.ui.widgets.furigana import FuriganaLabel
from nihongo_quest.ui.widgets.meaning_image import MeaningImageCard
from nihongo_quest.ui.widgets.pitch import PitchDiagram
from nihongo_quest.ui.widgets.stroke_canvas import StrokeCanvas


class DetailPane(QWidget):
    def __init__(self, services: AppServices, parent=None) -> None:
        super().__init__(parent)
        self.svc = services
        self.setObjectName("ContextRail")
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("詳 細")
        title.setObjectName("PanelTitle")
        head.addWidget(title, 1)
        self.back_btn = QPushButton("← Back")
        self.back_btn.setToolTip("Return to the previous linked item")
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.hide()
        head.addWidget(self.back_btn)
        root.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 8, 0)
        self.body_layout.setSpacing(10)
        scroll.setWidget(self.body)
        root.addWidget(scroll, 1)

        self.empty = QLabel("Select a word or kanji\nto inspect it here.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(f"color: {T.FOG_DIM}; padding: 40px;")
        self.body_layout.addWidget(self.empty)
        self.body_layout.addStretch(1)

        self.svc.selection_changed.connect(self.refresh)
        self.svc.progress_changed.connect(self.refresh)
        self.svc.images_changed.connect(self.refresh)

    def _go_back(self) -> None:
        if self.svc.go_back():
            self.svc.toast.emit("Back.")

    def _clear(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def refresh(self) -> None:
        self._clear()
        self.back_btn.setVisible(self.svc.can_go_back())
        word = self.svc.selected_word()
        kanji = self.svc.selected_kanji()
        if word is not None:
            self._show_word(word)
        elif kanji is not None:
            self._show_kanji(kanji)
        else:
            empty = QLabel("Select a word or kanji\nto inspect it here.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color: {T.FOG_DIM}; padding: 40px;")
            self.body_layout.addWidget(empty)
            self.body_layout.addStretch(1)

    def _chip(self, text: str, color: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(
            f"background:{color}; color:white; border-radius:8px; padding:3px 8px; font-size:11px;"
        )
        lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return lab

    def _show_word(self, w: Word) -> None:
        card = QFrame()
        card.setObjectName("Washi")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 16, 16, 16)
        furi = FuriganaLabel(base_pt=42, ruby_pt=13)
        if w.furi:
            furi.set_segments([(a, b) for a, b in w.furi])
        else:
            furi.set_plain(w.word)
        lay.addWidget(furi)
        reading = QLabel(f"{w.kana}  ·  {w.romaji}")
        reading.setObjectName("WashiReading")
        reading.setWordWrap(True)
        lay.addWidget(reading)
        meaning = QLabel(w.meaning)
        meaning.setObjectName("WashiMeaning")
        meaning.setWordWrap(True)
        lay.addWidget(meaning)
        self.body_layout.addWidget(card)

        row = QHBoxLayout()
        row.addWidget(self._chip(w.level_name, T.LEVEL_COLOR.get(w.level, T.FOG_DIM)))
        status = self.svc.progress.status(P.VOCAB, w.key)
        row.addWidget(self._chip(status, T.STATUS.get(status, T.FOG_DIM)))
        for label in self.svc.content.pos_labels(w.pos)[:3]:
            row.addWidget(self._chip(label, "#2E3C58"))
        row.addStretch(1)
        speak = QPushButton("♪ 聞く")
        speak.clicked.connect(lambda: self.svc.speak_word(w))
        row.addWidget(speak)
        self.body_layout.addLayout(row)

        self.body_layout.addWidget(self._section("イラスト · Meaning image"))
        img = MeaningImageCard(self.svc.images, P.VOCAB, w.key, max_height=200)
        img.changed.connect(self.svc.images_changed.emit)
        img.changed.connect(lambda: self.svc.toast.emit("Meaning image saved."))
        self.body_layout.addWidget(img)

        if w.pitch:
            pitch = PitchDiagram()
            pitch.set_pitch(w.kana, w.pitch[0])
            self.body_layout.addWidget(pitch)

        if w.kanji_form and w.kanji_form != w.word:
            alt = QLabel(f"Kanji form: {w.kanji_form}")
            alt.setStyleSheet(f"color:{T.FOG_DIM};")
            self.body_layout.addWidget(alt)

        # senses
        for i, sense in enumerate(w.senses[:4], 1):
            gloss = "; ".join(sense.get("gloss", []))
            lab = QLabel(f"{i}. {gloss}")
            lab.setWordWrap(True)
            self.body_layout.addWidget(lab)

        # kanji breakdown
        if w.all_kanji:
            self.body_layout.addWidget(self._section("漢字"))
            for ch in w.all_kanji:
                k = self.svc.content.kanji(ch)
                btn = QPushButton(f"{ch}  {(k.meaning if k else '')}")
                btn.setStyleSheet("text-align:left;")
                btn.clicked.connect(lambda _=False, c=ch: self.svc.select_kanji(c, remember=True))
                self.body_layout.addWidget(btn)

        # examples
        examples = self.svc.content.examples(w.id)
        if examples:
            self.body_layout.addWidget(self._section("例文"))
            for ex in examples[:4]:
                box = QFrame()
                box.setObjectName("Card")
                bl = QVBoxLayout(box)
                bl.setContentsMargins(10, 8, 10, 8)
                jp = FuriganaLabel(base_pt=18, ruby_pt=10, base_color=T.WASHI, ruby_color=T.FOG_DIM,
                                  align=Qt.AlignLeft)
                jp.set_segments(ex.segments)
                jp.setMinimumHeight(40)
                bl.addWidget(jp)
                en = QLabel(ex.en)
                en.setWordWrap(True)
                en.setStyleSheet(f"color:{T.FOG_DIM}; font-size:12px;")
                bl.addWidget(en)
                self.body_layout.addWidget(box)

        # conjugations
        forms = C.conjugate(w.word, w.kana, w.pos)
        if forms:
            self.body_layout.addWidget(self._section("活用"))
            for form in forms[:10]:
                lab = QLabel(f"{form.label_jp} ({form.label}):  {form.written} / {form.kana}")
                lab.setWordWrap(True)
                lab.setStyleSheet("font-size:12px;")
                self.body_layout.addWidget(lab)

        # notes
        self.body_layout.addWidget(self._section("メモ"))
        notes = QPlainTextEdit()
        notes.setPlaceholderText("Your notes for this word…")
        notes.setPlainText(self.svc.progress.note(P.VOCAB, w.key))
        notes.setFixedHeight(90)
        notes.textChanged.connect(
            lambda: self.svc.progress.set_note(P.VOCAB, w.key, notes.toPlainText())
        )
        self.body_layout.addWidget(notes)

        actions = QHBoxLayout()
        known = QPushButton("Already know")
        known.clicked.connect(lambda: self._mark(P.VOCAB, w.key, P.KNOWN))
        sus = QPushButton("Suspend")
        sus.clicked.connect(lambda: self._mark(P.VOCAB, w.key, P.SUSPENDED))
        actions.addWidget(known)
        actions.addWidget(sus)
        self.body_layout.addLayout(actions)
        self.body_layout.addStretch(1)

        if self.svc.progress.setting("autoplay"):
            self.svc.speak_word(w)

    def _show_kanji(self, k: Kanji) -> None:
        head = QLabel(k.ch)
        head.setAlignment(Qt.AlignCenter)
        head.setFont(QFont("Klee One", 84))
        head.setStyleSheet(f"color:{T.WASHI};")
        self.body_layout.addWidget(head)

        meaning = QLabel(" · ".join(k.meanings[:4]) or "(no meaning)")
        meaning.setAlignment(Qt.AlignCenter)
        meaning.setWordWrap(True)
        meaning.setStyleSheet(f"font-size:16px; color:{T.GOLD_SOFT};")
        self.body_layout.addWidget(meaning)

        meta = QLabel(
            f"{k.level_name}  ·  {k.grade_name}  ·  {k.strokes} strokes"
            + (f"  ·  freq #{k.freq}" if k.freq else "")
        )
        meta.setAlignment(Qt.AlignCenter)
        meta.setStyleSheet(f"color:{T.FOG_DIM};")
        self.body_layout.addWidget(meta)

        status = self.svc.progress.status(P.KANJI, k.ch)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._chip(status, T.STATUS.get(status, T.FOG_DIM)))
        row.addStretch(1)
        self.body_layout.addLayout(row)

        self.body_layout.addWidget(self._section("イラスト · Meaning image"))
        img = MeaningImageCard(self.svc.images, P.KANJI, k.ch, max_height=200)
        img.changed.connect(self.svc.images_changed.emit)
        img.changed.connect(lambda: self.svc.toast.emit("Meaning image saved."))
        self.body_layout.addWidget(img)

        strokes = self.svc.content.strokes(k.ch)
        if strokes:
            canvas = StrokeCanvas()
            canvas.setMinimumHeight(200)
            canvas.setMaximumHeight(280)
            canvas.set_character(strokes.paths, write=False, guide=True)
            self.body_layout.addWidget(canvas)
            anim = QPushButton("▶ Stroke order")
            anim.clicked.connect(canvas.animate)
            self.body_layout.addWidget(anim)

        self.body_layout.addWidget(self._section("読み"))
        on = QLabel("音: " + (" · ".join(k.on) or "—"))
        kun = QLabel("訓: " + (" · ".join(k.kun) or "—"))
        on.setWordWrap(True)
        kun.setWordWrap(True)
        self.body_layout.addWidget(on)
        self.body_layout.addWidget(kun)

        if k.radical:
            rad = k.radical
            self.body_layout.addWidget(
                QLabel(f"Radical: {rad.get('ch', '')} {rad.get('name', '')}")
            )

        words = self.svc.content.words_for_kanji(k.ch)[:8]
        if words:
            self.body_layout.addWidget(self._section("語彙"))
            for word, reading in words:
                btn = QPushButton(f"{word.word}【{reading or word.kana}】 {word.meaning.split('／')[0][:40]}")
                btn.setStyleSheet("text-align:left;")
                btn.clicked.connect(lambda _=False, ww=word: self.svc.select_word(ww, remember=True))
                self.body_layout.addWidget(btn)

        self.body_layout.addWidget(self._section("メモ"))
        notes = QPlainTextEdit()
        notes.setPlaceholderText("Your notes for this kanji…")
        notes.setPlainText(self.svc.progress.note(P.KANJI, k.ch))
        notes.setFixedHeight(90)
        notes.textChanged.connect(
            lambda: self.svc.progress.set_note(P.KANJI, k.ch, notes.toPlainText())
        )
        self.body_layout.addWidget(notes)

        actions = QHBoxLayout()
        known = QPushButton("Already know")
        known.clicked.connect(lambda: self._mark(P.KANJI, k.ch, P.KNOWN))
        speak = QPushButton("♪ 読む")
        speak.clicked.connect(lambda kk=k: self.svc.speak_kanji(kk))
        actions.addWidget(known)
        actions.addWidget(speak)
        self.body_layout.addLayout(actions)
        self.body_layout.addStretch(1)

    def _section(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("PanelTitle")
        return lab

    def _mark(self, kind: str, item: str, flag: int) -> None:
        self.svc.progress.set_flag(kind, item, flag)
        self.svc.notify_progress()
        self.svc.toast.emit("Saved.")
