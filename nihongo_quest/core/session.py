"""One sitting of study: decides which card comes next and applies the answers.

Order of play
  1. cards in a same-day learning step that have come due,
  2. lessons for new items, spread evenly between the reviews (never more
     than a handful of un-quizzed lessons at once),
  3. due reviews, most-forgotten first,
  4. whatever is still waiting on a learning step ("learn ahead"), so a
     session always ends with nothing left hanging.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable

from . import srs
from .progress import KANJI, KNOWN, PHRASE, VOCAB, Card, Progress

LESSON = "lesson"
COMBO_BONUS_EVERY = 10
COMBO_BONUS_XP = 20


@dataclass(frozen=True)
class Prompt:
    kind: str
    item: str
    mode: str                 # lesson | recognition | listening | recall | writing
    card: Card | None = None  # None while the item is still an un-started lesson

    @property
    def is_lesson(self) -> bool:
        return self.mode == LESSON


@dataclass
class SessionStats:
    started: float = 0.0
    answered: int = 0
    correct: int = 0
    lessons: int = 0
    combo: int = 0
    best_combo: int = 0
    xp_at_start: int = 0
    results: list[tuple[str, int]] = field(default_factory=list)   # (item, rating), newest last

    @property
    def accuracy(self) -> float:
        return self.correct / self.answered if self.answered else 0.0


class StudySession:
    WAITING_CAP = 5           # lessons allowed to pile up before their first quiz is forced

    def __init__(self, progress: Progress, kind: str, now: Callable[[], float] = time.time,
                 rng: random.Random | None = None) -> None:
        if kind not in (VOCAB, KANJI, PHRASE):
            raise ValueError(kind)
        self.progress = progress
        self.kind = kind
        self.now = now
        self.rng = rng or random.Random()
        t = now()
        self.reviews: list[Card] = progress.due_reviews(kind, t)[: int(progress.setting("review_cap"))]
        self.new: list[str] = progress.next_new(kind, progress.new_allowance(kind, t))
        self.learning: dict[str, Card] = {c.item: c for c in progress.in_learning(kind)}
        # one lesson every `gap` reviews spreads the new material over the whole session
        self._gap = max(1, math.ceil(len(self.reviews) / len(self.new))) if self.new else 0
        self._since_lesson = self._gap          # so a session with reviews still opens with something new
        self.current: Prompt | None = None
        self.stats = SessionStats(started=t, xp_at_start=progress.xp)
        self.total = len(self.reviews) + len(self.new) + len(self.learning)

    # ------------------------------------------------------------------ queue
    def remaining(self) -> dict[str, int]:
        return {"new": len(self.new), "learning": len(self.learning), "review": len(self.reviews)}

    def done(self) -> bool:
        return not (self.new or self.learning or self.reviews)

    def next(self) -> Prompt | None:
        """Choose the next prompt (None when the session is finished)."""
        t = self.now()
        waiting = sorted(self.learning.values(), key=lambda c: c.s.due)
        due = [c for c in waiting if c.s.due <= t]
        fresh = [c for c in waiting if c.s.state == srs.NEW]
        if due:
            prompt = self._quiz(due[0])
        elif len(fresh) >= self.WAITING_CAP:
            prompt = self._quiz(fresh[0])
        elif self.new and (not self.reviews or self._since_lesson >= self._gap):
            prompt = Prompt(self.kind, self.new[0], LESSON)
        elif self.reviews:
            prompt = self._quiz(self.reviews[0])
        elif waiting:
            prompt = self._quiz(waiting[0])
        else:
            prompt = None
        self.current = prompt
        return prompt

    def _quiz(self, card: Card) -> Prompt:
        if self.kind == VOCAB:
            setting = self.progress.setting("vocab_mode")
            choices = ["recognition", "listening", "recall"]
        elif self.kind == PHRASE:
            setting = self.progress.setting("phrase_mode")
            choices = ["recognition", "recall"]
        else:
            setting = self.progress.setting("kanji_mode")
            choices = ["recognition", "writing"]
        if card.s.state == srs.NEW:
            mode = "recognition"                      # the first quiz after a lesson is always the plain one
        elif setting == "mixed":
            mode = self.rng.choice(choices)
        else:
            mode = setting if setting in choices else "recognition"
        if mode == "writing" and self.progress.content.strokes(card.item) is None:
            mode = "recognition"
        return Prompt(self.kind, card.item, mode, card)

    # ------------------------------------------------------------------ answers
    def preview(self) -> dict[int, str]:
        """Label for each grade button: when the card would come back."""
        if self.current is None or self.current.card is None:
            return {}
        t = self.now()
        return {r: srs.due_text(c, t) for r, c in self.progress.scheduler.preview(self.current.card.s, t).items()}

    def finish_lesson(self, known: bool = False) -> None:
        """The learner has read the lesson. ``known``: they already knew the item,
        so it is filed as known instead of entering the review cycle."""
        prompt = self.current
        if prompt is None or not prompt.is_lesson:
            raise RuntimeError("no lesson in progress")
        t = self.now()
        self.new.remove(prompt.item)
        self._since_lesson = 0
        if known:
            self.progress.set_flag(self.kind, prompt.item, KNOWN, t)
        else:
            self.learning[prompt.item] = self.progress.introduce(self.kind, prompt.item, t)
            self.stats.lessons += 1
        self.current = None

    def answer(self, rating: int, duration_ms: int = 0) -> Card:
        prompt = self.current
        if prompt is None or prompt.card is None:
            raise RuntimeError("no card to answer")
        t = self.now()
        card = self.progress.answer(prompt.card, rating, t, duration_ms, prompt.mode)
        if prompt.card in self.reviews:
            self.reviews.remove(prompt.card)
            self._since_lesson += 1
        if card.s.state == srs.REVIEW:
            self.learning.pop(card.item, None)
        else:
            self.learning[card.item] = card
        st = self.stats
        st.answered += 1
        st.results.append((card.item, rating))
        if rating > srs.AGAIN:
            st.correct += 1
            st.combo += 1
            if st.combo > st.best_combo:
                st.best_combo = st.combo
                self.progress.record_combo(st.best_combo, t)
            if st.combo % COMBO_BONUS_EVERY == 0:
                self.progress.add_xp(COMBO_BONUS_XP, t)
        else:
            st.combo = 0
        self.current = None
        return card

    def skip(self) -> None:
        """Take the current item out of this session without answering it."""
        prompt = self.current
        if prompt is None:
            return
        if prompt.is_lesson:
            self.new.remove(prompt.item)
        else:
            if prompt.card in self.reviews:
                self.reviews.remove(prompt.card)
            self.learning.pop(prompt.item, None)
        self.current = None

    @property
    def xp_gained(self) -> int:
        return self.progress.xp - self.stats.xp_at_start
