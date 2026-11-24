from __future__ import annotations

from nihongo_quest.core import translate as tr


def test_en_to_ro_uses_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tr, "_CACHE_PATH", tmp_path / "ro.json")
    monkeypatch.setattr(tr, "_memory", {})
    monkeypatch.setattr(tr, "_loaded", False)
    calls = {"n": 0}

    def fake(text: str, langpair: str, timeout: float = 8.0) -> str:
        calls["n"] += 1
        assert langpair == "en|ro"
        return "salut"

    monkeypatch.setattr(tr, "_mymemory", fake)
    assert tr.translate_en_to_ro("hello") == "salut"
    assert tr.translate_en_to_ro("hello") == "salut"
    assert calls["n"] == 1
    assert (tmp_path / "ro.json").exists()


def test_batch_skips_blanks(monkeypatch) -> None:
    monkeypatch.setattr(tr, "_memory", {})
    monkeypatch.setattr(tr, "_loaded", True)
    monkeypatch.setattr(tr, "_mymemory", lambda text, langpair, timeout=8.0: f"RO:{text}")
    monkeypatch.setattr(tr, "_save_cache", lambda: None)
    out = tr.translate_en_batch_to_ro(["a", "", "a", "b"])
    assert out == {"a": "RO:a", "b": "RO:b"}
