"""Longest-match tokenizer for Immersion dictionary hover."""
from __future__ import annotations

from nihongo_quest.core.content import Content
from nihongo_quest.core.immersion.tokenize import LexiconMatcher, tokenize_japanese
from nihongo_quest.paths import CONTENT_DB


def test_tokenize_unknown_chars():
    tokens = tokenize_japanese("あいう", forms={}, max_len=4)
    assert "".join(t.text for t in tokens) == "あいう"
    assert all(t.word is None for t in tokens)


def test_lexicon_matcher_finds_common_word():
    content = Content(CONTENT_DB)
    matcher = LexiconMatcher(content)
    # 本 should be in the 10k list
    hit = matcher.lookup("本")
    assert hit is not None
    tokens = matcher.tokenize("この本は良い")
    surfaces = [t.text for t in tokens]
    assert "本" in surfaces
    matched = [t for t in tokens if t.word is not None]
    assert matched
