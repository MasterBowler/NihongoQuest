"""User-collected Japanese phrases (manual entry or OCR), stored in progress.db."""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass

from nihongo_quest.core import kana as K

PHRASE = "phrase"


@dataclass(frozen=True, slots=True)
class Phrase:
    id: str
    jp: str
    reading: str          # kana / mixed reading aid
    romaji: str
    en: str
    notes: str
    source: str           # manual | ocr | import
    created: float
    updated: float

    @property
    def display_jp(self) -> str:
        return self.jp

    def search_blob(self) -> str:
        return "\n".join([
            self.jp,
            K.kata_to_hira(self.reading),
            K.romaji_key(self.romaji),
            self.en.lower(),
            self.notes.lower(),
        ])


_ROMJI_ONLY = re.compile(r"^[A-Za-z0-9\s\-\.\,\!\?\'\"\:\;\(\)\/]+$")

# Common greetings where particle 「は」 is written wa in romaji.
_ROMAJI_FIXUPS = {
    "konnichiwa": "こんにちは",
    "konbanwa": "こんばんは",
    "dewa": "では",
    "soredewa": "それでは",
}


def normalize_jp_input(text: str) -> tuple[str, str, str]:
    """Turn typed Japanese (IME or romaji) into (jp, reading, romaji).

    If the line is mostly romaji, convert it to hiragana for ``jp``/``reading``.
    If it already contains kana/kanji, keep ``jp`` as typed and derive romaji
    from any kana present (best-effort).
    """
    raw = (text or "").strip()
    if not raw:
        return "", "", ""
    if _ROMJI_ONLY.match(raw) and any(c.isalpha() for c in raw):
        # Treat spaces as phrase breaks: convert each token.
        parts = []
        for token in re.split(r"(\s+)", raw):
            if token.isspace() or token == "":
                parts.append(token)
            else:
                key = re.sub(r"[^a-z]", "", token.lower())
                if key in _ROMAJI_FIXUPS:
                    parts.append(_ROMAJI_FIXUPS[key])
                else:
                    parts.append(K.romaji_to_kana(token, final=True))
        kana = "".join(parts).strip()
        return kana, kana, K.to_romaji(kana, final_wa=True)
    # Already Japanese script (or mixed).
    reading = "".join(c for c in K.kata_to_hira(raw) if K.is_kana(c) or c in "ー・ 　")
    # Prefer explicit reading later; for now derive romaji from kana-only subset.
    kana_only = "".join(c for c in K.kata_to_hira(raw) if K.is_kana(c) or c == "ー")
    romaji = K.to_romaji(kana_only, final_wa=True) if kana_only else ""
    return raw, reading.strip() or kana_only, romaji


class PhraseBook:
    """CRUD for the ``phrases`` table living inside the progress database."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS phrases (
        id TEXT PRIMARY KEY,
        jp TEXT NOT NULL,
        reading TEXT NOT NULL DEFAULT '',
        romaji TEXT NOT NULL DEFAULT '',
        en TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'manual',
        created REAL NOT NULL,
        updated REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS phrases_updated ON phrases(updated DESC);
    """

    def __init__(self, db) -> None:
        self.db = db
        self.db.executescript(self.SCHEMA)
        self.db.commit()

    def _row(self, r) -> Phrase:
        return Phrase(
            id=r["id"], jp=r["jp"], reading=r["reading"], romaji=r["romaji"],
            en=r["en"], notes=r["notes"], source=r["source"],
            created=r["created"], updated=r["updated"],
        )

    def all(self) -> list[Phrase]:
        rows = self.db.execute("SELECT * FROM phrases ORDER BY updated DESC")
        return [self._row(r) for r in rows]

    def get(self, phrase_id: str) -> Phrase | None:
        r = self.db.execute("SELECT * FROM phrases WHERE id=?", (phrase_id,)).fetchone()
        return self._row(r) if r else None

    def search(self, query: str) -> list[Phrase]:
        q = query.strip().lower()
        if not q:
            return self.all()
        needles = {q, K.romaji_key(q), K.kata_to_hira(q)}
        if all(ord(c) < 128 for c in q):
            kana = K.romaji_to_kana(q, final=True)
            if kana:
                needles.add(kana)
        out = []
        for p in self.all():
            blob = p.search_blob()
            if any(n and n in blob for n in needles):
                out.append(p)
        return out

    def add(
        self,
        jp: str,
        en: str = "",
        *,
        reading: str = "",
        romaji: str = "",
        notes: str = "",
        source: str = "manual",
        phrase_id: str | None = None,
        now: float | None = None,
    ) -> Phrase:
        now = time.time() if now is None else now
        jp = jp.strip()
        if not jp:
            raise ValueError("Japanese text is required")
        if not reading and not romaji:
            jp2, reading, romaji = normalize_jp_input(jp)
            jp = jp2 or jp
        elif not romaji and reading:
            romaji = K.to_romaji(K.kata_to_hira(reading), final_wa=True)
        elif not reading and romaji:
            reading = K.romaji_to_kana(romaji, final=True)
        pid = phrase_id or uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO phrases (id, jp, reading, romaji, en, notes, source, created, updated)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, jp, reading, romaji, en.strip(), notes.strip(), source, now, now),
        )
        self.db.commit()
        return self.get(pid)  # type: ignore[return-value]

    def update(self, phrase_id: str, **fields) -> Phrase:
        allowed = {"jp", "reading", "romaji", "en", "notes", "source"}
        sets = []
        vals = []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k}=?")
            vals.append(v.strip() if isinstance(v, str) else v)
        if not sets:
            phrase = self.get(phrase_id)
            if phrase is None:
                raise KeyError(phrase_id)
            return phrase
        sets.append("updated=?")
        vals.append(time.time())
        vals.append(phrase_id)
        self.db.execute(f"UPDATE phrases SET {', '.join(sets)} WHERE id=?", vals)
        self.db.commit()
        phrase = self.get(phrase_id)
        if phrase is None:
            raise KeyError(phrase_id)
        return phrase

    def delete(self, phrase_id: str) -> None:
        self.db.execute("DELETE FROM phrases WHERE id=?", (phrase_id,))
        self.db.commit()

    def count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) AS n FROM phrases").fetchone()["n"])
