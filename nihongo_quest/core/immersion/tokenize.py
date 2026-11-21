"""Longest-match Japanese tokenization against the lexicon."""
from __future__ import annotations

from dataclasses import dataclass

from nihongo_quest.core import kana as K
from nihongo_quest.core.content import Content, Word


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int
    word: Word | None = None


class LexiconMatcher:
    """Surface-form trie built once from Content.words."""

    def __init__(self, content: Content) -> None:
        self._max_len = 1
        # form -> best Word (prefer shorter key / higher freq)
        forms: dict[str, Word] = {}
        for w in content.words:
            for form in (w.word, w.kanji_form, w.kana):
                if not form:
                    continue
                form = form.strip()
                if len(form) < 1:
                    continue
                prev = forms.get(form)
                if prev is None or w.freq_rank < prev.freq_rank:
                    forms[form] = w
                self._max_len = max(self._max_len, len(form))
        self._forms = forms

    def lookup(self, surface: str) -> Word | None:
        return self._forms.get(surface)

    def tokenize(self, text: str) -> list[Token]:
        return tokenize_japanese(text, self._forms, self._max_len)


def tokenize_japanese(
    text: str,
    forms: dict[str, Word] | None = None,
    max_len: int = 12,
) -> list[Token]:
    """Greedy longest-match left-to-right. Unmatched runs become word=None tokens."""
    if not text:
        return []
    forms = forms or {}
    tokens: list[Token] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # Keep whitespace / punctuation as plain tokens
        if ch.isspace() or ch in "「」『』【】（）().,!?！？…・ー〜~":
            j = i + 1
            while j < n and (text[j].isspace() or text[j] in "「」『』【】（）().,!?！？…・ー〜~"):
                j += 1
            tokens.append(Token(text[i:j], i, j, None))
            i = j
            continue

        matched: Token | None = None
        upper = min(n, i + max_len)
        for length in range(upper - i, 0, -1):
            piece = text[i : i + length]
            word = forms.get(piece)
            if word is not None:
                matched = Token(piece, i, i + length, word)
                break
            # Also try if the piece is pure kana of a known reading length 1+
            if length == 1 and (K.is_kanji(piece) or K.is_kana(piece)):
                # single char may still match as form
                if piece in forms:
                    matched = Token(piece, i, i + 1, forms[piece])
                    break
        if matched is None:
            # Consume one character (or a run of unknown kana/kanji until next match attempt)
            tokens.append(Token(text[i], i, i + 1, None))
            i += 1
        else:
            tokens.append(matched)
            i = matched.end
    return tokens
