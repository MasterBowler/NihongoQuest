"""Read-only access to data/content.db (vocabulary, example sentences, kanji, strokes).

The 10,000 words are loaded into memory once; kanji, strokes and sentences are
fetched on demand and cached.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import kana as K

LEVEL_NAMES = {5: "N5", 4: "N4", 3: "N3", 2: "N2", 1: "N1", 0: "＋"}
LEVEL_ORDER = (5, 4, 3, 2, 1, 0)

# Short learner-facing names for the most frequent JMdict part-of-speech codes;
# anything else falls back to the dictionary's own description.
POS_SHORT = {
    "n": "noun", "pn": "pronoun", "adv": "adverb", "adv-to": "adverb (と)", "adj-i": "い-adj", "adj-ix": "い-adj",
    "adj-na": "な-adj", "adj-no": "の-adj", "adj-pn": "pre-noun", "adj-t": "たる-adj", "adj-f": "pre-noun",
    "v1": "ichidan verb", "v1-s": "ichidan verb", "vk": "irregular verb", "vs": "する verb", "vs-i": "する verb",
    "vs-s": "する verb", "vz": "ずる verb", "vt": "transitive", "vi": "intransitive", "exp": "expression",
    "int": "interjection", "conj": "conjunction", "prt": "particle", "suf": "suffix", "pref": "prefix",
    "n-suf": "noun suffix", "n-pref": "noun prefix", "ctr": "counter", "num": "numeral", "aux": "auxiliary",
    "aux-v": "auxiliary verb", "aux-adj": "auxiliary adj", "cop": "copula", "n-adv": "adverbial noun",
    "n-t": "time noun", "unc": "",
}
MISC_SHORT = {
    "uk": "usually kana", "hon": "honorific", "hum": "humble", "pol": "polite", "col": "colloquial", "fam": "familiar",
    "abbr": "abbreviation", "on-mim": "sound word", "male": "male speech", "fem": "female speech", "sl": "slang",
    "arch": "archaic", "derog": "derogatory", "vulg": "vulgar", "form": "formal", "id": "idiom", "yoji": "four-kanji idiom",
    "chn": "children's word", "dated": "dated", "hist": "historical", "rare": "rare", "joc": "humorous", "m-sl": "manga slang",
}


@dataclass(frozen=True, slots=True)
class Word:
    id: int
    key: str
    word: str
    kana: str
    romaji: str
    kanji_form: str | None
    usually_kana: bool
    alt_kana: tuple[str, ...]
    meaning: str
    senses: tuple[dict, ...]
    pos: tuple[str, ...]
    level: int
    band: int
    zipf: float
    freq_rank: int
    furi: tuple[tuple[str, str], ...]
    pitch: tuple[int, ...]
    tts: str
    ambiguous: bool
    search: str = field(repr=False, compare=False, default="")

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES[self.level]

    @property
    def kanji(self) -> list[str]:
        """Kanji of the displayed form."""
        return K.kanji_in(self.word)

    @property
    def all_kanji(self) -> list[str]:
        """Kanji of the displayed form, then those only in the kanji spelling."""
        out = K.kanji_in(self.word)
        for c in K.kanji_in(self.kanji_form or ""):
            if c not in out:
                out.append(c)
        return out

    @property
    def readings(self) -> tuple[str, ...]:
        return (self.kana,) + self.alt_kana

    def accepts_reading(self, typed: str) -> bool:
        return any(K.reading_matches(typed, r) for r in self.readings)


@dataclass(frozen=True, slots=True)
class Example:
    jp: str
    en: str
    form: str
    furi: str
    checked: bool
    sense: int

    @property
    def segments(self) -> list[tuple[str, str]]:
        return K.parse_furigana(self.furi) if self.furi else [(self.jp, "")]


@dataclass(frozen=True, slots=True)
class Kanji:
    ch: str
    rank: int | None
    meanings: tuple[str, ...]
    on: tuple[str, ...]
    kun: tuple[str, ...]
    strokes: int
    grade: int
    jlpt: int
    freq: int
    radical: dict
    usage: tuple[dict, ...]

    @property
    def meaning(self) -> str:
        return self.meanings[0] if self.meanings else ""

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES[self.jlpt] if self.jlpt else ("常用" if 1 <= self.grade <= 8 else "＋")

    @property
    def grade_name(self) -> str:
        if 1 <= self.grade <= 6:
            return f"Grade {self.grade}"
        return {8: "Secondary school", 9: "Name kanji", 10: "Name kanji"}.get(self.grade, "Not in the Jōyō list")


@dataclass(frozen=True, slots=True)
class Strokes:
    ch: str
    paths: tuple[str, ...]
    groups: tuple[dict, ...]


class ContentError(RuntimeError):
    pass


class Content:
    def __init__(self, path: Path) -> None:
        if not path.exists():
            raise ContentError(f"{path} not found - run tools/fetch_sources.py and tools/build_data.py")
        self.db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.meta = {r["key"]: r["value"] for r in self.db.execute("SELECT key, value FROM meta")}
        self.pos_tags: dict[str, str] = json.loads(self.meta.get("pos_tags", "{}"))
        self.words: list[Word] = [self._word(r) for r in self.db.execute("SELECT * FROM words ORDER BY id")]
        self._by_id = {w.id: w for w in self.words}
        self._by_key = {w.key: w for w in self.words}
        self.by_frequency: list[Word] = sorted(self.words, key=lambda w: w.freq_rank)
        self.course: list[Kanji] = [self._kanji(r) for r in
                                    self.db.execute("SELECT * FROM kanji WHERE rank IS NOT NULL ORDER BY rank")]
        self._kanji_cache: dict[str, Kanji | None] = {k.ch: k for k in self.course}

    # ------------------------------------------------------------------ rows
    @staticmethod
    def _word(r: sqlite3.Row) -> Word:
        senses = tuple(json.loads(r["senses"]))
        glosses = " ".join(g for s in senses for g in s.get("gloss", []))
        search = "\n".join([r["word"], K.kata_to_hira(r["kana"]), K.romaji_key(r["romaji"]),
                            r["kanji_form"] or "", glosses.lower()])
        return Word(
            id=r["id"], key=r["key"], word=r["word"], kana=r["kana"], romaji=r["romaji"], kanji_form=r["kanji_form"],
            usually_kana=bool(r["usually_kana"]), alt_kana=tuple(json.loads(r["alt_kana"])), meaning=r["meaning"],
            senses=senses, pos=tuple(p for p in r["pos"].split(",") if p), level=r["level"], band=r["band"],
            zipf=r["zipf"], freq_rank=r["freq_rank"], furi=tuple(tuple(x) for x in json.loads(r["furi"])),
            pitch=tuple(int(x) for x in r["pitch"].split(",") if x), tts=r["tts"], ambiguous=bool(r["ambiguous"]),
            search=search,
        )

    @staticmethod
    def _kanji(r: sqlite3.Row) -> Kanji:
        return Kanji(
            ch=r["ch"], rank=r["rank"], meanings=tuple(json.loads(r["meanings"])), on=tuple(json.loads(r["on_yomi"])),
            kun=tuple(json.loads(r["kun_yomi"])), strokes=r["strokes"], grade=r["grade"], jlpt=r["jlpt"],
            freq=r["freq"], radical=json.loads(r["radical"]), usage=tuple(json.loads(r["usage"])),
        )

    # ------------------------------------------------------------------ words
    def word(self, word_id: int) -> Word | None:
        return self._by_id.get(word_id)

    def word_by_key(self, key: str) -> Word | None:
        return self._by_key.get(key)

    @lru_cache(maxsize=512)
    def examples(self, word_id: int) -> tuple[Example, ...]:
        rows = self.db.execute("SELECT jp, en, form, furi, checked, sense FROM examples WHERE word_id=? ORDER BY id",
                               (word_id,))
        return tuple(Example(r["jp"], r["en"], r["form"], r["furi"], bool(r["checked"]), r["sense"]) for r in rows)

    def search(self, query: str, pool: list[Word] | None = None, limit: int | None = None) -> list[Word]:
        """Words matching a query typed as kanji, kana, romaji or English.

        Exact and prefix matches on the Japanese forms come first, then whole-word
        English matches, then everything else in list order.
        """
        pool = self.words if pool is None else pool
        q = query.strip().lower()
        if not q:
            return pool[:limit] if limit else list(pool)
        is_ascii = all(ord(c) < 128 for c in q)
        needles = {q}
        if is_ascii:
            needles.add(K.romaji_key(q))
            kana = K.romaji_to_kana(q, final=True)
            if kana and all(K.is_kana(c) or c == "ー" for c in kana):
                needles.add(kana)
        else:
            needles.add(K.kata_to_hira(q))
        needles.discard("")
        scored = []
        for w in pool:
            hay = w.search
            if not any(n in hay for n in needles):
                continue
            jp = (w.word, K.kata_to_hira(w.kana), K.romaji_key(w.romaji), w.kanji_form or "")
            if any(n in jp for n in needles):
                rank = 0
            elif any(f.startswith(n) for n in needles for f in jp):
                rank = 1
            elif is_ascii and any(g.lower() in (q, "to " + q) for s in w.senses[:2] for g in s.get("gloss", [])):
                rank = 2
            elif any(n in f for n in needles for f in jp):
                rank = 3
            else:
                rank = 4
            scored.append((rank, w.id, w))
        scored.sort(key=lambda t: t[:2])
        out = [w for _, _, w in scored]
        return out[:limit] if limit else out

    def pos_label(self, code: str) -> str:
        if code in POS_SHORT:
            return POS_SHORT[code]
        if code.startswith("v5"):
            return "godan verb"
        return self.pos_tags.get(code, code)

    def pos_labels(self, codes) -> list[str]:
        out: list[str] = []
        for c in codes:
            label = self.pos_label(c)
            if label and label not in out:
                out.append(label)
        return out

    # ------------------------------------------------------------------ kanji
    def kanji(self, ch: str) -> Kanji | None:
        if ch not in self._kanji_cache:
            r = self.db.execute("SELECT * FROM kanji WHERE ch=?", (ch,)).fetchone()
            self._kanji_cache[ch] = self._kanji(r) if r else None
        return self._kanji_cache[ch]

    @lru_cache(maxsize=1024)
    def strokes(self, ch: str) -> Strokes | None:
        r = self.db.execute("SELECT paths, groups FROM strokes WHERE ch=?", (ch,)).fetchone()
        if not r:
            return None
        return Strokes(ch, tuple(json.loads(r["paths"])), tuple(json.loads(r["groups"])))

    @lru_cache(maxsize=512)
    def words_for_kanji(self, ch: str, headword_only: bool = True) -> tuple[tuple[Word, str], ...]:
        """Vocabulary containing a kanji, in learning order, with how the kanji is read there."""
        sql = "SELECT word_id, reading FROM kanji_words WHERE ch=?" + (" AND headword=1" if headword_only else "")
        rows = self.db.execute(sql + " ORDER BY word_id", (ch,)).fetchall()
        return tuple((self._by_id[r["word_id"]], r["reading"]) for r in rows if r["word_id"] in self._by_id)

    def reading_in_word(self, ch: str, word: Word) -> str:
        """How ``ch`` is read inside ``word`` ('' when the word's reading is irregular)."""
        for base, rt in word.furi:
            if base == ch:
                return rt
        return ""

    def search_kanji(self, query: str, pool: list[Kanji] | None = None) -> list[Kanji]:
        """Course kanji matching a character, an English meaning or a reading (kana or romaji)."""
        pool = self.course if pool is None else pool
        q = query.strip().lower()
        if not q:
            return list(pool)
        chars = set(K.kanji_in(q))
        if chars:
            return [k for k in pool if k.ch in chars]
        kana = K.kata_to_hira(q if not all(ord(c) < 128 for c in q) else K.romaji_to_kana(q, final=True))
        by_reading = all(K.is_hiragana(c) for c in kana) and bool(kana)
        out = []
        for k in pool:
            if any(q in m.lower() for m in k.meanings):
                out.append(k)
            elif by_reading and (any(K.kata_to_hira(o) == kana for o in k.on)
                                 or any(u.replace(".", "").strip("-") == kana or u.split(".")[0].strip("-") == kana
                                        for u in k.kun)):
                out.append(k)
        return out
