"""The learner's state: SRS cards, review log, settings, XP, daily totals and notes.

Stored in a small SQLite file (userdata/progress.db). Cards are keyed by a
stable identity - the word's ``key`` or the kanji character - so the content
database can be rebuilt without losing progress.
"""
from __future__ import annotations

import json
import random
import shutil
import sqlite3
import time
from dataclasses import dataclass, replace
from pathlib import Path

from . import srs
from .content import Content, Kanji, Word
from .phrases import Phrase, PhraseBook
from .srs import CardState, Scheduler

VOCAB, KANJI, PHRASE = "vocab", "kanji", "phrase"
ACTIVE, SUSPENDED, KNOWN = 0, 1, 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    kind TEXT NOT NULL,                 -- 'vocab' | 'kanji' | 'phrase'
    item TEXT NOT NULL,                 -- word key, kanji character, or phrase id
    state INTEGER NOT NULL,
    due REAL NOT NULL,
    stability REAL NOT NULL,
    difficulty REAL NOT NULL,
    reps INTEGER NOT NULL,
    lapses INTEGER NOT NULL,
    last_review REAL NOT NULL,
    scheduled_days INTEGER NOT NULL,
    flag INTEGER NOT NULL DEFAULT 0,    -- 0 active, 1 suspended, 2 known (never asked)
    created REAL NOT NULL,
    PRIMARY KEY (kind, item)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS revlog (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    item TEXT NOT NULL,
    rating INTEGER NOT NULL,
    state INTEGER NOT NULL,             -- state before the answer
    elapsed_days INTEGER NOT NULL,
    scheduled_days INTEGER NOT NULL,    -- interval chosen by this answer
    duration_ms INTEGER NOT NULL,
    mode TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS revlog_ts ON revlog(ts);
CREATE TABLE IF NOT EXISTS daily (
    day INTEGER PRIMARY KEY,            -- study-day ordinal (days roll over at 4 am)
    reviews INTEGER NOT NULL DEFAULT 0,
    correct INTEGER NOT NULL DEFAULT 0,
    new_vocab INTEGER NOT NULL DEFAULT 0,
    new_kanji INTEGER NOT NULL DEFAULT 0,
    new_phrase INTEGER NOT NULL DEFAULT 0,
    xp INTEGER NOT NULL DEFAULT 0,
    seconds INTEGER NOT NULL DEFAULT 0,
    best_combo INTEGER NOT NULL DEFAULT 0,
    kanji_written INTEGER NOT NULL DEFAULT 0,
    battles_won INTEGER NOT NULL DEFAULT 0,
    quests TEXT NOT NULL DEFAULT '[]'   -- ids of quests already rewarded
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notes (
    kind TEXT NOT NULL, item TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (kind, item)
);
"""

DEFAULTS: dict = {
    "new_vocab_per_day": 15,
    "new_kanji_per_day": 5,
    "new_phrase_per_day": 10,
    "review_cap": 200,
    "retention": 0.90,
    "vocab_mode": "recognition",        # recognition | listening | recall | mixed
    "kanji_mode": "recognition",        # recognition | writing | mixed
    "phrase_mode": "recognition",       # recognition | recall | mixed
    "typing": False,                    # type the reading before revealing
    "levels": [5, 4, 3, 2, 1, 0],       # which word lists new vocabulary is drawn from (0 = common extras)
    "order": "course",                  # course (JLPT order) | frequency
    "kanji_from_vocab": True,           # introduce the kanji of words being studied first
    "voice": "nanami",                  # nanami | keita | offline
    "speech_rate": 0,                   # percent, -50 .. +50
    "autoplay": True,
    "sfx_volume": 0.5,
    "show_romaji": True,
    "furigana": True,
    "petals": True,
    "daily_goal": 50,                   # cards per day for the daruma
    "fullscreen": True,
    "ui_scale": 1.0,                    # whole-app zoom, 0.85 .. 1.75
    "loupe_factor": 2.25,                # magnifier zoom loop strength
    "auto_translate_ocr": True,         # fetch EN gloss after OCR when online
    "detail_ro_glosses": False,         # show EN→RO glosses under JA meanings in 詳細
    "rail_mode": "ja",                  # ja = lexicon detail | en_ro = English→Romanian rail
    "ffmpeg_path": "",                  # optional path to ffmpeg.exe or its folder
    "lmstudio_enabled": False,          # use LM Studio for Immersion EN drafts
    "lmstudio_url": "http://127.0.0.1:1234/v1",
    "lmstudio_model": "",               # empty = whatever LM Studio has loaded
    "immersion_video_mode": "window",   # window = separate VLC | embed = in-app
}

XP_FOR_RATING = {srs.AGAIN: 2, srs.HARD: 6, srs.GOOD: 10, srs.EASY: 12}
XP_NEW_ITEM = 5

# (minimum level, Japanese title, English title)
RANKS = [
    (1, "初心者", "Novice"), (3, "見習い", "Apprentice"), (6, "学生", "Student"), (10, "旅人", "Traveller"),
    (15, "浪人", "Rōnin"), (20, "侍", "Samurai"), (30, "達人", "Expert"), (40, "師範", "Master"),
    (50, "仙人", "Sage"), (65, "伝説", "Legend"),
]


def xp_to_reach(level: int) -> int:
    """Total XP needed to be at ``level`` (level 1 = 0, 2 = 100, 3 = 300, 4 = 600 ...)."""
    return 50 * level * (level - 1)


def level_for_xp(xp: int) -> int:
    level = 1
    while xp >= xp_to_reach(level + 1):
        level += 1
    return level


def rank_for_level(level: int) -> tuple[str, str]:
    title = RANKS[0]
    for r in RANKS:
        if level >= r[0]:
            title = r
    return title[1], title[2]


@dataclass(frozen=True)
class Card:
    kind: str
    item: str
    s: CardState
    flag: int = ACTIVE
    created: float = 0.0

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind, self.item)


@dataclass(frozen=True)
class Quest:
    id: str
    jp: str
    en: str
    metric: str
    target: int
    reward: int


# (id stem, Japanese, English, daily metric, targets, XP per target)
_QUEST_POOL = [
    ("review", "復習を{n}枚こなす", "Review {n} cards", "reviews", (20, 40, 60), (40, 70, 100)),
    ("vocab", "新しい単語を{n}個学ぶ", "Learn {n} new words", "new_vocab", (5, 10, 15), (40, 70, 100)),
    ("kanji", "新しい漢字を{n}字学ぶ", "Learn {n} new kanji", "new_kanji", (3, 5), (50, 80)),
    ("combo", "{n}連続正解する", "Answer {n} in a row correctly", "best_combo", (10, 20), (40, 80)),
    ("write", "漢字を{n}字書く", "Write {n} kanji from memory", "kanji_written", (3, 5), (50, 80)),
    ("battle", "妖怪バトルに{n}回勝つ", "Win {n} yōkai battle(s)", "battles_won", (1, 2), (60, 100)),
    ("time", "{n}分間修行する", "Train for {n} minutes", "minutes", (10, 20), (40, 80)),
]


class Progress:
    def __init__(self, path: Path, content: Content) -> None:
        self.path = path
        self.content = content
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()
        self.phrases = PhraseBook(self.db)
        self._settings = dict(DEFAULTS)
        for r in self.db.execute("SELECT key, value FROM kv WHERE key LIKE 'set.%'"):
            name = r["key"][4:]
            if name in DEFAULTS:
                self._settings[name] = json.loads(r["value"])
        self.cards: dict[tuple[str, str], Card] = {}
        for r in self.db.execute("SELECT * FROM cards"):
            s = CardState(r["state"], r["due"], r["stability"], r["difficulty"], r["reps"], r["lapses"],
                          r["last_review"], r["scheduled_days"])
            self.cards[(r["kind"], r["item"])] = Card(r["kind"], r["item"], s, r["flag"], r["created"])
        self._scheduler: Scheduler | None = None

    def close(self) -> None:
        try:
            self.db.commit()
            self.db.close()
        except sqlite3.ProgrammingError:
            pass

    def _migrate(self) -> None:
        """Add columns introduced after the first release."""
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(daily)")}
        if "new_phrase" not in cols:
            self.db.execute("ALTER TABLE daily ADD COLUMN new_phrase INTEGER NOT NULL DEFAULT 0")

    # ------------------------------------------------------------------ settings & key-value
    def setting(self, name: str):
        return self._settings[name]

    def set_setting(self, name: str, value) -> None:
        if name not in DEFAULTS:
            raise KeyError(name)
        self._settings[name] = value
        self._put("set." + name, value)
        if name == "retention":
            self._scheduler = None

    def _get(self, key: str, default=None):
        r = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def _put(self, key: str, value) -> None:
        self.db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    @property
    def scheduler(self) -> Scheduler:
        if self._scheduler is None:
            self._scheduler = Scheduler(retention=float(self.setting("retention")))
        return self._scheduler

    def today(self, now: float | None = None) -> int:
        return self.scheduler.day_index(time.time() if now is None else now)

    # ------------------------------------------------------------------ cards
    def card(self, kind: str, item: str) -> Card | None:
        return self.cards.get((kind, item))

    def _save(self, card: Card) -> None:
        s = card.s
        self.db.execute(
            "INSERT INTO cards (kind, item, state, due, stability, difficulty, reps, lapses, last_review,"
            " scheduled_days, flag, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(kind, item) DO UPDATE SET state=excluded.state, due=excluded.due,"
            " stability=excluded.stability, difficulty=excluded.difficulty, reps=excluded.reps,"
            " lapses=excluded.lapses, last_review=excluded.last_review, scheduled_days=excluded.scheduled_days,"
            " flag=excluded.flag",
            (card.kind, card.item, s.state, s.due, s.stability, s.difficulty, s.reps, s.lapses, s.last_review,
             s.scheduled_days, card.flag, card.created))
        self.cards[card.key] = card

    def status(self, kind: str, item: str) -> str:
        """unseen | new | learning | young | mature | known | suspended"""
        c = self.cards.get((kind, item))
        if c is None:
            return "unseen"
        if c.flag == KNOWN:
            return "known"
        if c.flag == SUSPENDED:
            return "suspended"
        return srs.maturity(c.s)

    def introduce(self, kind: str, item: str, now: float, delay: float = 45.0) -> Card:
        """Start learning an item: its first quiz comes up after ``delay`` seconds."""
        existing = self.cards.get((kind, item))
        if existing is not None and existing.flag == ACTIVE:
            return existing
        card = Card(kind, item, CardState(due=now + delay), ACTIVE, now)
        self._save(card)
        bump_key = {VOCAB: "new_vocab", KANJI: "new_kanji", PHRASE: "new_phrase"}.get(kind, "new_vocab")
        self._bump(now, **{bump_key: 1})
        self.add_xp(XP_NEW_ITEM, now)
        self.db.commit()
        return card

    def answer(self, card: Card, rating: int, now: float, duration_ms: int = 0, mode: str = "") -> Card:
        """Apply a rating: reschedule, log, and count it towards today."""
        before = card.s
        after = self.scheduler.answer(before, rating, now)
        elapsed = self.scheduler.day_index(now) - self.scheduler.day_index(before.last_review) if before.last_review else 0
        new_card = replace(card, s=after)
        self._save(new_card)
        self.db.execute(
            "INSERT INTO revlog (ts, kind, item, rating, state, elapsed_days, scheduled_days, duration_ms, mode)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (now, card.kind, card.item, rating, before.state, elapsed, after.scheduled_days, int(duration_ms), mode))
        self._bump(now, reviews=1, correct=int(rating > srs.AGAIN), seconds=min(int(duration_ms / 1000), 120))
        self.add_xp(XP_FOR_RATING[rating], now)
        self.db.commit()
        return new_card

    def set_flag(self, kind: str, item: str, flag: int, now: float | None = None) -> Card:
        """Suspend, un-suspend, or mark an item as already known."""
        now = time.time() if now is None else now
        card = self.cards.get((kind, item))
        if card is None:
            card = Card(kind, item, CardState(due=now), flag, now)
        else:
            card = replace(card, flag=flag)
        self._save(card)
        self.db.commit()
        return card

    def forget(self, kind: str, item: str) -> None:
        """Remove an item's card entirely so it becomes unseen again."""
        self.cards.pop((kind, item), None)
        self.db.execute("DELETE FROM cards WHERE kind=? AND item=?", (kind, item))
        self.db.commit()

    def mark_level_known(self, level: int, now: float | None = None) -> int:
        """Mark every unseen word of a JLPT level as known (for learners who are past it)."""
        now = time.time() if now is None else now
        count = 0
        for w in self.content.words:
            if w.level == level and (VOCAB, w.key) not in self.cards:
                self._save(Card(VOCAB, w.key, CardState(due=now), KNOWN, now))
                count += 1
        self.db.commit()
        return count

    # ------------------------------------------------------------------ queues
    def due_reviews(self, kind: str, now: float) -> list[Card]:
        out = [c for c in self.cards.values()
               if c.kind == kind and c.flag == ACTIVE and c.s.state == srs.REVIEW and c.s.due <= now]
        # most forgotten first, so a capped session spends itself where it matters
        out.sort(key=lambda c: self.scheduler.retrievability(c.s, now))
        return out

    def in_learning(self, kind: str) -> list[Card]:
        """Cards mid-way through same-day steps (including lessons not yet quizzed)."""
        out = [c for c in self.cards.values()
               if c.kind == kind and c.flag == ACTIVE and c.s.state != srs.REVIEW]
        out.sort(key=lambda c: c.s.due)
        return out

    def new_today(self, kind: str, now: float) -> int:
        row = self.day_row(self.today(now))
        key = {VOCAB: "new_vocab", KANJI: "new_kanji", PHRASE: "new_phrase"}.get(kind, "new_vocab")
        return int(row.get(key, 0))

    def new_allowance(self, kind: str, now: float) -> int:
        setting = {
            VOCAB: "new_vocab_per_day",
            KANJI: "new_kanji_per_day",
            PHRASE: "new_phrase_per_day",
        }.get(kind, "new_vocab_per_day")
        return max(int(self.setting(setting)) - self.new_today(kind, now), 0)

    def unseen_vocab(self) -> list[Word]:
        levels = set(self.setting("levels"))
        pool = self.content.by_frequency if self.setting("order") == "frequency" else self.content.words
        return [w for w in pool if w.level in levels and (VOCAB, w.key) not in self.cards]

    def unseen_kanji(self) -> list[Kanji]:
        course = [k for k in self.content.course if (KANJI, k.ch) not in self.cards]
        if not self.setting("kanji_from_vocab"):
            return course
        wanted: set[str] = set()
        for (kind, item), c in self.cards.items():
            if kind == VOCAB and c.flag != SUSPENDED:
                w = self.content.word_by_key(item)
                if w is not None:
                    wanted.update(w.kanji)
        return [k for k in course if k.ch in wanted] + [k for k in course if k.ch not in wanted]

    def unseen_phrases(self) -> list[Phrase]:
        return [p for p in self.phrases.all() if (PHRASE, p.id) not in self.cards]

    def next_new(self, kind: str, count: int) -> list[str]:
        if count <= 0:
            return []
        if kind == VOCAB:
            return [w.key for w in self.unseen_vocab()[:count]]
        if kind == PHRASE:
            return [p.id for p in self.unseen_phrases()[:count]]
        return [k.ch for k in self.unseen_kanji()[:count]]

    def counts(self, kind: str, now: float) -> dict[str, int]:
        """What is waiting right now: due reviews, cards in learning, new items still allowed today."""
        if kind == VOCAB:
            unseen = len(self.unseen_vocab())
        elif kind == PHRASE:
            unseen = len(self.unseen_phrases())
        else:
            unseen = len(self.unseen_kanji())
        return {
            "review": len(self.due_reviews(kind, now)),
            "learning": len(self.in_learning(kind)),
            "new": min(self.new_allowance(kind, now), unseen),
        }

    # ------------------------------------------------------------------ daily totals, XP, streak
    def day_row(self, day: int) -> dict:
        r = self.db.execute("SELECT * FROM daily WHERE day=?", (day,)).fetchone()
        if r is None:
            return {"day": day, "reviews": 0, "correct": 0, "new_vocab": 0, "new_kanji": 0, "new_phrase": 0,
                    "xp": 0, "seconds": 0, "best_combo": 0, "kanji_written": 0, "battles_won": 0, "quests": []}
        d = dict(r)
        d.setdefault("new_phrase", 0)
        d["quests"] = json.loads(d["quests"])
        return d

    def _bump(self, now: float, **amounts: int) -> None:
        day = self.today(now)
        self.db.execute("INSERT OR IGNORE INTO daily (day) VALUES (?)", (day,))
        for column, amount in amounts.items():
            self.db.execute(f"UPDATE daily SET {column} = {column} + ? WHERE day=?", (amount, day))

    def record(self, now: float, **amounts: int) -> None:
        """Add to today's counters (seconds, kanji_written, battles_won)."""
        self._bump(now, **amounts)
        self.db.commit()

    def record_combo(self, combo: int, now: float) -> None:
        day = self.today(now)
        self.db.execute("INSERT OR IGNORE INTO daily (day) VALUES (?)", (day,))
        self.db.execute("UPDATE daily SET best_combo = MAX(best_combo, ?) WHERE day=?", (combo, day))
        self.db.commit()

    @property
    def xp(self) -> int:
        return int(self._get("xp", 0))

    def add_xp(self, amount: int, now: float) -> None:
        if amount:
            self._put("xp", self.xp + int(amount))
            self._bump(now, xp=int(amount))
            self.db.commit()

    def level_info(self) -> dict:
        xp = self.xp
        level = level_for_xp(xp)
        lo, hi = xp_to_reach(level), xp_to_reach(level + 1)
        jp, en = rank_for_level(level)
        return {"xp": xp, "level": level, "into": xp - lo, "span": hi - lo, "rank_jp": jp, "rank_en": en}

    def streak(self, now: float) -> int:
        """Consecutive study days up to today (today may still be empty)."""
        today = self.today(now)
        days = {r["day"] for r in self.db.execute(
            "SELECT day FROM daily WHERE reviews > 0 OR new_vocab > 0 OR new_kanji > 0 OR new_phrase > 0"
        )}
        day = today if today in days else today - 1
        n = 0
        while day in days:
            n += 1
            day -= 1
        return n

    def goal_progress(self, now: float) -> tuple[int, int]:
        row = self.day_row(self.today(now))
        return row["reviews"] + row["new_vocab"] + row["new_kanji"] + row.get("new_phrase", 0), int(self.setting("daily_goal"))

    # ------------------------------------------------------------------ quests
    def quests(self, now: float) -> list[tuple[Quest, int, bool]]:
        """Today's three quests as (quest, progress, already rewarded)."""
        day = self.today(now)
        rng = random.Random(day * 7919)
        row = self.day_row(day)
        out = []
        for stem, jp, en, metric, targets, rewards in rng.sample(_QUEST_POOL, 3):
            i = rng.randrange(len(targets))
            n = targets[i]
            q = Quest(f"{stem}{n}", jp.format(n=n), en.format(n=n), metric, n, rewards[i])
            value = row["seconds"] // 60 if metric == "minutes" else row[metric]
            out.append((q, min(value, n), q.id in row["quests"]))
        return out

    def claim_quests(self, now: float) -> list[Quest]:
        """Reward quests completed since the last call; returns the newly completed ones."""
        day = self.today(now)
        done = []
        claimed = list(self.day_row(day)["quests"])
        for q, value, rewarded in self.quests(now):
            if value >= q.target and not rewarded:
                claimed.append(q.id)
                done.append(q)
        if done:
            self.db.execute("INSERT OR IGNORE INTO daily (day) VALUES (?)", (day,))
            self.db.execute("UPDATE daily SET quests=? WHERE day=?", (json.dumps(claimed), day))
            self.db.commit()
            for q in done:
                self.add_xp(q.reward, now)
        return done

    # ------------------------------------------------------------------ statistics
    def history(self, days: int, now: float) -> list[dict]:
        """One row per day for the last ``days`` days, oldest first (empty days included)."""
        today = self.today(now)
        return [self.day_row(d) for d in range(today - days + 1, today + 1)]

    def forecast(self, days: int, now: float) -> list[int]:
        """Reviews falling due on each of the next ``days`` days (index 0 = today, incl. overdue)."""
        today = self.today(now)
        out = [0] * days
        for c in self.cards.values():
            if c.flag != ACTIVE or c.s.state != srs.REVIEW:
                continue
            offset = max(self.scheduler.day_index(c.s.due) - today, 0)
            if offset < days:
                out[offset] += 1
        return out

    def status_counts(self, kind: str) -> dict[int, dict[str, int]]:
        """Per level: how many items are unseen / learning / young / mature / known."""
        out: dict[int, dict[str, int]] = {}
        if kind == VOCAB:
            items = ((w.level, w.key) for w in self.content.words)
        else:
            items = ((k.jlpt, k.ch) for k in self.content.course)
        for level, item in items:
            bucket = out.setdefault(level, {"total": 0, "unseen": 0, "learning": 0, "young": 0, "mature": 0, "known": 0})
            st = self.status(kind, item)
            st = {"new": "learning", "suspended": "unseen"}.get(st, st)
            bucket[st] += 1
            bucket["total"] += 1
        return out

    def learned_count(self, kind: str) -> int:
        return sum(1 for c in self.cards.values()
                   if c.kind == kind and (c.flag == KNOWN or (c.flag == ACTIVE and c.s.state == srs.REVIEW)))

    def retention(self, days: int, now: float) -> tuple[int, int]:
        """(remembered, total) for reviews of graduated cards in the last ``days`` days."""
        since = now - days * srs.DAY
        r = self.db.execute("SELECT SUM(rating > 1) AS ok, COUNT(*) AS n FROM revlog WHERE ts >= ? AND state = ?",
                            (since, srs.REVIEW)).fetchone()
        return int(r["ok"] or 0), int(r["n"] or 0)

    def totals(self) -> dict:
        r = self.db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(duration_ms), 0) AS ms FROM revlog").fetchone()
        d = self.db.execute("SELECT COUNT(*) AS days FROM daily WHERE reviews > 0").fetchone()
        return {"reviews": r["n"], "seconds": int(r["ms"] / 1000), "days": d["days"]}

    def leeches(self, kind: str, limit: int = 12) -> list[Card]:
        """The items forgotten most often."""
        out = [c for c in self.cards.values() if c.kind == kind and c.flag == ACTIVE and c.s.lapses > 0]
        out.sort(key=lambda c: (-c.s.lapses, c.s.stability))
        return out[:limit]

    # ------------------------------------------------------------------ notes
    def note(self, kind: str, item: str) -> str:
        r = self.db.execute("SELECT text FROM notes WHERE kind=? AND item=?", (kind, item)).fetchone()
        return r["text"] if r else ""

    def set_note(self, kind: str, item: str, text: str) -> None:
        if text.strip():
            self.db.execute("INSERT INTO notes (kind, item, text) VALUES (?,?,?)"
                            " ON CONFLICT(kind, item) DO UPDATE SET text=excluded.text", (kind, item, text))
        else:
            self.db.execute("DELETE FROM notes WHERE kind=? AND item=?", (kind, item))
        self.db.commit()

    # ------------------------------------------------------------------ housekeeping
    def backup(self, folder: Path, keep: int = 7) -> Path | None:
        """Copy the progress file once per day; keeps the most recent ``keep`` copies."""
        if not self.cards:
            return None
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"progress-{time.strftime('%Y%m%d')}.db"
        if dest.exists():
            return None
        self.db.commit()
        target = sqlite3.connect(dest)
        with target:
            self.db.backup(target)
        target.close()
        for old in sorted(folder.glob("progress-*.db"))[:-keep]:
            old.unlink(missing_ok=True)
        return dest

    def reset_all(self, folder: Path) -> None:
        """Wipe all progress (a safety copy is written first)."""
        folder.mkdir(parents=True, exist_ok=True)
        self.db.commit()
        shutil.copy2(self.path, folder / f"before-reset-{time.strftime('%Y%m%d-%H%M%S')}.db")
        for table in ("cards", "revlog", "daily", "notes"):
            self.db.execute(f"DELETE FROM {table}")
        self.db.execute("DELETE FROM kv WHERE key = 'xp'")
        self.db.commit()
        self.cards.clear()
