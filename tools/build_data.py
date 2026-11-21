"""Build data/content.db, the read-only study database, from data/raw/.

Run tools/fetch_sources.py first. The build takes about a minute and writes a
short report to data/raw/build_report.txt.

What ends up in the database
  words     10,000 vocabulary items: the full JLPT N5-N1 word lists plus the most
            frequent common words that the JLPT lists leave out. Each has its
            written form, kana, romaji, glosses, part of speech, per-kanji
            furigana, pitch accent and a frequency rank.
  examples  example sentences (JMdict/Tatoeba) with furigana.
  kanji     every KANJIDIC character with readings/meanings; the Joyo kanji and
            every kanji used by the vocabulary form the ordered "kanji course".
  strokes   KanjiVG stroke paths and component groups for kanji and kana.
"""
from __future__ import annotations

import argparse
import bz2
import csv
import gzip
import json
import math
import re
import sqlite3
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nihongo_quest.core import kana as K  # noqa: E402
from nihongo_quest.core.conjugate import stems  # noqa: E402

RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "content.db"
TOTAL_WORDS = 10_000
SCHEMA_VERSION = 1

BAD_KANJI_TAGS = {"rK", "sK", "iK", "oK", "io"}
BAD_KANA_TAGS = {"sk", "ik", "ok", "rk"}
# Senses carrying these markers are moved behind the plain ones so a card never
# leads with an abbreviation or an archaic meaning.
MINOR_SENSE_MISC = {"abbr", "arch", "obs", "rare", "poet", "vulg", "X", "derog", "obsc",
                    "sl", "net-sl", "m-sl", "chn", "joc"}
# First-sense markers that make a word a poor pick for the "common words" tier.
# Abbreviations and slang stay in: アニメ and スマホ are abbreviations.
EXTRA_SKIP_MISC = (MINOR_SENSE_MISC - {"abbr", "sl", "m-sl"}) | {"sens", "dated"}
# The frequency corpus leans on the web, so adult terms rank high; the bonus
# tier of a study list is not the place for them.
EXTRA_SKIP_GLOSS = re.compile(
    r"\b(sex|sexual|sexually|rape|sperm|semen|condom|nude|nudity|porn\w*|erotic\w*|penis|vagina|genital\w*|"
    r"masturbat\w*|prostitut\w*|brothel|orgasm|lewd|pervert\w*|molest\w*|harem|nazi\w*|comfort women|"
    r"breasts?|busty|nipples?|friend with benefits)\b", re.I)
# Japanese towns and wards crowd the top of any frequency list; a handful are worth knowing.
EXTRA_PLACE_GLOSS = re.compile(r"\((city|ward|district|prefecture|town|former province|island, prefecture|area)\b", re.I)
EXTRA_PLACE_KEEP = {"東京", "大阪", "京都", "北海道", "沖縄"}
# Frequent only as a brand / given name, not as the dictionary word.
EXTRA_UNCOMMON_DENY = {"楽天", "太郎", "清水", "山下", "大島", "本田", "大宮", "白石", "大輔", "三重", "東日本",
                       "ヘンリー", "ブラウン", "アップル", "童貞"}
# Everyday words that the JLPT lists place late or leave out; they are studied with the N5 band.
BEGINNER_ESSENTIALS = {
    "ありがとう", "こんにちは", "こんばんは", "おはよう", "すみません", "さようなら", "お休み", "お願い", "お願いします",
    "ごめんなさい", "ごめん", "いただきます", "ごちそうさま", "はじめまして", "よろしく", "おめでとう", "ただいま", "お帰り",
    "日本", "日本語", "日本人", "東京", "顔", "母", "父", "本当に",
}
# The extra tier is for content words; grammar particles and affixes are left to grammar study.
EXTRA_CONTENT_POS = {"n", "adj-i", "adj-ix", "adj-na", "adj-no", "adj-pn", "adj-t", "adv", "adv-to", "v1", "v1-s",
                     "vk", "vs", "vs-i", "vs-s", "pn"}
EXTRA_SKIP_POS = {"exp", "prt", "aux", "aux-v", "aux-adj", "cop", "conj", "int", "pref", "suf", "ctr", "n-suf",
                  "n-pref", "unc", "num", "n-pr"}
PARTICLE_WA_POS = {"conj", "exp", "int", "adv", "prt"}

# JLPT rows whose dictionary entry in the source list is a different homophone
# than the word the list means (checked against the list's own definitions).
SEQ_OVERRIDES = {(4, "そう", ""): "2137720"}      # "so; really" rather than the auxiliary "seeming"

RADICAL_FALLBACK = {      # Kangxi radicals the Kanji alive table has no usable row for
    43: ("lame", "だいのまげあし"), 52: ("short thread", "いとがしら"), 92: ("fang", "きば"),
    97: ("melon", "うり"), 168: ("long", "ながい"), 178: ("tanned leather", "なめしがわ"),
}

_STOP = set("a an the to of in on at for and or be is are it that this with by from as one's oneself someone "
            "something etc eg esp usu not no do does".split())


def gloss_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", text.lower()) if t not in _STOP and len(t) > 1}

REPORT: list[str] = []


def note(*parts) -> None:
    line = " ".join(str(p) for p in parts)
    REPORT.append(line)


def log(*parts) -> None:
    print(*parts, flush=True)
    note(*parts)


# --------------------------------------------------------------------------- loaders

def read_zip_json(name: str):
    with zipfile.ZipFile(RAW / name) as z:
        with z.open(z.namelist()[0]) as fh:
            return json.loads(fh.read().decode("utf-8-sig"))


def load_frequency() -> dict[str, float]:
    try:
        from wordfreq import get_frequency_dict
    except ImportError:
        log("! wordfreq is not installed (pip install -r requirements-build.txt); frequency ranks will be empty")
        return {}
    return get_frequency_dict("ja", wordlist="large")


def load_jlpt_rows() -> list[tuple[int, str, str, str, str]]:
    rows = []
    for lvl in (5, 4, 3, 2, 1):
        with open(RAW / f"jlpt_n{lvl}.csv", encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                rows.append((lvl, r["jmdict_seq"].strip(), r["kana"].strip(), r["kanji"].strip(),
                             r["waller_definition"].strip()))
    return rows


def load_pitch() -> dict[tuple[str, str], str]:
    """(written form, hiragana reading) -> '0,2' accent positions (Kanjium)."""
    out: dict[tuple[str, str], str] = {}
    with open(RAW / "kanjium_accents.txt", encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            word, reading, acc = parts[0], parts[1], parts[2]
            nums = list(dict.fromkeys(re.findall(r"\d+", acc)))
            if not nums:
                continue
            reading = K.kata_to_hira(reading or word)
            out.setdefault((word, reading), ",".join(nums))
    return out


def load_transcriptions() -> dict[str, tuple[str, bool]]:
    """Tatoeba sentence id -> (furigana markup, reviewed by a human)."""
    out: dict[str, tuple[str, bool]] = {}
    with bz2.open(RAW / "tatoeba_jpn_transcriptions.tsv.bz2", "rt", encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 5 and parts[2] == "Hrkt":
                out[parts[0]] = (parts[4], bool(parts[3].strip()))
    return out


def load_word_furigana() -> dict[tuple[str, str], list]:
    out: dict[tuple[str, str], list] = {}
    for e in read_zip_json("jmdict-furigana.json.zip"):
        out[(e["text"], e["reading"])] = [[f["ruby"], f.get("rt", "")] for f in e["furigana"]]
    return out


# --------------------------------------------------------------------------- frequency

FREQ: dict[str, float] = {}


def zipf(freq: float) -> float:
    return round(math.log10(freq) + 9, 3) if freq > 0 else 0.0


def est_freq(text: str) -> float:
    """Frequency of a written form; multi-token forms are estimated from their rarest part."""
    f = FREQ.get(text)
    if f:
        return f
    n = len(text)
    if n < 2 or n > 14:
        return 0.0
    best: list[tuple[int, float] | None] = [None] * (n + 1)
    best[0] = (0, 1.0)
    for i in range(n):
        if best[i] is None:
            continue
        for j in range(i + 1, min(n, i + 8) + 1):
            f = FREQ.get(text[i:j])
            if not f:
                continue
            cand = (best[i][0] + 1, min(best[i][1], f))
            cur = best[j]
            if cur is None or cand[0] < cur[0] or (cand[0] == cur[0] and cand[1] > cur[1]):
                best[j] = cand
    if best[n] is None:
        return 0.0
    count, rarest = best[n]
    return rarest * (0.25 ** (count - 1))


def lemma_freq(form: str | None, kana: str, pos: list[str], estimate: bool = True) -> float:
    """Frequency of a dictionary word in one spelling, including its inflected stems (食べる + 食べ…).

    With ``estimate`` off only exact corpus tokens count, and of the stems only
    the first (the masu-stem), since te-form stems collide between verbs
    (分かっ belongs to both 分かる and 分かつ).
    """
    if not form:
        return 0.0
    total = est_freq(form) if estimate else FREQ.get(form, 0.0)
    found = stems(form, kana if K.has_kanji(form) else form, pos)
    for st in found if estimate else found[:1]:
        if len(st) == 1 and K.is_kana(st):
            continue                          # し, い … far too ambiguous
        total += FREQ.get(st, 0.0)
    return total


def is_katakana_word(text: str) -> bool:
    return bool(text) and all(K.is_katakana(c) for c in text)


def item_freq(it: dict, strict: bool = False) -> float:
    """Estimated frequency of a vocabulary item.

    ``strict`` is used when *choosing* words for the extra tier: only real
    corpus tokens count there, and a hiragana spelling is trusted only as far
    as the kanji spelling backs it up, because short hiragana strings collide
    with particles and verb stems (あり is rarely "ant").
    """
    pos = it["senses"][0]["pos"]
    word, kana, kform = it["word"], it["kana"], it["kanji_form"]
    if K.has_kanji(word):
        f = lemma_freq(word, kana, pos, estimate=not strict)
        forms = it["entry"]["kanji"]
        mine = next((k for k in forms if k["text"] == word), None)
        if mine is not None and not mine["common"] and any(k["common"] for k in forms):
            f *= 0.1      # a minor spelling of this word (円 for まる "circle"): the count belongs to its other reading
        return f
    kf = lemma_freq(kform, kana, pos, estimate=not strict) if kform else 0.0
    if len(word) == 1:
        return kf                             # a lone kana is never a reliable token (と, か …)
    f_kana = lemma_freq(word, kana, pos, estimate=not strict)
    if is_katakana_word(word) or not strict:
        return f_kana + kf
    if len(word) < 3:
        return 0.0
    return kf + min(f_kana, kf * 8) if kform else f_kana


def split_homographs(items: list[dict]) -> None:
    """Share out a corpus count between words that are written the same way.

    Kana homographs (居る / 要る -> いる): the count goes to the likeliest owner
    - the easier JLPT level, then the entry with more senses - and the others
    are ranked by their kanji spelling alone.
    Kanji homographs (上 = うえ / うわ / かみ): the reading from the easier
    level (or, within a level, the one more often seen in kana) keeps the
    count; the secondary readings are marked down.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        groups[it["word"]].append(it)

    def kanji_freq(it: dict) -> float:
        return lemma_freq(it["kanji_form"], it["kana"], it["senses"][0]["pos"])

    for word, grp in groups.items():
        if len(grp) < 2:
            continue
        if K.has_kanji(word):
            grp.sort(key=lambda it: (-it["level"], -FREQ.get(it["kana"], 0.0), it["seq"]))
            for other in grp[1:]:
                other["freq"] *= 0.15
        else:
            grp.sort(key=lambda it: (-it["level"], -len(it["senses"]), -kanji_freq(it), it["seq"]))
            for other in grp[1:]:
                other["freq"] = kanji_freq(other) or grp[0]["freq"] * 0.02


# --------------------------------------------------------------------------- vocabulary selection

class Dictionary:
    def __init__(self, data: dict) -> None:
        self.words = data["words"]
        self.tags = data["tags"]
        self.date = data.get("dictDate", "")
        self.by_id = {w["id"]: w for w in self.words}
        self.by_kanji: dict[str, list[dict]] = defaultdict(list)
        self.by_kana: dict[str, list[dict]] = defaultdict(list)
        for w in self.words:
            for k in w["kanji"]:
                self.by_kanji[k["text"]].append(w)
            for k in w["kana"]:
                self.by_kana[k["text"]].append(w)

    def readings_of(self, kanji_text: str) -> set[str]:
        """Every (non-obsolete) reading the dictionary knows for a written form."""
        out = set()
        for w in self.by_kanji.get(kanji_text, ()):
            for k in w["kana"]:
                if BAD_KANA_TAGS & set(k["tags"]):
                    continue
                if "*" in k["appliesToKanji"] or kanji_text in k["appliesToKanji"]:
                    out.add(K.kata_to_hira(k["text"]))
        return out

    def find(self, kanji: str, kana: str) -> dict | None:
        cands = [w for w in (self.by_kanji.get(kanji, []) if kanji else self.by_kana.get(kana, []))
                 if any(k["text"] == kana for k in w["kana"])]
        if not cands:
            return None
        cands.sort(key=lambda w: not is_common(w))
        return cands[0]


def is_common(entry: dict) -> bool:
    return any(k["common"] for k in entry["kanji"]) or any(k["common"] for k in entry["kana"])


def kana_applies(kana_el: dict, kanji_text: str) -> bool:
    return "*" in kana_el["appliesToKanji"] or kanji_text in kana_el["appliesToKanji"]


def pick_kanji(entry: dict, kana: str) -> str | None:
    """Best kanji spelling for a reading: a common, unmarked form the reading applies to."""
    kana_el = next((k for k in entry["kana"] if k["text"] == kana), None)
    for want_common in (True, False):
        for k in entry["kanji"]:
            if BAD_KANJI_TAGS & set(k["tags"]):
                continue
            if want_common and not k["common"]:
                continue
            if kana_el is None or kana_applies(kana_el, k["text"]):
                return k["text"]
        if is_common(entry):
            break          # a common word whose kanji are all uncommon is written in kana
    return None


def pack_senses(entry: dict, kanji_form: str | None, kana: str) -> list[dict]:
    def keep(s: dict, strict: bool) -> bool:
        if strict:
            if kanji_form and "*" not in s["appliesToKanji"] and kanji_form not in s["appliesToKanji"]:
                return False
            if "*" not in s["appliesToKana"] and kana not in s["appliesToKana"]:
                return False
        return any(g.get("lang", "eng") == "eng" for g in s["gloss"])

    senses = [s for s in entry["sense"] if keep(s, True)] or [s for s in entry["sense"] if keep(s, False)]
    out = []
    for s in senses:
        out.append({
            "pos": s["partOfSpeech"],
            "gloss": [g["text"] for g in s["gloss"] if g.get("lang", "eng") == "eng"],
            "misc": s["misc"],
            "field": s["field"],
            "info": s["info"],
            "dial": s["dialect"],
            "ex": s.get("examples") or [],
        })
    plain = [s for s in out if not MINOR_SENSE_MISC & set(s["misc"])]
    if plain and len(plain) < len(out):
        out = plain + [s for s in out if MINOR_SENSE_MISC & set(s["misc"])]
    return out


def make_item(entry: dict, level: int, kana: str, kanji_form: str | None, list_def: str = "") -> dict | None:
    senses = pack_senses(entry, kanji_form, kana)
    if not senses:
        return None
    # When the JLPT list defines the word by a later dictionary sense (あまり is
    # listed as "not very", the dictionary leads with "remainder"), keep that
    # sense right behind the primary one so the card shows both.
    jlpt_sense = None
    want = gloss_tokens(list_def) if list_def and not list_def.startswith("#") else set()
    if want and not want & gloss_tokens(" ".join(senses[0]["gloss"])):
        for i, s in enumerate(senses[1:], 1):
            if want & gloss_tokens(" ".join(s["gloss"])):
                senses.insert(1, senses.pop(i))
                jlpt_sense = 1
                break
    usually_kana = "uk" in senses[0]["misc"]
    form_tags = next((set(k["tags"]) for k in entry["kanji"] if k["text"] == kanji_form), set())
    rare_kanji = bool(form_tags & BAD_KANJI_TAGS)        # e.g. 居る: real, but nobody writes it that way
    word = kana if (usually_kana or not kanji_form or rare_kanji) else kanji_form
    return {
        "seq": int(entry["id"]), "level": level, "word": word, "kana": kana,
        "kanji_form": kanji_form, "uk": usually_kana, "senses": senses, "entry": entry,
        "alt_kana": [], "jlpt_sense": jlpt_sense,
    }


def gloss1(entry: dict) -> str:
    return "; ".join(g["text"] for g in entry["sense"][0]["gloss"][:2])


def resolve_kanji(d: "Dictionary", entry: dict, kana: str, listed: str, stats: Counter) -> str | None:
    """The kanji spelling to teach.

    The JLPT lists contain many old-fashioned spellings (明い, 集る, 朝御飯).
    Those are swapped for the dictionary's standard form, while deliberate
    distinctions between kanji (会う / 遭う, 町 / 街) are kept.
    """
    forms = {k["text"]: k for k in entry["kanji"]}
    k = forms.get(listed) if listed else None
    if k is None:
        if listed:
            stats["kanji not in entry"] += 1
            note(f"  kanji not in entry {entry['id']}: {listed} {kana}")
        return pick_kanji(entry, kana)
    kana_el = next((x for x in entry["kana"] if x["text"] == kana), None)
    standard = [x["text"] for x in entry["kanji"]
                if x["common"] and not BAD_KANJI_TAGS & set(x["tags"])
                and (kana_el is None or kana_applies(kana_el, x["text"]))]
    marked = bool(BAD_KANJI_TAGS & set(k["tags"]))
    if not marked and (k["common"] or not standard):
        return listed

    def switch(to: str, why: str) -> str:
        stats[f"spelling: {why}"] += 1
        note(f"  spelling ({why}): {listed} -> {to} ({kana})")
        return to

    mine = set(K.kanji_in(listed))
    for cand in standard:                       # same kanji, modern okurigana: 曲る -> 曲がる
        theirs = set(K.kanji_in(cand))
        if theirs and theirs <= mine:
            return switch(cand, "okurigana")
    if not standard:
        return listed                           # kept for reference; make_item shows the kana instead
    best = standard[0]
    if marked:                                  # rare or irregular kanji: 棄てる -> 捨てる
        return switch(best, "rare kanji")
    # An unmarked but uncommon spelling with different kanji (街 for 町): only
    # switch when the standard form clearly dominates and cannot be misread.
    if est_freq(best) >= 5 * est_freq(listed) and d.readings_of(best) == {K.kata_to_hira(kana)}:
        return switch(best, "dominant form")
    return listed


def select_jlpt(d: Dictionary) -> list[dict]:
    items: dict[tuple[int, str], dict] = {}
    stats = Counter()
    for level, seq, kana, kanji, list_def in load_jlpt_rows():
        seq = SEQ_OVERRIDES.get((level, kana, kanji), seq)
        entry = d.by_id.get(seq) if seq else d.find(kanji, kana)
        if entry is None:
            stats["no entry"] += 1
            note(f"  JLPT row without a dictionary entry: N{level} {kanji} {kana}")
            continue
        if not kanji and not is_common(entry):
            # A kana-only row pointing at an obscure entry while exactly one common
            # "usually written in kana" word has the same reading: the source list
            # picked the wrong homophone (これ -> "hey!" instead of "this").
            alts = [o for o in d.by_kana.get(kana, []) if o is not entry and "uk" in o["sense"][0]["misc"]
                    and any(k["text"] == kana and k["common"] for k in o["kana"])]
            if len(alts) == 1:
                stats["remapped homophone"] += 1
                note(f"  remapped N{level} {kana}: {entry['id']} ({gloss1(entry)}) -> {alts[0]['id']} ({gloss1(alts[0])})")
                entry = alts[0]
        kana_texts = [k["text"] for k in entry["kana"]]
        if kana not in kana_texts:
            other = d.find(kanji, kana) if kanji else None
            if other is not None:
                stats["entry found by spelling"] += 1
                note(f"  N{level} {kanji} {kana}: entry {entry['id']} lacks the reading, using {other['id']} ({gloss1(other)})")
                entry = other
            else:
                alt = next((k["text"] for k in entry["kana"] if not BAD_KANA_TAGS & set(k["tags"])), kana_texts[0])
                stats["kana replaced"] += 1
                note(f"  kana not in entry {entry['id']}: N{level} {kanji} {kana} -> {alt}")
                kana = alt
        kanji_form = resolve_kanji(d, entry, kana, kanji, stats)
        item = make_item(entry, level, kana, kanji_form, list_def)
        if item is None:
            stats["no senses"] += 1
            continue
        key = (item["seq"], item["word"])
        prev = items.get(key)
        if prev is None:
            items[key] = item
            continue
        stats["merged duplicates"] += 1
        if item["kana"] != prev["kana"] and item["kana"] not in prev["alt_kana"]:
            prev["alt_kana"].append(item["kana"])
        if item["level"] > prev["level"]:
            prev["level"] = item["level"]          # keep the easier level
        if not prev["kanji_form"] and item["kanji_form"]:
            prev["kanji_form"] = item["kanji_form"]
    log("JLPT selection:", len(items), "words;", dict(stats))
    return list(items.values())


_CLEAN_JP = re.compile(r"^[\u3041-\u30ff\u4e00-\u9fff々]+$")


def add_secondary_jlpt(d: Dictionary, items: list[dict]) -> list[dict]:
    """Fill gaps in the primary JLPT lists from a second transcription of the
    same source (the primary one is missing 母, 父, 顔 and a few hundred more).

    Only rows that are a single clean word are used, and only when the
    dictionary entry is not in the selection yet at any level.
    """
    have_seq = {it["seq"] for it in items}
    have_forms = {(it["word"], K.kata_to_hira(it["kana"])) for it in items}
    stats = Counter()
    added = []
    for lvl in (5, 4, 3, 2, 1):
        path = RAW / f"openanki_n{lvl}.csv"
        if not path.exists():
            log(f"! {path.name} is missing; run tools/fetch_sources.py")
            continue
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            expr, reading, meaning = r["expression"].strip(), r["reading"].strip(), r["meaning"].strip()
            if not _CLEAN_JP.match(expr) or not _CLEAN_JP.match(reading) or K.has_kanji(reading) or len(expr) < 2 and not K.has_kanji(expr):
                stats["not a single clean word"] += 1
                continue
            kanji = expr if K.has_kanji(expr) else ""
            if kanji:
                entry = d.find(kanji, reading)
            else:
                # written in kana in the list: prefer an entry that is itself written in kana
                cands = [w for w in d.by_kana.get(reading, []) if is_common(w)]
                cands.sort(key=lambda w: bool(w["kanji"]) and "uk" not in w["sense"][0]["misc"])
                entry = cands[0] if cands else None
            if entry is None or not is_common(entry):
                stats["no common dictionary entry"] += 1
                continue
            if int(entry["id"]) in have_seq:
                stats["already selected"] += 1
                continue
            item = make_item(entry, lvl, reading, resolve_kanji(d, entry, reading, kanji, stats), meaning)
            if item is None or (item["word"], K.kata_to_hira(reading)) in have_forms:
                continue
            have_seq.add(item["seq"])
            have_forms.add((item["word"], K.kata_to_hira(reading)))
            added.append(item)
            stats[f"added N{lvl}"] += 1
    log("second JLPT source:", len(added), "words added;", dict(stats))
    note("  added: " + " ".join(f"{it['word']}(N{it['level']})" for it in added))
    return added


def select_extra(d: Dictionary, jlpt: list[dict], count: int, kd: dict) -> list[dict]:
    """The most frequent content words that the JLPT lists do not cover.

    Candidates are the dictionary's "common" entries, plus unmarked entries
    that are nevertheless frequent in the corpus (忍者, コスプレ).
    """
    taken_seq = {it["seq"] for it in jlpt}
    taken_words = {it["word"] for it in jlpt} | {it["kanji_form"] for it in jlpt if it["kanji_form"]}
    jlpt_kana = {K.kata_to_hira(it["kana"]) for it in jlpt}
    cands = []
    skipped = Counter()
    uncommon_floor = 10 ** (4.0 - 9)

    def is_verb(it: dict) -> bool:
        return any(p.startswith("v") and p not in ("vs", "vt", "vi") for p in it["senses"][0]["pos"])

    for entry in d.words:
        if int(entry["id"]) in taken_seq:
            continue
        common = is_common(entry)
        kana_el = next((k for k in entry["kana"] if k["common"] and not BAD_KANA_TAGS & set(k["tags"])), None)
        if kana_el is None:
            kana_el = next((k for k in entry["kana"] if not BAD_KANA_TAGS & set(k["tags"])), None)
        if kana_el is None:
            continue
        kana = kana_el["text"]
        item = make_item(entry, 0, kana, pick_kanji(entry, kana))
        if item is None:
            continue
        first = item["senses"][0]
        pos = {p if not p.startswith("v5") else "v1" for p in first["pos"]}      # any godan verb counts as a verb
        if EXTRA_SKIP_MISC & set(first["misc"]):
            skipped["marked sense"] += 1
            continue
        if pos & EXTRA_SKIP_POS or not pos & EXTRA_CONTENT_POS:
            skipped["not a content word"] += 1
            continue
        w = item["word"]
        if len(w) == 1 and not K.is_kanji(w):
            skipped["single kana"] += 1
            continue
        if re.search(r"[0-9A-Za-zＡ-Ｚａ-ｚ０-９]", w):
            skipped["latin/digits"] += 1
            continue
        if w in taken_words:
            # Another reading of a word that is already in (主 has four); the
            # corpus cannot tell the readings apart, so these are left out.
            skipped["same spelling as a JLPT word"] += 1
            continue
        gloss = " ".join(first["gloss"])
        if EXTRA_SKIP_GLOSS.search(gloss):
            skipped["adult/sensitive"] += 1
            continue
        if EXTRA_PLACE_GLOSS.search(first["gloss"][0]) and w not in EXTRA_PLACE_KEEP:
            skipped["place name"] += 1
            continue
        item["freq"] = item_freq(item, strict=True)
        if len(w) == 1:
            # A lone kanji is over-counted (tokenizers split unknown compounds
            # into single characters, and the count covers every reading), so
            # it needs backing from its kana spelling: 顔/かお passes, 兵/つわもの does not.
            reading = K.kata_to_hira(kana)
            native = reading in {k.split(".")[0].strip("-") for k in kd.get(w, {}).get("kun", [])}
            if not native:
                item["freq"] *= 0.2
            elif reading in jlpt_kana or len(reading) < 2:
                item["freq"] = 0.0           # the kana spelling belongs to another word; nothing to go on
            else:
                item["freq"] = min(item["freq"], 30 * FREQ.get(reading, 0.0))
        if item["freq"] <= 0:
            skipped["not a reliable corpus token"] += 1
            continue
        if not common:
            # Unflagged entries: only clear-cut nouns, which keeps out inflected
            # forms (言える, 大きく), fragments (スマ) and personal names.
            plain_noun = set(first["pos"]) <= {"n", "vs", "vt", "vi", "adj-no", "adj-na"} and "n" in first["pos"]
            long_enough = len(w) >= (4 if is_katakana_word(w) else 2)
            named = (first["gloss"][0][:1].isupper() or re.search(r"name\)|surname|company\)", gloss)
                     or w in EXTRA_UNCOMMON_DENY)
            if item["freq"] < uncommon_floor or not plain_noun or not long_enough or named \
                    or not (K.has_kanji(w) or is_katakana_word(w)):
                continue
            item["uncommon"] = True
        cands.append(item)

    # Nouns that are just a verb's stem (生き, 落ち, 買い) get that verb's whole count.
    verb_stems = {st for it in jlpt + cands if is_verb(it)
                  for form in (it["word"], it["kanji_form"]) if form
                  for st in stems(form, it["kana"] if K.has_kanji(form) else form, it["senses"][0]["pos"])}
    kept, seen = [], set()
    for it in sorted(cands, key=lambda it: (-it["freq"], it["seq"])):
        if it["word"] in verb_stems and not is_verb(it):
            skipped["verb stem"] += 1
        elif it["word"] in seen:
            skipped["second reading of the same spelling"] += 1
        else:
            seen.add(it["word"])
            kept.append(it)
    cands = kept
    log(f"extra tier: {len(cands)} candidates, taking {count}; skipped {dict(skipped)}")
    note("  frequent words taken although the dictionary does not flag them as common:")
    note("    " + " ".join(it["word"] for it in cands[:count] if it.get("uncommon")))
    if len(cands) > count:
        note(f"  cut-off: the last word taken has zipf {zipf(cands[count - 1]['freq']):.2f}")
    return cands[:count]


# --------------------------------------------------------------------------- per-word enrichment

def short_meaning(it: dict) -> str:
    senses = it["senses"]
    text = "; ".join(senses[0]["gloss"][:3])
    if it.get("jlpt_sense"):
        text += " ／ " + "; ".join(senses[it["jlpt_sense"]]["gloss"][:2])
    return text


def romaji_for(it: dict) -> str:
    pos = set(it["senses"][0]["pos"])
    final_wa = (it["kana"].endswith("は") and it["word"].endswith("は") and len(it["kana"]) > 1
                and bool(pos & PARTICLE_WA_POS) and not pos & {"n", "v1", "v5r"})
    return K.to_romaji(it["kana"], final_wa=final_wa)


def tts_text(d: Dictionary, it: dict) -> str:
    """What to hand a speech engine: the written form when its reading is
    unambiguous (engines pick better pitch for it), otherwise the kana."""
    w = it["word"]
    if not K.has_kanji(w):
        return it["kana"]
    readings = d.readings_of(w)
    return w if readings == {K.kata_to_hira(it["kana"])} else it["kana"]


def find_pitch(pitch: dict, it: dict) -> str:
    reading = K.kata_to_hira(it["kana"])
    forms = [it["kanji_form"], it["word"], it["kana"], K.hira_to_kata(it["kana"])]
    forms += [k["text"] for k in it["entry"]["kanji"]]
    for f in forms:
        if f and (f, reading) in pitch:
            return pitch[(f, reading)]
    return ""


def collect_examples(it: dict, trans: dict, stats: Counter) -> list[dict]:
    out = []
    seen = set()
    for si, s in enumerate(it["senses"]):
        for ex in s["ex"]:
            jp = next((x["text"] for x in ex["sentences"] if x["lang"] == "jpn"), "")
            en = next((x["text"] for x in ex["sentences"] if x["lang"] == "eng"), "")
            if not jp or not en or jp in seen:
                continue
            seen.add(jp)
            tid = ex["source"]["value"] if ex.get("source", {}).get("type") == "tatoeba" else ""
            furi, checked = "", 0
            if tid in trans:
                markup, reviewed = trans[tid]
                if K.strip_furigana(markup) == jp:
                    furi, checked = markup, int(reviewed)
                    stats["furigana ok"] += 1
                else:
                    stats["furigana text mismatch"] += 1
            else:
                stats["no transcription"] += 1
            out.append({"sense": si, "jp": jp, "en": en, "form": ex.get("text", ""), "furi": furi,
                        "checked": checked, "tid": int(tid) if tid.isdigit() else None})
    # sentences for the meanings shown on the card first; then verified furigana, then shorter ones
    out.sort(key=lambda e: (e["sense"] > 1, -e["checked"], not e["furi"], len(e["jp"])))
    return out[:5]


# --------------------------------------------------------------------------- kanji

def load_radicals() -> dict[int, dict]:
    """Kangxi radical number -> {glyph, meaning, name}."""
    by_glyph: dict[str, tuple[str, str]] = {}
    with open(RAW / "kanjialive_radicals.csv", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["Origin"].strip() != "Kangxi":
                continue
            glyph = unicodedata.normalize("NFKC", r["Radical"].strip())
            by_glyph[glyph] = (r["Meaning"].strip(), r["Reading"].strip())
    out = {}
    for n in range(1, 215):
        glyph = unicodedata.normalize("NFKC", chr(0x2F00 + n - 1))
        meaning, name = by_glyph.get(glyph) or RADICAL_FALLBACK.get(n, ("", ""))
        out[n] = {"glyph": glyph, "meaning": meaning, "name": name}
    missing = [n for n, r in out.items() if not r["meaning"]]
    log(f"radicals: {214 - len(missing)} of 214 have meanings" + (f" (missing {missing})" if missing else ""))
    return out


def load_kanjivg() -> dict[str, dict]:
    """char -> {"paths": [d...], "groups": [component tree]} from KanjiVG."""
    with gzip.open(RAW / "kanjivg.xml.gz", "rt", encoding="utf-8") as fh:
        txt = fh.read()
    txt = txt.replace("kvg:", "kvg_")
    txt = re.sub(r"<!DOCTYPE[^\[>]*\[.*?\]>", "", txt, count=1, flags=re.S)
    root = ET.fromstring(txt)
    out: dict[str, dict] = {}
    for kel in root.iter("kanji"):
        try:
            ch = chr(int(kel.get("id").rsplit("_", 1)[-1], 16))
        except (TypeError, ValueError):
            continue
        paths: list[str] = []

        def walk(g) -> dict:
            node = {"el": g.get("kvg_element"), "orig": g.get("kvg_original"), "pos": g.get("kvg_position"),
                    "rad": g.get("kvg_radical"), "part": g.get("kvg_part"), "strokes": [], "children": []}
            for child in g:
                if child.tag == "path":
                    paths.append(child.get("d"))
                    node["strokes"].append(len(paths) - 1)
                elif child.tag == "g":
                    sub = walk(child)
                    node["children"].append(sub)
                    node["strokes"].extend(sub["strokes"])
            return node

        top = kel.find("g")
        if top is None:
            continue
        tree = walk(top)
        if not paths:
            continue
        out[ch] = {"paths": paths, "groups": named_components(tree, ch, depth=0)}
    return out


def named_components(node: dict, self_char: str, depth: int) -> list[dict]:
    """Named sub-groups of a KanjiVG node, with split parts merged and
    anonymous wrapper groups flattened."""
    found: list[dict] = []
    for ch in node["children"]:
        if ch["el"] and ch["el"] != self_char:
            found.append(ch)
        else:
            found.extend(named_components_raw(ch, self_char))
    merged: dict[str, dict] = {}
    order: list[str] = []
    for c in found:
        key = c["el"]
        if key in merged and c.get("part"):
            merged[key]["strokes"].extend(c["strokes"])
            merged[key]["children"].extend(c["children"])
            continue
        if key in merged:
            key = f"{key}#{len(order)}"       # the same shape used twice (林 = 木 + 木)
        merged[key] = {**c, "strokes": list(c["strokes"]), "children": list(c["children"])}
        order.append(key)
    out = []
    for key in order:
        c = merged[key]
        comp = {"el": c["el"], "strokes": sorted(c["strokes"])}
        if c.get("orig"):
            comp["orig"] = c["orig"]
        if c.get("pos"):
            comp["pos"] = c["pos"]
        if c.get("rad"):
            comp["rad"] = 1
        if depth < 1:
            sub = named_components(c, c["el"], depth + 1)
            if len(sub) > 1:
                comp["sub"] = sub
        out.append(comp)
    return out


def named_components_raw(node: dict, self_char: str) -> list[dict]:
    out = []
    for ch in node["children"]:
        if ch["el"] and ch["el"] != self_char:
            out.append(ch)
        else:
            out.extend(named_components_raw(ch, self_char))
    return out


_DEVOICE = str.maketrans("がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ", "かきくけこさしすせそたちつてとはひふへほはひふへほ")


def _reading_key(r: str) -> str:
    r = K.kata_to_hira(r)
    return (r[:1].translate(_DEVOICE) + r[1:]) if r else r


def classify_reading(rt: str, on: list[str], kun: list[str]) -> str:
    """Is this reading of a kanji inside a word one of its on or kun readings?
    Allows for rendaku (かみ -> がみ) and gemination (がく -> がっ)."""
    key = _reading_key(rt)

    def hit(base: str) -> bool:
        b = _reading_key(base)
        if not b:
            return False
        if key == b:
            return True
        return key.endswith("っ") and len(b) == len(key) and b[:-1] == key[:-1] and b[-1] in "くつちき"

    for o in on:
        if hit(o):
            return "on"
    for k in kun:
        k = k.strip("-")
        stem = _reading_key(k.split(".")[0])
        if hit(k.split(".")[0]) or hit(k.replace(".", "")):
            return "kun"
        # okurigana swallowed by the kanji: 物語 = もの + がたり (かた.る)
        if "." in k and stem and key.startswith(stem) and 0 < len(key) - len(stem) <= 2:
            return "kun"
    return ""


def component_meaning(el: str, orig: str | None, rad_by_glyph: dict, kd: dict) -> str:
    for g in (el, orig):
        if g and g in rad_by_glyph and rad_by_glyph[g]:
            return ", ".join(p.strip() for p in rad_by_glyph[g].split(",")[:2])
    for g in (el, orig):
        if g and g in kd and kd[g]["meanings"]:
            m = kd[g]["meanings"][0]
            return re.sub(r"\s*\(?(radical|no\.)[^)]*\)?", "", m).strip() or m
    return ""


def load_kanjidic() -> dict[str, dict]:
    out = {}
    for c in read_zip_json("kanjidic2-en.json.zip")["characters"]:
        rm = c.get("readingMeaning") or {}
        on, kun, meanings = [], [], []
        for g in rm.get("groups", []):
            for r in g.get("readings", []):
                if r["type"] == "ja_on":
                    on.append(r["value"])
                elif r["type"] == "ja_kun":
                    kun.append(r["value"])
            meanings += [m["value"] for m in g.get("meanings", []) if m.get("lang") == "en"]
        misc = c["misc"]
        rad = next((r["value"] for r in c.get("radicals", []) if r["type"] == "classical"), 0)
        out[c["literal"]] = {
            "meanings": meanings, "on": on, "kun": kun,
            "strokes": (misc.get("strokeCounts") or [0])[0],
            "grade": misc.get("grade") or 0,
            "freq": misc.get("frequency") or 0,
            "radical": rad,
        }
    return out


def order_course(course: set[str], level_of: dict[str, int], kd: dict, vg: dict) -> list[str]:
    """Learning order: JLPT N5 -> N1 -> the rest; frequent kanji first, and a
    kanji's building blocks (from the same level) always before the kanji itself."""
    def parts(ch: str) -> list[str]:
        out = []
        for g in vg.get(ch, {}).get("groups", []):
            for c in [g] + g.get("sub", []):
                for cand in (c["el"], c.get("orig")):
                    if cand and cand != ch and cand in course:
                        out.append(cand)
        return out

    def level_key(ch: str) -> int:
        lvl = level_of.get(ch, 0)
        if lvl:
            return 5 - lvl                       # N5 -> 0 … N1 -> 4
        return 5 if 1 <= kd[ch]["grade"] <= 8 else 6

    buckets: dict[int, list[str]] = defaultdict(list)
    for ch in course:
        buckets[level_key(ch)].append(ch)
    order: list[str] = []
    emitted: set[str] = set()

    def emit(ch: str, bucket: int) -> None:
        if ch in emitted:
            return
        emitted.add(ch)
        for p in parts(ch):
            if p not in emitted and level_key(p) == bucket:
                emit(p, bucket)
        order.append(ch)

    for bucket in sorted(buckets):
        for ch in sorted(buckets[bucket], key=lambda c: (kd[c]["freq"] or 9999, kd[c]["strokes"], c)):
            emit(ch, bucket)
    return order


# --------------------------------------------------------------------------- database

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE words (
    id INTEGER PRIMARY KEY,          -- position in the default (JLPT) learning order
    key TEXT NOT NULL UNIQUE,        -- stable identity: "<jmdict seq>:<word>"
    seq INTEGER NOT NULL,
    word TEXT NOT NULL,              -- the form shown on cards
    kana TEXT NOT NULL,
    romaji TEXT NOT NULL,
    kanji_form TEXT,                 -- kanji spelling, also set for words usually written in kana
    usually_kana INTEGER NOT NULL,
    alt_kana TEXT NOT NULL,          -- JSON list of other accepted readings
    meaning TEXT NOT NULL,           -- short gloss for cards
    senses TEXT NOT NULL,            -- JSON [{pos, gloss, misc, field, info, dial}]
    pos TEXT NOT NULL,               -- part-of-speech codes of the first sense, comma separated
    level INTEGER NOT NULL,          -- 5..1 = JLPT N5..N1, 0 = common word outside the JLPT lists
    band INTEGER NOT NULL,           -- 5..1: the JLPT level this word is studied alongside
    zipf REAL NOT NULL,
    freq_rank INTEGER NOT NULL,      -- 1 = most frequent of the list
    furi TEXT NOT NULL,              -- JSON [[text, reading], ...] per-kanji furigana of `word`
    pitch TEXT NOT NULL,             -- accent positions such as "0" or "1,2"; empty when unknown
    tts TEXT NOT NULL,               -- text to hand to a speech engine
    ambiguous INTEGER NOT NULL       -- another item is written the same way
);
CREATE TABLE examples (
    id INTEGER PRIMARY KEY,
    word_id INTEGER NOT NULL REFERENCES words(id),
    sense INTEGER NOT NULL,
    jp TEXT NOT NULL,
    en TEXT NOT NULL,
    form TEXT NOT NULL,              -- the word as it appears in the sentence
    furi TEXT NOT NULL,              -- Tatoeba furigana markup, or empty
    checked INTEGER NOT NULL,        -- furigana reviewed by a person
    tatoeba_id INTEGER
);
CREATE INDEX examples_word ON examples(word_id);
CREATE TABLE kanji (
    ch TEXT PRIMARY KEY,
    rank INTEGER,                    -- position in the kanji course, NULL for reference-only characters
    meanings TEXT NOT NULL,          -- JSON list
    on_yomi TEXT NOT NULL,           -- JSON list (katakana)
    kun_yomi TEXT NOT NULL,          -- JSON list (hiragana, okurigana after a dot)
    strokes INTEGER NOT NULL,
    grade INTEGER NOT NULL,          -- 1-6 elementary, 8 secondary, 9/10 name kanji, 0 other
    jlpt INTEGER NOT NULL,           -- 5..1, 0 = not in the JLPT lists
    freq INTEGER NOT NULL,           -- newspaper frequency rank, 0 = unranked
    radical TEXT NOT NULL,           -- JSON {n, glyph, meaning, name}
    usage TEXT NOT NULL              -- JSON [{r, type, n}] readings seen in the vocabulary
);
CREATE INDEX kanji_rank ON kanji(rank);
CREATE TABLE strokes (
    ch TEXT PRIMARY KEY,
    paths TEXT NOT NULL,             -- JSON list of SVG path data, 109x109 box, in stroke order
    groups TEXT NOT NULL             -- JSON component tree [{el, orig, pos, rad, strokes, name, sub}]
);
CREATE TABLE kanji_words (
    ch TEXT NOT NULL,
    word_id INTEGER NOT NULL,
    reading TEXT NOT NULL,           -- how the kanji is read in this word ('' when irregular)
    headword INTEGER NOT NULL,       -- 1 if the kanji is in the displayed form, 0 if only in the kanji spelling
    PRIMARY KEY (ch, word_id)
) WITHOUT ROWID;
CREATE INDEX kanji_words_word ON kanji_words(word_id);
"""


def build(report_only: bool = False) -> None:
    t0 = time.time()
    global FREQ
    FREQ = load_frequency()
    log(f"frequency list: {len(FREQ):,} tokens")
    jm = read_zip_json("jmdict-examples-eng.json.zip")
    d = Dictionary(jm)
    log(f"JMdict {d.date}: {len(d.words):,} entries")

    # ---- vocabulary
    kd = load_kanjidic()
    items = select_jlpt(d)
    items += add_secondary_jlpt(d, items)
    for it in items:
        it["freq"] = item_freq(it)
    # The source lists carry a few rows that are not words at all (秭, a
    # numeral nobody uses): unknown to the corpus and not marked common.
    junk = [it for it in items if it["freq"] <= 0 and not is_common(it["entry"]) and len(it["word"]) == 1]
    if junk:
        log("dropped non-words from the JLPT lists:", " ".join(f"{it['word']}({it['kana']})" for it in junk))
        items = [it for it in items if it not in junk]
    split_homographs(items)
    extra = select_extra(d, items, max(TOTAL_WORDS - len(items), 0), kd)
    note("\n=== extra tier, most frequent 150")
    note("  " + "  ".join(f"{it['word']}({zipf(it['freq']):.1f})" for it in extra[:150]))
    note("=== extra tier, last 80")
    note("  " + "  ".join(f"{it['word']}({zipf(it['freq']):.1f})" for it in extra[-80:]))
    # The default learning order follows the JLPT levels. Words outside the JLPT
    # lists are slotted into that order by frequency (never into N5, which stays
    # the plain beginner list) so that サイト or 東京 does not wait until after N1.
    for it in items:
        it["band"] = it["level"]
    cuts = [int(len(extra) * q) for q in (0.03, 0.20, 0.50)]
    for i, it in enumerate(extra):
        it["band"] = 4 if i < cuts[0] else 3 if i < cuts[1] else 2 if i < cuts[2] else 1
    items += extra
    promoted = [it for it in items if it["word"] in BEGINNER_ESSENTIALS and it["band"] != 5]
    for it in promoted:
        it["band"] = 5
    log("everyday essentials moved into the N5 band:", " ".join(it["word"] for it in promoted))
    missing = BEGINNER_ESSENTIALS - {it["word"] for it in items}
    if missing:
        log("  (not in the list at all:", " ".join(sorted(missing)) + ")")

    level_default = {5: 4.0, 4: 3.8, 3: 3.5, 2: 3.2, 1: 3.0, 0: 3.0}
    unknown = Counter()
    for it in items:
        z = zipf(it["freq"])
        if z <= 0:
            unknown[it["level"]] += 1
            z = level_default[it["level"]] - 0.5
        it["zipf"] = z
    log("words without a frequency estimate, by level:", dict(unknown))

    items.sort(key=lambda it: (5 - it["band"], -it["zipf"], it["kana"]))
    for i, it in enumerate(items, 1):
        it["id"] = i
    for rank, it in enumerate(sorted(items, key=lambda it: (-it["zipf"], it["id"])), 1):
        it["freq_rank"] = rank
    log("words per level:", dict(sorted(Counter(it["level"] for it in items).items(), reverse=True)))
    log("words per study band:", dict(sorted(Counter(it["band"] for it in items).items(), reverse=True)))

    word_counts = Counter(it["word"] for it in items)
    pitch = load_pitch()
    trans = load_transcriptions()
    word_furi = load_word_furigana()
    ex_stats = Counter()
    stats = Counter()
    for it in items:
        it["romaji"] = romaji_for(it)
        it["tts"] = tts_text(d, it)
        it["pitch"] = find_pitch(pitch, it)
        it["ambiguous"] = int(word_counts[it["word"]] > 1)
        it["examples"] = collect_examples(it, trans, ex_stats)
        furi = word_furi.get((it["word"], it["kana"])) if K.has_kanji(it["word"]) else None
        it["furi"] = furi or ([[it["word"], it["kana"]]] if K.has_kanji(it["word"]) else [])
        if it["kanji_form"] and it["kanji_form"] != it["word"]:
            it["kfuri"] = word_furi.get((it["kanji_form"], it["kana"])) or []
        else:
            it["kfuri"] = []
        stats["has pitch"] += bool(it["pitch"])
        stats["has examples"] += bool(it["examples"])
        stats["has kanji"] += K.has_kanji(it["word"])
        stats["per-kanji furigana"] += bool(furi)
        stats["usually kana"] += it["uk"]
        stats["tts uses kana"] += it["tts"] == it["kana"] and K.has_kanji(it["word"])
        stats["ambiguous"] += it["ambiguous"]
    log("word stats:", dict(stats))
    log("example stats:", dict(ex_stats), "total examples:", sum(len(it["examples"]) for it in items))

    # ---- kanji
    vg = load_kanjivg()
    radicals = load_radicals()
    rad_by_glyph = {r["glyph"]: r["meaning"] for r in radicals.values()}
    kanji_data = json.load(open(RAW / "kanji-data.json", encoding="utf-8"))
    level_of = {ch: v["jlpt_new"] for ch, v in kanji_data.items() if v.get("jlpt_new")}
    log(f"KANJIDIC: {len(kd):,} characters; KanjiVG: {len(vg):,} characters")

    usage: dict[str, Counter] = defaultdict(Counter)
    kanji_words: dict[tuple[str, int], tuple[str, int]] = {}
    for it in items:
        for segs, headword in ((it["furi"], 1), (it["kfuri"], 0)):
            for base, rt in segs:
                chars = K.kanji_in(base)
                for ch in chars:
                    reading = rt if (len(base) == 1 and rt) else ""
                    key = (ch, it["id"])
                    if key not in kanji_words or headword > kanji_words[key][1]:
                        kanji_words[key] = (reading, headword)
                    if reading and headword:
                        usage[ch][K.kata_to_hira(reading)] += 1
        for ch in K.kanji_in(it["kanji_form"] or ""):
            kanji_words.setdefault((ch, it["id"]), ("", 0))

    in_vocab = {ch for (ch, _), (_, hw) in kanji_words.items() if hw}
    course = {ch for ch in kd if 1 <= kd[ch]["grade"] <= 8} | {c for c in in_vocab if c in kd}
    course_order = order_course(course, level_of, kd, vg)
    rank_of = {ch: i for i, ch in enumerate(course_order, 1)}
    joyo = sum(1 for ch in course if 1 <= kd[ch]["grade"] <= 8)
    log(f"kanji course: {len(course):,} characters ({joyo:,} Joyo, {len(course) - joyo} more used by the vocabulary)")
    log("course kanji without stroke data:", "".join(ch for ch in course_order if ch not in vg) or "none")
    log("kanji per JLPT level:", dict(sorted(Counter(level_of.get(c, 0) for c in course).items(), reverse=True)))
    missing_kd = sorted({ch for (ch, _) in kanji_words if ch not in kd})
    log("vocabulary kanji missing from KANJIDIC:", "".join(missing_kd) or "none")

    def add_names(groups: list[dict]) -> list[dict]:
        for g in groups:
            g["name"] = component_meaning(g["el"], g.get("orig"), rad_by_glyph, kd)
            if "sub" in g:
                add_names(g["sub"])
        return groups

    if report_only:
        write_report(items, course_order, kd, vg, usage, t0)
        return

    # ---- write
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".db.tmp")
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    js = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    db.executemany(
        "INSERT INTO words VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(
            it["id"], f"{it['seq']}:{it['word']}", it["seq"], it["word"], it["kana"], it["romaji"],
            it["kanji_form"], int(it["uk"]), js(it["alt_kana"]), short_meaning(it),
            js([{k: v for k, v in s.items() if k != "ex" and v} for s in it["senses"][:8]]),
            ",".join(it["senses"][0]["pos"]), it["level"], it["band"], it["zipf"], it["freq_rank"], js(it["furi"]),
            it["pitch"], it["tts"], it["ambiguous"],
        ) for it in items],
    )
    db.executemany(
        "INSERT INTO examples (word_id, sense, jp, en, form, furi, checked, tatoeba_id) VALUES (?,?,?,?,?,?,?,?)",
        [(it["id"], e["sense"], e["jp"], e["en"], e["form"], e["furi"], e["checked"], e["tid"])
         for it in items for e in it["examples"]],
    )
    rows = []
    for ch, k in kd.items():
        rad = radicals.get(k["radical"], {"glyph": "", "meaning": "", "name": ""})
        use = [{"r": r, "type": classify_reading(r, k["on"], k["kun"]), "n": n}
               for r, n in usage.get(ch, Counter()).most_common(8)]
        rows.append((ch, rank_of.get(ch), js(k["meanings"]), js(k["on"]), js(k["kun"]), k["strokes"], k["grade"],
                     level_of.get(ch, 0), k["freq"], js({"n": k["radical"], **rad}), js(use)))
    db.executemany("INSERT INTO kanji VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.executemany(
        "INSERT INTO strokes VALUES (?,?,?)",
        [(ch, js(v["paths"]), js(add_names(v["groups"]))) for ch, v in vg.items()
         if ch in kd or K.is_kana(ch) or ch in "ー々"],
    )
    db.executemany("INSERT INTO kanji_words VALUES (?,?,?,?)",
                   [(ch, wid, r, hw) for (ch, wid), (r, hw) in kanji_words.items() if ch in kd])
    meta = {
        "schema": SCHEMA_VERSION,
        "built": time.strftime("%Y-%m-%d %H:%M"),
        "jmdict_date": d.date,
        "words": len(items),
        "course_kanji": len(course_order),
        "pos_tags": js(d.tags),
    }
    db.executemany("INSERT INTO meta VALUES (?,?)", [(k, str(v)) for k, v in meta.items()])
    db.commit()
    db.execute("VACUUM")
    db.close()
    if OUT.exists():
        OUT.unlink()
    tmp.rename(OUT)
    log(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    write_report(items, course_order, kd, vg, usage, t0)


def write_report(items, course_order, kd, vg, usage, t0) -> None:
    by_level = defaultdict(list)
    for it in items:
        by_level[it["level"]].append(it)
    for lvl in (5, 4, 3, 2, 1, 0):
        lst = by_level[lvl]
        note(f"\n=== level {lvl}: {len(lst)} words; first 40 and last 15 in learning order")
        for it in lst[:40] + lst[-15:]:
            note(f"  {it['id']:>5} {it['word']}【{it['kana']}】 {it['romaji']}  z={it['zipf']:.2f} #{it['freq_rank']}"
                 f"  pitch={it['pitch'] or '-'} tts={it['tts']}  {short_meaning(it)[:70]}")
    note("\n=== romaji read with particle wa")
    note("  " + ", ".join(f"{it['word']}={it['romaji']}" for it in items if it["romaji"].endswith("wa") and it["kana"].endswith("は")))
    note("\n=== ambiguous written forms (sample)")
    amb = defaultdict(list)
    for it in items:
        if it["ambiguous"]:
            amb[it["word"]].append(f"{it['kana']}({short_meaning(it)[:25]})")
    for w, lst in list(amb.items())[:60]:
        note(f"  {w}: " + " | ".join(lst))
    note(f"\n=== kanji course order (first 200): {''.join(course_order[:200])}")
    note("\n=== sample kanji")
    for ch in "日休語曜鬱飲":
        if ch in vg:
            note(f"  {ch} groups={json.dumps(vg[ch]['groups'], ensure_ascii=False)}")
            note(f"     usage={usage.get(ch, Counter()).most_common(6)} on={kd[ch]['on']} kun={kd[ch]['kun']}")
    note(f"\nfinished in {time.time() - t0:.0f}s")
    (RAW / "build_report.txt").write_text("\n".join(REPORT), encoding="utf-8")
    print("report ->", RAW / "build_report.txt")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build data/content.db from data/raw/")
    ap.add_argument("--report-only", action="store_true", help="run the selection and write the report, but no database")
    args = ap.parse_args(argv)
    if not (RAW / "jmdict-examples-eng.json.zip").exists():
        print("data/raw is empty - run tools/fetch_sources.py first", file=sys.stderr)
        return 1
    build(report_only=args.report_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
