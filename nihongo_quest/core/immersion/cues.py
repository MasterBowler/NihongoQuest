"""Timed subtitle cues."""
from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_right


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str


@dataclass
class CueTrack:
    cues: list[Cue]
    language: str = ""
    title: str = ""

    def __post_init__(self) -> None:
        self.cues = sorted(self.cues, key=lambda c: (c.start_ms, c.end_ms))
        self._starts = [c.start_ms for c in self.cues]

    def at(self, time_ms: int) -> Cue | None:
        return active_cue(self.cues, time_ms, starts=self._starts)


def active_cue(cues: list[Cue], time_ms: int, starts: list[int] | None = None) -> Cue | None:
    """Return the last cue whose start ≤ time < end."""
    if not cues:
        return None
    starts = starts if starts is not None else [c.start_ms for c in cues]
    i = bisect_right(starts, time_ms) - 1
    while i >= 0:
        c = cues[i]
        if c.start_ms <= time_ms < c.end_ms:
            return c
        if c.end_ms <= time_ms:
            break
        i -= 1
    return None
