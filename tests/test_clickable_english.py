from nihongo_quest.ui.widgets.clickable_english import is_english_word, tokenize_english


def test_tokenize_keeps_words_and_punct() -> None:
    toks = tokenize_english("Don't go, Alice!")
    assert "Don't" in toks
    assert "go" in toks
    assert "Alice" in toks
    assert any("," in t or t == "," for t in toks)


def test_is_english_word() -> None:
    assert is_english_word("Hello")
    assert is_english_word("Don't")
    assert not is_english_word(",")
    assert not is_english_word(" ")
    assert not is_english_word("こんにちは")
