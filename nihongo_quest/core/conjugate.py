"""Verb and adjective conjugation driven by JMdict part-of-speech codes.

``conjugate(written, kana, pos)`` returns the common forms of a word in both its
written spelling and its kana reading. Only forms that are regular for the
word's class are produced; classes with unpredictable forms get a reduced
table rather than a guessed one.
"""
from __future__ import annotations

from dataclasses import dataclass

# ending kana -> (a-row, i-row, e-row, o-row, te-form, ta-form)
_GODAN = {
    "う": ("わ", "い", "え", "お", "って", "った"),
    "く": ("か", "き", "け", "こ", "いて", "いた"),
    "ぐ": ("が", "ぎ", "げ", "ご", "いで", "いだ"),
    "す": ("さ", "し", "せ", "そ", "して", "した"),
    "つ": ("た", "ち", "て", "と", "って", "った"),
    "ぬ": ("な", "に", "ね", "の", "んで", "んだ"),
    "ぶ": ("ば", "び", "べ", "ぼ", "んで", "んだ"),
    "む": ("ま", "み", "め", "も", "んで", "んだ"),
    "る": ("ら", "り", "れ", "ろ", "って", "った"),
}

# (key, English label, Japanese label)
FORM_LABELS: dict[str, tuple[str, str]] = {
    "dict": ("Dictionary", "辞書形"),
    "masu": ("Polite", "ます形"),
    "polite": ("Polite", "丁寧形"),
    "neg": ("Negative", "否定形"),
    "masu_neg": ("Polite negative", "丁寧否定"),
    "past": ("Past", "過去形"),
    "masu_past": ("Polite past", "丁寧過去"),
    "neg_past": ("Negative past", "否定過去"),
    "te": ("Te-form", "て形"),
    "prog": ("Progressive", "進行形"),
    "tai": ("Want to", "希望形"),
    "vol": ("Volitional", "意向形"),
    "pot": ("Potential", "可能形"),
    "pass": ("Passive", "受身形"),
    "caus": ("Causative", "使役形"),
    "caus_pass": ("Causative passive", "使役受身"),
    "imp": ("Imperative", "命令形"),
    "proh": ("Prohibitive", "禁止形"),
    "ba": ("Conditional (ba)", "仮定形"),
    "tara": ("Conditional (tara)", "たら形"),
    "adv": ("Adverbial", "連用形"),
    "noun": ("Noun form", "名詞形"),
    "sou": ("Looks like", "様態"),
    "attr": ("Before a noun", "連体形"),
}


@dataclass(frozen=True)
class Form:
    key: str
    written: str
    kana: str

    @property
    def label(self) -> str:
        return FORM_LABELS[self.key][0]

    @property
    def label_jp(self) -> str:
        return FORM_LABELS[self.key][1]


def word_class(pos: list[str] | tuple[str, ...]) -> str | None:
    """Pick the conjugation class from a JMdict part-of-speech list."""
    codes = list(pos)
    for code in ("vk", "vs-i", "vs-s"):
        if code in codes:
            return code
    for code in codes:
        if code in ("v1", "v1-s") or (code.startswith("v5") and code not in ("v5uru",)):
            return code
    for code in ("adj-ix", "adj-i", "vs", "adj-na"):
        if code in codes:
            return code
    return None


def _pairs(base_w: str, base_k: str, table: dict[str, str]) -> list[Form]:
    return [Form(key, base_w + suf, base_k + suf) for key, suf in table.items()]


def _godan(written: str, kana: str, cls: str) -> list[Form]:
    end = kana[-1]
    if end not in _GODAN or written[-1] != end:
        return []
    a, i, e, o, te, ta = _GODAN[end]
    if cls == "v5k-s":                      # 行く -> 行って
        te, ta = "って", "った"
    elif cls == "v5u-s":                    # 問う -> 問うて
        te, ta = "うて", "うた"
    bw, bk = written[:-1], kana[:-1]
    masu = "い" if cls == "v5aru" else i    # いらっしゃる -> いらっしゃいます
    table = {
        "dict": end,
        "masu": masu + "ます",
        "neg": a + "ない",
        "masu_neg": masu + "ません",
        "past": ta,
        "masu_past": masu + "ました",
        "neg_past": a + "なかった",
        "te": te,
        "prog": te + "いる",
        "tai": masu + "たい",
        "vol": o + "う",
        "pot": e + "る",
        "pass": a + "れる",
        "caus": a + "せる",
        "caus_pass": a + "せられる",
        "imp": "い" if cls == "v5aru" else e,
        "proh": end + "な",
        "ba": e + "ば",
        "tara": ta + "ら",
    }
    forms = _pairs(bw, bk, table)
    if cls == "v5r-i":
        # ある: the negative is ない, and it has no potential/passive/causative.
        if not kana.endswith("ある"):
            return []
        pw = written[:-2] if written.endswith("ある") else ""
        pk = kana[:-2]
        fixed = {"neg": "ない", "neg_past": "なかった"}
        drop = {"pot", "pass", "caus", "caus_pass", "imp", "proh", "vol", "tai", "prog"}
        out = []
        for f in forms:
            if f.key in drop:
                continue
            if f.key in fixed:
                f = Form(f.key, pw + fixed[f.key], pk + fixed[f.key])
            out.append(f)
        return out
    return forms


def _ichidan(written: str, kana: str, cls: str) -> list[Form]:
    if not (written.endswith("る") and kana.endswith("る")):
        return []
    table = {
        "dict": "る", "masu": "ます", "neg": "ない", "masu_neg": "ません", "past": "た",
        "masu_past": "ました", "neg_past": "なかった", "te": "て", "prog": "ている", "tai": "たい",
        "vol": "よう", "pot": "られる", "pass": "られる", "caus": "させる", "caus_pass": "させられる",
        "imp": "" if cls == "v1-s" else "ろ", "proh": "るな", "ba": "れば", "tara": "たら",
    }
    return _pairs(written[:-1], kana[:-1], table)


def _kuru(written: str, kana: str) -> list[Form]:
    if not kana.endswith("くる") or len(written) < 2:
        return []
    keep_kanji = written[-2] == "来"
    if not keep_kanji and not written.endswith("くる"):
        return []
    pw, pk = written[:-2], kana[:-2]
    table = {
        "dict": ("く", "る"), "masu": ("き", "ます"), "neg": ("こ", "ない"), "masu_neg": ("き", "ません"),
        "past": ("き", "た"), "masu_past": ("き", "ました"), "neg_past": ("こ", "なかった"), "te": ("き", "て"),
        "prog": ("き", "ている"), "tai": ("き", "たい"), "vol": ("こ", "よう"), "pot": ("こ", "られる"),
        "pass": ("こ", "られる"), "caus": ("こ", "させる"), "caus_pass": ("こ", "させられる"), "imp": ("こ", "い"),
        "proh": ("く", "るな"), "ba": ("く", "れば"), "tara": ("き", "たら"),
    }
    return [Form(k, pw + ("来" if keep_kanji else root) + suf, pk + root + suf) for k, (root, suf) in table.items()]


_SURU = {
    "dict": "する", "masu": "します", "neg": "しない", "masu_neg": "しません", "past": "した",
    "masu_past": "しました", "neg_past": "しなかった", "te": "して", "prog": "している", "tai": "したい",
    "vol": "しよう", "pot": "できる", "pass": "される", "caus": "させる", "caus_pass": "させられる",
    "imp": "しろ", "proh": "するな", "ba": "すれば", "tara": "したら",
}
# 愛する / 接する style verbs disagree on the negative (愛さない vs 接しない), so only
# the forms every member of the class shares are listed.
_SURU_SPECIAL = {k: _SURU[k] for k in ("dict", "masu", "masu_neg", "past", "masu_past", "te", "prog", "tai",
                                       "pass", "caus", "proh", "ba", "tara")}


def _suru(written: str, kana: str, cls: str) -> list[Form]:
    if cls == "vs":                          # noun that takes する
        return _pairs(written, kana, _SURU)
    if not kana.endswith("する"):
        return []
    pw = written[:-2] if written.endswith("する") else ""
    return _pairs(pw, kana[:-2], _SURU if cls == "vs-i" else _SURU_SPECIAL)


def _adj_i(written: str, kana: str, cls: str) -> list[Form]:
    if not (written.endswith("い") and kana.endswith("い")):
        return []
    bw, bk = written[:-1], kana[:-1]
    sou = "そう"
    if cls == "adj-ix":                      # いい conjugates as よい
        if not kana.endswith("いい"):
            return []
        bk = kana[:-2] + "よ"
        bw = written[:-2] + "よ" if written.endswith("いい") else written[:-1]
        sou = "さそう"
    table = {
        "neg": "くない", "past": "かった", "neg_past": "くなかった", "te": "くて", "ba": "ければ",
        "adv": "く", "noun": "さ", "sou": sou,
    }
    return [Form("dict", written, kana), Form("polite", written + "です", kana + "です")] + _pairs(bw, bk, table)


def _adj_na(written: str, kana: str) -> list[Form]:
    table = {
        "dict": "だ", "polite": "です", "neg": "じゃない", "masu_neg": "じゃありません", "past": "だった",
        "masu_past": "でした", "neg_past": "じゃなかった", "te": "で", "attr": "な", "adv": "に",
    }
    return _pairs(written, kana, table)


def conjugate(written: str, kana: str, pos: list[str] | tuple[str, ...]) -> list[Form]:
    """Conjugated forms of a word, or an empty list when it does not inflect."""
    cls = word_class(pos)
    if not cls or not written or not kana:
        return []
    if cls == "vk":
        return _kuru(written, kana)
    if cls in ("vs-i", "vs-s", "vs"):
        return _suru(written, kana, cls)
    if cls in ("v1", "v1-s"):
        return _ichidan(written, kana, cls)
    if cls.startswith("v5"):
        return _godan(written, kana, cls)
    if cls in ("adj-i", "adj-ix"):
        return _adj_i(written, kana, cls)
    if cls == "adj-na":
        return _adj_na(written, kana)
    return []


def class_name(cls: str | None) -> str:
    """Learner-friendly name of a conjugation class."""
    if not cls:
        return ""
    if cls.startswith("v5"):
        return "Godan verb (五段)"
    return {
        "v1": "Ichidan verb (一段)", "v1-s": "Ichidan verb (一段)", "vk": "Irregular verb 来る",
        "vs-i": "Irregular verb する", "vs-s": "する verb (special)", "vs": "Noun + する",
        "adj-i": "い-adjective", "adj-ix": "い-adjective (いい)", "adj-na": "な-adjective",
    }.get(cls, "")


def stems(written: str, kana: str, pos: list[str] | tuple[str, ...]) -> list[str]:
    """Surface stems a tokenizer would split an inflected word into (食べ, 行っ, 高)."""
    cls = word_class(pos)
    if not cls or cls in ("vs", "adj-na"):
        return []
    forms = {f.key: f.written for f in conjugate(written, kana, pos)}
    out = []
    if cls.startswith("adj-i"):
        if "adv" in forms:
            out.append(forms["adv"])                     # 高く
        if forms.get("past", "").endswith("た"):
            out.append(forms["past"][:-1])               # 高かっ
    else:
        if forms.get("masu", "").endswith("ます"):
            out.append(forms["masu"][:-2])               # 食べ, 行き
        if len(forms.get("te", "")) > 1:
            out.append(forms["te"][:-1])                 # 行っ
    return [s for s in dict.fromkeys(out) if s]
