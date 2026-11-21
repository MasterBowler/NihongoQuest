"""Kana utilities: script detection, kana <-> romaji conversion, a small romaji IME,
mora splitting (for pitch accent) and the gojuon chart used by the kana trainer.

Everything here is pure Python with no Qt dependency so it can be unit-tested and
reused by the data build script.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- script tests

_SMALL_Y = "ゃゅょ"
_SMALL_VOWEL = "ぁぃぅぇぉ"
_SMALL_ALL = _SMALL_Y + _SMALL_VOWEL + "ゎ"
LONG_MARK = "ー"


def is_hiragana(ch: str) -> bool:
    return "\u3041" <= ch <= "\u309f"


def is_katakana(ch: str) -> bool:
    return "\u30a1" <= ch <= "\u30ff"


def is_kana(ch: str) -> bool:
    return is_hiragana(ch) or is_katakana(ch)


def is_kanji(ch: str) -> bool:
    # CJK unified ideographs + extension A + compatibility block, plus the iteration mark.
    return ("\u4e00" <= ch <= "\u9fff") or ("\u3400" <= ch <= "\u4dbf") or ("\uf900" <= ch <= "\ufaff") or ch == "々"


def has_kanji(text: str) -> bool:
    return any(is_kanji(c) for c in text)


def kanji_in(text: str) -> list[str]:
    """Distinct kanji of ``text`` in order of first appearance (々 excluded)."""
    seen: list[str] = []
    for c in text:
        if is_kanji(c) and c != "々" and c not in seen:
            seen.append(c)
    return seen


def kata_to_hira(text: str) -> str:
    out = []
    for c in text:
        if "\u30a1" <= c <= "\u30f6":
            out.append(chr(ord(c) - 0x60))
        else:
            out.append(c)
    return "".join(out)


def hira_to_kata(text: str) -> str:
    out = []
    for c in text:
        if "\u3041" <= c <= "\u3096":
            out.append(chr(ord(c) + 0x60))
        else:
            out.append(c)
    return "".join(out)


# --------------------------------------------------------------------------- kana -> romaji

_BASE = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "wi", "ゑ": "we", "を": "o", "ん": "n",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ゔ": "vu",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ゎ": "wa", "ゕ": "ka", "ゖ": "ke",
}

# Two-kana combinations that do not follow the regular "consonant + y + vowel" pattern.
_DIGRAPH = {
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho", "しぇ": "she",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo", "じぇ": "je",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho", "ちぇ": "che",
    "ぢゃ": "ja", "ぢゅ": "ju", "ぢょ": "jo",
    "ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo", "ふゅ": "fyu",
    "てぃ": "ti", "でぃ": "di", "とぅ": "tu", "どぅ": "du", "てゅ": "tyu", "でゅ": "dyu",
    "うぃ": "wi", "うぇ": "we", "うぉ": "wo",
    "ゔぁ": "va", "ゔぃ": "vi", "ゔぇ": "ve", "ゔぉ": "vo", "ゔゅ": "vyu",
    "つぁ": "tsa", "つぃ": "tsi", "つぇ": "tse", "つぉ": "tso",
    "いぇ": "ye",
    "くぁ": "kwa", "くぃ": "kwi", "くぇ": "kwe", "くぉ": "kwo",
    "ぐぁ": "gwa", "ぐぃ": "gwi", "ぐぇ": "gwe", "ぐぉ": "gwo",
    "すぃ": "si", "ずぃ": "zi",
}
# Regular yoon: き + ゃ -> kya, etc.
for _k, _c in {"き": "ky", "ぎ": "gy", "に": "ny", "ひ": "hy", "び": "by", "ぴ": "py", "み": "my", "り": "ry"}.items():
    for _s, _v in (("ゃ", "a"), ("ゅ", "u"), ("ょ", "o"), ("ぇ", "e")):
        _DIGRAPH[_k + _s] = _c + _v

_VOWELS = "aiueo"
_N_NEEDS_APOSTROPHE = set("あいうえおやゆよ")


def to_romaji(kana: str, final_wa: bool = False) -> str:
    """Hepburn-style romanisation that mirrors the kana spelling.

    Long vowels are written out the way they are spelled (とうきょう -> toukyou,
    コーヒー -> koohii) so the romaji can be typed straight back into an IME.
    ``final_wa`` reads a trailing は as the particle "wa" (こんにちは -> konnichiwa).
    """
    text = kata_to_hira(kana).replace("ヴ", "ゔ").replace("ヵ", "ゕ").replace("ヶ", "ゖ")
    out: list[str] = []
    sokuon = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "っ":
            sokuon = True
            i += 1
            continue
        if ch == LONG_MARK:
            prev = out[-1] if out else ""
            out.append(prev[-1] if prev and prev[-1] in _VOWELS else "-")
            i += 1
            continue
        syl = None
        step = 1
        if i + 1 < n and text[i:i + 2] in _DIGRAPH:
            syl = _DIGRAPH[text[i:i + 2]]
            step = 2
        elif ch in _BASE:
            syl = _BASE[ch]
            if ch == "ん" and i + 1 < n and text[i + 1] in _N_NEEDS_APOSTROPHE:
                syl = "n'"
            elif ch == "は" and final_wa and i == n - 1 and n > 1:
                syl = "wa"
        if syl is None:
            # Not kana: keep punctuation readable, pass anything else through.
            sokuon = False
            out.append({"・": " ", "　": " ", "〜": "~", "、": ", ", "。": ". "}.get(ch, ch))
            i += 1
            continue
        if sokuon:
            sokuon = False
            if syl.startswith("ch"):
                syl = "t" + syl
            elif syl[0] not in _VOWELS:
                syl = syl[0] + syl
        out.append(syl)
        i += step
    return "".join(out)


def romaji_key(text: str) -> str:
    """Normalise romaji for loose matching: lower-case ASCII letters only,
    macrons expanded (ō -> ou, ū -> uu)."""
    text = text.lower()
    for a, b in (("ā", "aa"), ("ī", "ii"), ("ū", "uu"), ("ē", "ee"), ("ō", "ou")):
        text = text.replace(a, b)
    return re.sub(r"[^a-z]", "", text)


# --------------------------------------------------------------------------- romaji -> kana (IME)

def _build_ime_table() -> dict[str, str]:
    t: dict[str, str] = {"a": "あ", "i": "い", "u": "う", "e": "え", "o": "お"}
    rows = {
        "k": "かきくけこ", "s": "さしすせそ", "t": "たちつてと", "n": "なにぬねの", "h": "はひふへほ",
        "m": "まみむめも", "r": "らりるれろ", "g": "がぎぐげご", "z": "ざじずぜぞ", "d": "だぢづでど",
        "b": "ばびぶべぼ", "p": "ぱぴぷぺぽ",
    }
    for c, kana in rows.items():
        for v, k in zip(_VOWELS, kana):
            t[c + v] = k
    t.update({"ya": "や", "yu": "ゆ", "yo": "よ", "wa": "わ", "wo": "を", "wi": "うぃ", "we": "うぇ",
              "shi": "し", "chi": "ち", "tsu": "つ", "fu": "ふ", "ji": "じ"})
    yoon = {
        "ky": "き", "gy": "ぎ", "sy": "し", "sh": "し", "zy": "じ", "jy": "じ", "j": "じ", "ty": "ち", "ch": "ち",
        "cy": "ち", "dy": "ぢ", "ny": "に", "hy": "ひ", "by": "び", "py": "ぴ", "my": "み", "ry": "り",
    }
    for c, k in yoon.items():
        for v, s in (("a", "ゃ"), ("u", "ゅ"), ("o", "ょ")):
            t[c + v] = k + s
    t.update({
        "she": "しぇ", "je": "じぇ", "che": "ちぇ",
        "fa": "ふぁ", "fi": "ふぃ", "fe": "ふぇ", "fo": "ふぉ", "fyu": "ふゅ",
        "va": "ゔぁ", "vi": "ゔぃ", "vu": "ゔ", "ve": "ゔぇ", "vo": "ゔぉ",
        "thi": "てぃ", "dhi": "でぃ", "twu": "とぅ", "dwu": "どぅ", "thu": "てゅ", "dhu": "でゅ",
        "tsa": "つぁ", "tsi": "つぃ", "tse": "つぇ", "tso": "つぉ",
        "kwa": "くぁ", "gwa": "ぐぁ", "ye": "いぇ", "whi": "うぃ", "whe": "うぇ", "who": "うぉ",
        "xa": "ぁ", "xi": "ぃ", "xu": "ぅ", "xe": "ぇ", "xo": "ぉ",
        "la": "ぁ", "li": "ぃ", "lu": "ぅ", "le": "ぇ", "lo": "ぉ",
        "xya": "ゃ", "xyu": "ゅ", "xyo": "ょ", "lya": "ゃ", "lyu": "ゅ", "lyo": "ょ",
        "xtu": "っ", "xtsu": "っ", "ltu": "っ", "ltsu": "っ", "xwa": "ゎ", "xn": "ん",
        "-": "ー",
    })
    return t


_IME = _build_ime_table()
_IME_MAXLEN = max(len(k) for k in _IME)
_CONSONANTS = set("bcdfghjkmpqrstvwxyz")


def romaji_to_kana(text: str, final: bool = False, nn_eager: bool = False) -> str:
    """Convert typed romaji to hiragana the way a Japanese IME does.

    Kana and other characters already in ``text`` pass through, so this can be
    applied to a line edit on every keystroke. Unless ``final`` is set, a
    trailing incomplete syllable (``k``, ``sh``, a lone ``n``) is left as typed
    so the user can finish it.

    ``nn`` before a vowel is read as ん + n-row (``onna`` -> おんな); use
    ``n'`` for ん before a vowel (``kin'en`` -> きんえん). With ``nn_eager``
    every ``nn`` is ん, which is how desktop IMEs behave (``honnya`` -> ほんや).
    """
    src = text
    low = text.lower()
    out: list[str] = []
    i = 0
    n = len(low)
    while i < n:
        c = low[i]
        if not ("a" <= c <= "z" or c in "-'"):
            out.append(src[i])
            i += 1
            continue
        nxt = low[i + 1] if i + 1 < n else ""
        if c == "n":
            if nxt == "'":
                out.append("ん")
                i += 2
                continue
            if nxt == "n":
                after = low[i + 2] if i + 2 < n else ""
                out.append("ん")
                lazy = bool(after) and (after in _VOWELS or after == "y") and not nn_eager
                i += 1 if lazy else 2
                continue
            if nxt == "":
                out.append("ん" if final else src[i])
                i += 1
                continue
            if nxt not in _VOWELS and nxt != "y":
                out.append("ん")
                i += 1
                continue
        # sokuon: doubled consonant, or "tch"
        if c in _CONSONANTS and c != "n" and (nxt == c or (c == "t" and low[i + 1:i + 3] == "ch")):
            out.append("っ")
            i += 1
            continue
        for ln in range(min(_IME_MAXLEN, n - i), 0, -1):
            kana = _IME.get(low[i:i + ln])
            if kana:
                out.append(kana)
                i += ln
                break
        else:
            if c == "'":
                i += 1          # stray apostrophe: drop
                continue
            out.append(src[i])  # incomplete or unknown: leave as typed
            i += 1
    return "".join(out)


def normalize_reading(text: str) -> str:
    """Canonical form for comparing readings: hiragana, no spaces or separators."""
    text = kata_to_hira(text.strip())
    return re.sub(r"[\s・.\-~〜]", "", text)


def reading_matches(typed: str, expected: str) -> bool:
    """True when the typed answer (romaji or kana) matches the expected kana reading."""
    want = normalize_reading(expected)
    if not want:
        return False
    want_key = romaji_key(to_romaji(want))
    for eager in (False, True):
        got = normalize_reading(romaji_to_kana(typed, final=True, nn_eager=eager))
        if got == want:
            return True
        # Long marks are often typed as doubled vowels (koohii for コーヒー).
        if want_key and romaji_key(to_romaji(got)) == want_key:
            return True
    # Hepburn typists leave out the apostrophe after ん (honya for ほんや).
    raw = romaji_key(typed)
    return bool(raw) and raw == want_key


# --------------------------------------------------------------------------- morae / pitch accent

def split_morae(kana: str) -> list[str]:
    """Split a kana string into morae (small kana attach to the previous one)."""
    morae: list[str] = []
    for ch in kana:
        if not (is_kana(ch) or ch == LONG_MARK):
            continue
        if kata_to_hira(ch) in _SMALL_ALL and morae:
            morae[-1] += ch
        else:
            morae.append(ch)
    return morae


def pitch_pattern(n_morae: int, accent: int) -> list[bool]:
    """High/low (True/False) for each mora plus one trailing particle slot.

    accent 0 = heiban (rises and stays high), 1 = atamadaka (drops after the
    first mora), k = drop after the k-th mora.
    """
    if n_morae <= 0:
        return []
    highs = []
    for i in range(1, n_morae + 2):          # the extra slot is the following particle
        if accent == 0:
            highs.append(i > 1)
        elif accent == 1:
            highs.append(i == 1)
        else:
            highs.append(1 < i <= accent)
    return highs


def pitch_name(n_morae: int, accent: int) -> str:
    if accent == 0:
        return "heiban 平板"
    if accent == 1:
        return "atamadaka 頭高"
    if accent >= n_morae:
        return "odaka 尾高"
    return "nakadaka 中高"


# --------------------------------------------------------------------------- furigana markup

_FURI_RE = re.compile(r"\[([^\[\]|]+)\|([^\[\]]*)\]")


def parse_furigana(markup: str) -> list[tuple[str, str]]:
    """Parse Tatoeba-style markup ``[漢字|かん|じ]です`` into (base, ruby) segments.

    When a bracket lists one reading per character the group is split so every
    kanji carries its own reading; otherwise the whole group shares the reading.
    Plain text is returned with an empty ruby.
    """
    segs: list[tuple[str, str]] = []
    pos = 0
    for m in _FURI_RE.finditer(markup):
        if m.start() > pos:
            segs.append((markup[pos:m.start()], ""))
        base = m.group(1)
        readings = m.group(2).split("|")
        if len(readings) == len(base) and all(readings):
            segs.extend(zip(base, readings))
        else:
            segs.append((base, "".join(readings)))
        pos = m.end()
    if pos < len(markup):
        segs.append((markup[pos:], ""))
    return segs


def strip_furigana(markup: str) -> str:
    return _FURI_RE.sub(lambda m: m.group(1), markup)


# --------------------------------------------------------------------------- gojuon chart

# Each row: (row label, [five cells for a i u e o]); "" marks an empty cell.
GOJUON: list[tuple[str, list[str]]] = [
    ("", ["あ", "い", "う", "え", "お"]),
    ("k", ["か", "き", "く", "け", "こ"]),
    ("s", ["さ", "し", "す", "せ", "そ"]),
    ("t", ["た", "ち", "つ", "て", "と"]),
    ("n", ["な", "に", "ぬ", "ね", "の"]),
    ("h", ["は", "ひ", "ふ", "へ", "ほ"]),
    ("m", ["ま", "み", "む", "め", "も"]),
    ("y", ["や", "", "ゆ", "", "よ"]),
    ("r", ["ら", "り", "る", "れ", "ろ"]),
    ("w", ["わ", "", "", "", "を"]),
    ("n", ["ん", "", "", "", ""]),
]
DAKUON: list[tuple[str, list[str]]] = [
    ("g", ["が", "ぎ", "ぐ", "げ", "ご"]),
    ("z", ["ざ", "じ", "ず", "ぜ", "ぞ"]),
    ("d", ["だ", "ぢ", "づ", "で", "ど"]),
    ("b", ["ば", "び", "ぶ", "べ", "ぼ"]),
    ("p", ["ぱ", "ぴ", "ぷ", "ぺ", "ぽ"]),
]
# Each row: three cells for ya yu yo.
YOON: list[tuple[str, list[str]]] = [
    ("ky", ["きゃ", "きゅ", "きょ"]), ("sh", ["しゃ", "しゅ", "しょ"]), ("ch", ["ちゃ", "ちゅ", "ちょ"]),
    ("ny", ["にゃ", "にゅ", "にょ"]), ("hy", ["ひゃ", "ひゅ", "ひょ"]), ("my", ["みゃ", "みゅ", "みょ"]),
    ("ry", ["りゃ", "りゅ", "りょ"]), ("gy", ["ぎゃ", "ぎゅ", "ぎょ"]), ("j", ["じゃ", "じゅ", "じょ"]),
    ("by", ["びゃ", "びゅ", "びょ"]), ("py", ["ぴゃ", "ぴゅ", "ぴょ"]),
]


def chart_kana(groups: tuple[str, ...] = ("gojuon", "dakuon", "yoon"), katakana: bool = False) -> list[str]:
    """Flat list of the kana in the requested chart sections."""
    tables = {"gojuon": GOJUON, "dakuon": DAKUON, "yoon": YOON}
    out = [k for g in groups for _, row in tables[g] for k in row if k]
    return [hira_to_kata(k) for k in out] if katakana else out
