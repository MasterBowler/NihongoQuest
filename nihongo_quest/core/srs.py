"""Spaced-repetition scheduling.

Long-term memory is modelled with FSRS-4.5 (the "free spaced repetition
scheduler": each card carries a *stability* in days and a *difficulty* from
1 to 10, and the next interval is chosen so the predicted chance of recall
equals the desired retention). The formulas and default weights follow the
published FSRS-4.5 reference implementation.

Same-day learning steps are handled the way Anki-style schedulers do: a new
or lapsed card must be answered correctly once more after a short delay before
it graduates to day-scale intervals. One deliberate addition: failing during
those steps resets the card to the "Again" starting stability, so a word that
did not stick on its first day comes back the next day rather than days later.

Pure Python, no Qt; time is always passed in explicitly so the module is easy
to test.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, datetime, time as dtime

NEW, LEARNING, REVIEW, RELEARNING = 0, 1, 2, 3
AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
RATINGS = (AGAIN, HARD, GOOD, EASY)
RATING_NAMES = {AGAIN: "Again", HARD: "Hard", GOOD: "Good", EASY: "Easy"}
STATE_NAMES = {NEW: "new", LEARNING: "learning", REVIEW: "review", RELEARNING: "relearning"}

DAY = 86400.0
MATURE_DAYS = 21.0

# FSRS-4.5 default weights.
DEFAULT_WEIGHTS = (
    0.4872, 1.4003, 3.7145, 13.8206, 5.1618, 1.2298, 0.8975, 0.031, 1.6474,
    0.1367, 1.0461, 2.1072, 0.0793, 0.3246, 1.587, 0.2272, 2.8755,
)
DECAY = -0.5
FACTOR = 0.9 ** (1 / DECAY) - 1          # 19/81, makes R(S, S) = 0.9


@dataclass(frozen=True)
class CardState:
    state: int = NEW
    due: float = 0.0             # unix seconds
    stability: float = 0.0       # days until recall probability falls to 90%
    difficulty: float = 0.0      # 1 (easy) .. 10 (hard)
    reps: int = 0
    lapses: int = 0
    last_review: float = 0.0     # unix seconds, 0 = never reviewed
    scheduled_days: int = 0      # length of the current review interval


class Scheduler:
    def __init__(
        self,
        retention: float = 0.9,
        max_interval: int = 36500,
        weights: tuple[float, ...] = DEFAULT_WEIGHTS,
        day_start_hour: int = 4,
        again_secs: float = 60,
        hard_secs: float = 5 * 60,
        good_secs: float = 10 * 60,
    ) -> None:
        if not 0.7 <= retention <= 0.99:
            raise ValueError("retention must be between 0.70 and 0.99")
        self.retention = retention
        self.max_interval = max_interval
        self.w = tuple(weights)
        self.day_start_hour = day_start_hour
        self.again_secs = again_secs
        self.hard_secs = hard_secs
        self.good_secs = good_secs

    # ------------------------------------------------------------------ days
    def day_index(self, ts: float) -> int:
        """Ordinal of the study day containing ``ts`` (days roll over at day_start_hour, local time)."""
        return datetime.fromtimestamp(ts - self.day_start_hour * 3600).date().toordinal()

    def day_start(self, day_index: int) -> float:
        """Unix time at which the given study day begins."""
        return datetime.combine(date.fromordinal(day_index), dtime(self.day_start_hour)).timestamp()

    # ------------------------------------------------------------------ FSRS core
    def init_stability(self, rating: int) -> float:
        return max(self.w[rating - 1], 0.1)

    def init_difficulty(self, rating: int) -> float:
        return min(max(self.w[4] - self.w[5] * (rating - 3), 1.0), 10.0)

    @staticmethod
    def forgetting_curve(elapsed_days: float, stability: float) -> float:
        if stability <= 0:
            return 0.0
        return (1 + FACTOR * max(elapsed_days, 0.0) / stability) ** DECAY

    def next_interval(self, stability: float) -> int:
        ivl = stability / FACTOR * (self.retention ** (1 / DECAY) - 1)
        return int(min(max(round(ivl), 1), self.max_interval))

    def next_difficulty(self, d: float, rating: int) -> float:
        nd = d - self.w[6] * (rating - 3)
        nd = self.w[7] * self.w[4] + (1 - self.w[7]) * nd       # mean reversion
        return min(max(nd, 1.0), 10.0)

    def next_recall_stability(self, d: float, s: float, r: float, rating: int) -> float:
        hard_penalty = self.w[15] if rating == HARD else 1.0
        easy_bonus = self.w[16] if rating == EASY else 1.0
        return s * (1 + math.exp(self.w[8]) * (11 - d) * s ** (-self.w[9])
                    * (math.exp((1 - r) * self.w[10]) - 1) * hard_penalty * easy_bonus)

    def next_forget_stability(self, d: float, s: float, r: float) -> float:
        return self.w[11] * d ** (-self.w[12]) * ((s + 1) ** self.w[13] - 1) * math.exp((1 - r) * self.w[14])

    # ------------------------------------------------------------------ scheduling
    def retrievability(self, card: CardState, now: float) -> float:
        """Predicted probability that the card would be recalled right now."""
        if card.state == NEW or card.last_review <= 0 or card.stability <= 0:
            return 0.0
        elapsed = self.day_index(now) - self.day_index(card.last_review)
        return self.forgetting_curve(elapsed, card.stability)

    def _graduate(self, card: CardState, now: float, interval: int) -> CardState:
        return replace(card, state=REVIEW, scheduled_days=interval,
                       due=self.day_start(self.day_index(now) + interval))

    def preview(self, card: CardState, now: float) -> dict[int, CardState]:
        """The card as it would be after each of the four ratings."""
        out: dict[int, CardState] = {}
        base = replace(card, reps=card.reps + 1, last_review=now)

        if card.state == NEW:
            for r in RATINGS:
                c = replace(base, stability=self.init_stability(r), difficulty=self.init_difficulty(r))
                if r == EASY:
                    c = self._graduate(c, now, self.next_interval(c.stability))
                else:
                    step = {AGAIN: self.again_secs, HARD: self.hard_secs, GOOD: self.good_secs}[r]
                    c = replace(c, state=LEARNING, scheduled_days=0, due=now + step)
                out[r] = c
            return out

        if card.state in (LEARNING, RELEARNING):
            weak = min(card.stability, self.init_stability(AGAIN))
            out[AGAIN] = replace(base, stability=weak, scheduled_days=0, due=now + self.again_secs)
            out[HARD] = replace(base, scheduled_days=0, due=now + self.hard_secs)
            good = self.next_interval(card.stability)
            out[GOOD] = self._graduate(base, now, good)
            out[EASY] = self._graduate(base, now, min(good + 1, self.max_interval))
            return out

        # REVIEW
        elapsed = max(self.day_index(now) - self.day_index(card.last_review), 0)
        r_now = self.forgetting_curve(elapsed, card.stability)
        d, s = card.difficulty, card.stability
        # A lapse can never leave the card more stable than it was (the raw
        # formula can exceed s for very young cards), hence the min().
        fail = replace(base, state=RELEARNING, lapses=card.lapses + 1, scheduled_days=0,
                       difficulty=self.next_difficulty(d, AGAIN),
                       stability=max(min(self.next_forget_stability(d, s, r_now), s), 0.1),
                       due=now + self.good_secs)
        out[AGAIN] = fail
        cards = {}
        for r in (HARD, GOOD, EASY):
            cards[r] = replace(base, difficulty=self.next_difficulty(d, r),
                               stability=self.next_recall_stability(d, s, r_now, r))
        hard = self.next_interval(cards[HARD].stability)
        good = self.next_interval(cards[GOOD].stability)
        # Keep Hard < Good < Easy so the buttons always mean something, but never
        # push past the configured ceiling.
        hard = min(hard, good)
        good = min(max(good, hard + 1), self.max_interval)
        easy = min(max(self.next_interval(cards[EASY].stability), good + 1), self.max_interval)
        out[HARD] = self._graduate(cards[HARD], now, hard)
        out[GOOD] = self._graduate(cards[GOOD], now, good)
        out[EASY] = self._graduate(cards[EASY], now, easy)
        return out

    def answer(self, card: CardState, rating: int, now: float) -> CardState:
        if rating not in RATINGS:
            raise ValueError(f"rating must be 1-4, got {rating!r}")
        return self.preview(card, now)[rating]


def interval_text(seconds: float) -> str:
    """Compact human interval: 45s, 10m, 3h, 4d, 2.5mo, 1.2y."""
    seconds = max(seconds, 0)
    if seconds < 60:
        return f"{int(round(seconds))}s"
    if seconds < 3600:
        return f"{int(round(seconds / 60))}m"
    if seconds < DAY:
        return f"{int(round(seconds / 3600))}h"
    days = seconds / DAY
    if days < 30.5:
        return f"{int(round(days))}d"
    if days < 365:
        return f"{days / 30.4:.1f}mo".replace(".0mo", "mo")
    return f"{days / 365:.1f}y".replace(".0y", "y")


def due_text(card: CardState, now: float) -> str:
    """How far away a freshly scheduled card is: '10m' for a learning step, '4d' for a review."""
    if card.state == REVIEW:
        return interval_text(card.scheduled_days * DAY)
    return interval_text(card.due - now)


def maturity(card: CardState) -> str:
    """Coarse bucket used for colouring: new / learning / young / mature."""
    if card.state == NEW:
        return "new"
    if card.state in (LEARNING, RELEARNING):
        return "learning"
    return "mature" if card.scheduled_days >= MATURE_DAYS else "young"
