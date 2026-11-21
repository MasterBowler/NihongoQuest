"""SRS study session for vocabulary or kanji."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from nihongo_quest.core import progress as P
from nihongo_quest.core import srs
from nihongo_quest.core.content import Kanji, Word
from nihongo_quest.core.phrases import Phrase
from nihongo_quest.core.session import StudySession
from nihongo_quest.ui import theme as T
from nihongo_quest.ui.services import AppServices
from nihongo_quest.ui.widgets.furigana import FuriganaLabel
from nihongo_quest.ui.widgets.pitch import PitchDiagram
from nihongo_quest.ui.widgets.stroke_canvas import StrokeCanvas


class StudyPane(QWidget):
    finished = Signal()
    detail_wanted = Signal(bool)  # show right rail for lessons / after reveal

    def __init__(self, services: AppServices, kind: str, parent=None) -> None:
        super().__init__(parent)
        self.svc = services
        self.kind = kind
        self.session: StudySession | None = None
        self._revealed = False
        self._started_ms = 0
        self._awaiting_write = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        titles = {P.VOCAB: "単語修行", P.KANJI: "漢字道場", P.PHRASE: "フレーズ修行"}
        self.title = QLabel(titles.get(kind, "修行"))
        self.title.setObjectName("SectionTitle")
        top.addWidget(self.title, 1)
        self.combo = QLabel()
        self.combo.setStyleSheet(f"font-family:'Dela Gothic One'; font-size:18px; color:{T.GOLD};")
        top.addWidget(self.combo)
        self.remain = QLabel()
        self.remain.setStyleSheet(f"color:{T.FOG_DIM};")
        top.addWidget(self.remain)
        root.addLayout(top)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        root.addWidget(self.bar)

        # Washi stage: text column + optional canvas column
        self.stage = QFrame()
        self.stage.setObjectName("Washi")
        self.stage.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        stage_row = QHBoxLayout(self.stage)
        stage_row.setContentsMargins(20, 16, 20, 16)
        stage_row.setSpacing(16)

        self.text_col = QWidget()
        self.text_col.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        text_l = QVBoxLayout(self.text_col)
        text_l.setContentsMargins(0, 0, 0, 0)
        text_l.setSpacing(8)

        self.mode_lab = QLabel()
        self.mode_lab.setStyleSheet("color:#6A5544; font-size:13px;")
        text_l.addWidget(self.mode_lab)

        text_l.addStretch(1)
        self.prompt = FuriganaLabel(base_pt=72, ruby_pt=18)
        self.prompt.setMinimumHeight(100)
        self.prompt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        text_l.addWidget(self.prompt, 2)

        self.sub = QLabel()
        self.sub.setObjectName("WashiReading")
        self.sub.setAlignment(Qt.AlignCenter)
        self.sub.setWordWrap(True)
        text_l.addWidget(self.sub)

        self.meaning = QLabel()
        self.meaning.setObjectName("WashiMeaning")
        self.meaning.setAlignment(Qt.AlignCenter)
        self.meaning.setWordWrap(True)
        text_l.addWidget(self.meaning)

        self.meaning_image = QLabel()
        self.meaning_image.setAlignment(Qt.AlignCenter)
        self.meaning_image.setMinimumHeight(0)
        self.meaning_image.setMaximumHeight(180)
        self.meaning_image.hide()
        text_l.addWidget(self.meaning_image)

        self.pitch = PitchDiagram()
        self.pitch.setMaximumHeight(72)
        text_l.addWidget(self.pitch)

        self.type_row = QHBoxLayout()
        self.type_input = QLineEdit()
        self.type_input.setPlaceholderText("Type reading (kana or romaji)…")
        self.type_input.returnPressed.connect(self._check_typed)
        self.type_row.addWidget(self.type_input)
        self.type_ok = QPushButton("Check")
        self.type_ok.clicked.connect(self._check_typed)
        self.type_row.addWidget(self.type_ok)
        text_l.addLayout(self.type_row)

        self.feedback = QLabel()
        self.feedback.setAlignment(Qt.AlignCenter)
        self.feedback.setStyleSheet("color:#6A5544; font-size:14px;")
        text_l.addWidget(self.feedback)
        text_l.addStretch(1)

        stage_row.addWidget(self.text_col, 3)

        self.canvas_wrap = QWidget()
        self.canvas_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cw = QVBoxLayout(self.canvas_wrap)
        cw.setContentsMargins(0, 0, 0, 0)
        self.canvas = StrokeCanvas()
        self.canvas.setMinimumSize(220, 220)
        self.canvas.character_done.connect(self._writing_done)
        self.canvas.stroke_judged.connect(self._stroke_feedback)
        cw.addWidget(self.canvas, 1)
        self.replay_btn = QPushButton("▶ Replay strokes")
        self.replay_btn.clicked.connect(self.canvas.animate)
        self.replay_btn.hide()
        cw.addWidget(self.replay_btn)
        stage_row.addWidget(self.canvas_wrap, 2)
        self.canvas_wrap.hide()

        root.addWidget(self.stage, 1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.reveal_btn = QPushButton("Show answer  (Space)")
        self.reveal_btn.setObjectName("Primary")
        self.reveal_btn.setMinimumHeight(52)
        self.reveal_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.reveal_btn.clicked.connect(self.reveal)
        self.actions.addWidget(self.reveal_btn, 2)

        self.lesson_next = QPushButton("Got it — continue")
        self.lesson_next.setObjectName("Primary")
        self.lesson_next.setMinimumHeight(52)
        self.lesson_next.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lesson_next.clicked.connect(lambda: self._finish_lesson(False))
        self.lesson_known = QPushButton("Already know")
        self.lesson_known.setMinimumHeight(52)
        self.lesson_known.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lesson_known.clicked.connect(lambda: self._finish_lesson(True))
        self.actions.addWidget(self.lesson_next, 2)
        self.actions.addWidget(self.lesson_known, 1)

        self.grade_btns: dict[int, QPushButton] = {}
        for rating, name, obj in (
            (srs.AGAIN, "Again", "GradeAgain"),
            (srs.HARD, "Hard", "GradeHard"),
            (srs.GOOD, "Good", "GradeGood"),
            (srs.EASY, "Easy", "GradeEasy"),
        ):
            btn = QPushButton(name)
            btn.setObjectName(obj)
            btn.setMinimumHeight(52)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda _=False, r=rating: self.grade(r))
            self.grade_btns[rating] = btn
            self.actions.addWidget(btn, 1)

        self.speak_btn = QPushButton("♪")
        self.speak_btn.setFixedSize(52, 52)
        self.speak_btn.clicked.connect(self._speak_current)
        self.actions.addWidget(self.speak_btn)
        root.addLayout(self.actions)

        QShortcut(QKeySequence(Qt.Key_Space), self, self._space)
        QShortcut(QKeySequence(Qt.Key_1), self, lambda: self.grade(srs.AGAIN))
        QShortcut(QKeySequence(Qt.Key_2), self, lambda: self.grade(srs.HARD))
        QShortcut(QKeySequence(Qt.Key_3), self, lambda: self.grade(srs.GOOD))
        QShortcut(QKeySequence(Qt.Key_4), self, lambda: self.grade(srs.EASY))
        QShortcut(QKeySequence(Qt.Key_R), self, self._speak_current)

        self._set_grades_visible(False)
        self._set_lesson_visible(False)

    def start(self) -> None:
        self.session = StudySession(self.svc.progress, self.kind)
        self.bar.setMaximum(max(self.session.total, 1))
        self.bar.setValue(0)
        self._next()

    def _show_canvas(self, on: bool, *, replay: bool = False) -> None:
        self.canvas_wrap.setVisible(on)
        self.replay_btn.setVisible(on and replay)
        # When the canvas is hidden, give the text column the full washi width.
        stage_row = self.stage.layout()
        if isinstance(stage_row, QHBoxLayout):
            stage_row.setStretch(0, 1 if on else 1)
            stage_row.setStretch(1, 1 if on else 0)

    def _want_detail(self, on: bool) -> None:
        self.detail_wanted.emit(on)

    def _next(self) -> None:
        assert self.session is not None
        prompt = self.session.next()
        self._revealed = False
        self._awaiting_write = False
        self._started_ms = int(time.time() * 1000)
        self.feedback.clear()
        self.type_input.clear()
        self._show_canvas(False)
        self.pitch.hide()
        self.meaning_image.hide()
        self.meaning_image.clear()
        self.prompt.show()
        rem = self.session.remaining()
        self.remain.setText(f"new {rem['new']} · learning {rem['learning']} · review {rem['review']}")
        self.combo.setText(f"×{self.session.stats.combo}" if self.session.stats.combo else "")
        done = self.session.stats.answered + self.session.stats.lessons
        self.bar.setValue(min(done, self.bar.maximum()))

        if prompt is None:
            self._show_summary()
            return

        if prompt.kind == P.VOCAB:
            word = self.svc.content.word_by_key(prompt.item)
            assert word is not None
            self.svc.select_word(word)
            self._show_vocab(word, prompt.mode)
        elif prompt.kind == P.PHRASE:
            phrase = self.svc.progress.phrases.get(prompt.item)
            assert phrase is not None
            self._show_phrase(phrase, prompt.mode)
        else:
            kanji = self.svc.content.kanji(prompt.item)
            assert kanji is not None
            self.svc.select_kanji(kanji)
            self._show_kanji(kanji, prompt.mode)

    def _show_vocab(self, w: Word, mode: str) -> None:
        typing = bool(self.svc.progress.setting("typing"))
        self.type_input.setVisible(typing and mode in ("recognition", "recall"))
        self.type_ok.setVisible(self.type_input.isVisible())

        if mode == "lesson":
            self.mode_lab.setText("LESSON · 新しい単語")
            if w.furi and self.svc.progress.setting("furigana"):
                self.prompt.set_segments([(a, b) for a, b in w.furi])
            else:
                self.prompt.set_plain(w.word)
            self.sub.setText(
                f"{w.kana}" + (f"  ·  {w.romaji}" if self.svc.progress.setting("show_romaji") else "")
            )
            self.meaning.setText(w.meaning)
            if w.pitch:
                self.pitch.show()
                self.pitch.set_pitch(w.kana, w.pitch[0])
            self._set_meaning_image(P.VOCAB, w.key)
            self._set_lesson_visible(True)
            self._set_grades_visible(False)
            self.reveal_btn.hide()
            self._want_detail(True)
            if self.svc.progress.setting("autoplay"):
                self.svc.speak_word(w)
            return

        self._set_lesson_visible(False)
        self.reveal_btn.show()
        self.reveal_btn.setText("Show answer  (Space)")
        self._set_grades_visible(False)
        self.meaning.clear()
        self.sub.clear()
        self._want_detail(False)

        if mode == "listening":
            self.mode_lab.setText("LISTENING · 聞き取り")
            self.prompt.set_plain("♪")
            self.sub.setText("Listen, then reveal the word.")
            self.svc.speak_word(w)
        elif mode == "recall":
            self.mode_lab.setText("RECALL · 英 → 日")
            self.prompt.set_plain(w.meaning.split("／")[0][:60])
            self.sub.setText("What is the Japanese word?")
        else:
            self.mode_lab.setText("RECOGNITION · 読んで意味")
            if w.furi and self.svc.progress.setting("furigana"):
                self.prompt.set_segments([(a, "") for a, _ in w.furi])
            else:
                self.prompt.set_plain(w.word)
            self.sub.setText("What does this mean?")

    def _show_phrase(self, p: Phrase, mode: str) -> None:
        self.type_input.hide()
        self.type_ok.hide()
        self._show_canvas(False)

        if mode == "lesson":
            self.mode_lab.setText("LESSON · 新しいフレーズ")
            self.prompt.set_plain(p.jp)
            reading = p.reading or ""
            if self.svc.progress.setting("show_romaji") and p.romaji:
                reading = f"{reading}  ·  {p.romaji}" if reading else p.romaji
            self.sub.setText(reading)
            self.meaning.setText(p.en or "(add a translation in Phrases)")
            if p.notes:
                self.feedback.setText(p.notes)
            self._set_lesson_visible(True)
            self._set_grades_visible(False)
            self.reveal_btn.hide()
            if self.svc.progress.setting("autoplay"):
                self.svc.speak_text(p.jp)
            return

        self._set_lesson_visible(False)
        self.reveal_btn.show()
        self.reveal_btn.setText("Show answer  (Space)")
        self._set_grades_visible(False)
        self.meaning.clear()
        self.sub.clear()

        if mode == "recall":
            self.mode_lab.setText("RECALL · 英 → 日")
            self.prompt.set_plain(p.en or "(no English yet)")
            self.sub.setText("What is the Japanese phrase?")
        else:
            self.mode_lab.setText("RECOGNITION · フレーズの意味")
            self.prompt.set_plain(p.jp)
            self.sub.setText("What does this mean?")

    def _show_kanji(self, k: Kanji, mode: str) -> None:
        self.type_input.hide()
        self.type_ok.hide()
        strokes = self.svc.content.strokes(k.ch)

        if mode == "lesson":
            self.mode_lab.setText("LESSON · 新しい漢字")
            self.prompt.set_plain(k.ch)
            self.sub.setText(" · ".join(k.meanings[:3]))
            self.meaning.setText(
                f"音 {' · '.join(k.on) or '—'}    訓 {' · '.join(k.kun) or '—'}\n"
                f"{k.strokes} strokes · {k.grade_name}"
            )
            if strokes:
                self._show_canvas(True, replay=True)
                self.canvas.set_character(strokes.paths, write=False, guide=True)
                self.canvas.animate()
            self._set_meaning_image(P.KANJI, k.ch)
            self._set_lesson_visible(True)
            self._set_grades_visible(False)
            self.reveal_btn.hide()
            self._want_detail(True)
            if self.svc.progress.setting("autoplay"):
                self.svc.speak_kanji(k)
            return

        self._set_lesson_visible(False)
        self.reveal_btn.show()
        self._set_grades_visible(False)
        self.meaning.clear()
        self._want_detail(False)

        if mode == "writing" and strokes:
            self.mode_lab.setText("WRITING · 書いてみよう")
            self.prompt.hide()
            self.sub.setText(" · ".join(k.meanings[:2]) + "\nDraw the kanji stroke by stroke.")
            self._show_canvas(True, replay=False)
            self.canvas.set_character(strokes.paths, write=True, guide=True)
            self._awaiting_write = True
            self.reveal_btn.setText("Skip writing / reveal")
        else:
            self.mode_lab.setText("RECOGNITION · 漢字の意味")
            self.prompt.set_plain(k.ch)
            self.sub.setText("What does this kanji mean?")
            self.reveal_btn.setText("Show answer  (Space)")

    def reveal(self) -> None:
        if self.session is None or self.session.current is None:
            return
        if self.session.current.is_lesson:
            return
        self._revealed = True
        prompt = self.session.current
        self.reveal_btn.hide()
        self._set_grades_visible(True)
        self._want_detail(True)
        preview = self.session.preview()
        for r, btn in self.grade_btns.items():
            btn.setText(f"{srs.RATING_NAMES[r]}\n{preview.get(r, '')}")

        if prompt.kind == P.VOCAB:
            w = self.svc.content.word_by_key(prompt.item)
            assert w is not None
            if w.furi and self.svc.progress.setting("furigana"):
                self.prompt.set_segments([(a, b) for a, b in w.furi])
            else:
                self.prompt.set_plain(w.word)
            self.prompt.show()
            romaji = f"  ·  {w.romaji}" if self.svc.progress.setting("show_romaji") else ""
            self.sub.setText(f"{w.kana}{romaji}")
            self.meaning.setText(w.meaning)
            if w.pitch:
                self.pitch.show()
                self.pitch.set_pitch(w.kana, w.pitch[0])
            self._set_meaning_image(P.VOCAB, w.key)
            if self.svc.progress.setting("autoplay"):
                self.svc.speak_word(w)
        elif prompt.kind == P.PHRASE:
            p = self.svc.progress.phrases.get(prompt.item)
            assert p is not None
            self.prompt.show()
            self.prompt.set_plain(p.jp)
            reading = p.reading or ""
            if self.svc.progress.setting("show_romaji") and p.romaji:
                reading = f"{reading}  ·  {p.romaji}" if reading else p.romaji
            self.sub.setText(reading)
            self.meaning.setText(p.en or "(no translation)")
            if self.svc.progress.setting("autoplay"):
                self.svc.speak_text(p.jp)
        else:
            k = self.svc.content.kanji(prompt.item)
            assert k is not None
            self.prompt.show()
            self.prompt.set_plain(k.ch)
            self.sub.setText(" · ".join(k.meanings[:4]))
            self.meaning.setText(f"音 {' · '.join(k.on) or '—'}    訓 {' · '.join(k.kun) or '—'}")
            self._set_meaning_image(P.KANJI, k.ch)
            strokes = self.svc.content.strokes(k.ch)
            if strokes:
                self._show_canvas(True, replay=True)
                self.canvas.set_character(strokes.paths, write=False, guide=True)
                self.canvas.animate()
            if self.svc.progress.setting("autoplay"):
                self.svc.speak_kanji(k)

    def _set_meaning_image(self, kind: str, item: str) -> None:
        path = self.svc.images.path(kind, item)
        if path is None:
            self.meaning_image.hide()
            self.meaning_image.clear()
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            self.meaning_image.hide()
            return
        self.meaning_image.setPixmap(
            pix.scaled(280, 170, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.meaning_image.show()

    def grade(self, rating: int) -> None:
        if self.session is None or self.session.current is None or self.session.current.is_lesson:
            return
        if not self._revealed and not (self._awaiting_write and rating >= srs.GOOD):
            return
        duration = int(time.time() * 1000) - self._started_ms
        self.session.answer(rating, duration)
        self.svc.notify_progress()
        self._next()

    def _finish_lesson(self, known: bool) -> None:
        if self.session is None:
            return
        self.session.finish_lesson(known)
        self.svc.notify_progress()
        self._next()

    def _writing_done(self, ok: bool) -> None:
        if not ok:
            return
        self.svc.progress.record(self.svc.now(), kanji_written=1)
        self._awaiting_write = False
        self._revealed = True
        self.feedback.setText("綺麗！ Nice writing.")
        self.reveal_btn.hide()
        self._set_grades_visible(True)
        self._want_detail(True)
        self.replay_btn.setVisible(True)
        preview = self.session.preview() if self.session else {}
        for r, btn in self.grade_btns.items():
            btn.setText(f"{srs.RATING_NAMES[r]}\n{preview.get(r, '')}")

    def _stroke_feedback(self, ok: bool, reason: str) -> None:
        if ok:
            self.feedback.setText("✓")
        else:
            msg = {
                "short": "Too short",
                "backwards": "Wrong direction",
                "elsewhere": "Wrong place",
                "shape": "Shape is off",
            }.get(reason, reason)
            self.feedback.setText(msg)

    def _check_typed(self) -> None:
        if self.session is None or self.session.current is None:
            return
        w = self.svc.content.word_by_key(self.session.current.item)
        if w is None:
            return
        if w.accepts_reading(self.type_input.text()):
            self.feedback.setText("✓ Reading OK")
            self.reveal()
        else:
            self.feedback.setText("Not quite — try again or reveal.")

    def _speak_current(self) -> None:
        if self.session is None or self.session.current is None:
            return
        if self.session.current.kind == P.VOCAB:
            w = self.svc.content.word_by_key(self.session.current.item)
            if w:
                self.svc.speak_word(w)
        elif self.session.current.kind == P.PHRASE:
            p = self.svc.progress.phrases.get(self.session.current.item)
            if p:
                self.svc.speak_text(p.jp)
        else:
            k = self.svc.content.kanji(self.session.current.item)
            if k:
                self.svc.speak_kanji(k)

    def _space(self) -> None:
        if self.session and self.session.current and self.session.current.is_lesson:
            self._finish_lesson(False)
        elif not self._revealed:
            self.reveal()
        else:
            self.grade(srs.GOOD)

    def _set_grades_visible(self, on: bool) -> None:
        for btn in self.grade_btns.values():
            btn.setVisible(on)

    def _set_lesson_visible(self, on: bool) -> None:
        self.lesson_next.setVisible(on)
        self.lesson_known.setVisible(on)

    def _show_summary(self) -> None:
        assert self.session is not None
        st = self.session.stats
        self.mode_lab.setText("SESSION CLEAR")
        self.prompt.set_plain("完了")
        self.sub.setText(f"{st.answered} reviews · {st.lessons} lessons · best combo ×{st.best_combo}")
        self.meaning.setText(f"Accuracy {st.accuracy:.0%} · +{self.session.xp_gained} XP")
        self._show_canvas(False)
        self.pitch.hide()
        self.type_input.hide()
        self.type_ok.hide()
        self.reveal_btn.hide()
        self._set_grades_visible(False)
        self._want_detail(False)
        self.lesson_known.hide()
        self.lesson_next.setText("Back to dojo")
        self.lesson_next.show()
        try:
            self.lesson_next.clicked.disconnect()
        except TypeError:
            pass
        self.lesson_next.clicked.connect(self.finished.emit)
        self.svc.notify_progress()
