from pathlib import Path

from nihongo_quest.core.images import ImageStore
from nihongo_quest.core.progress import KANJI, VOCAB


def test_set_and_clear_vocab_image(tmp_path: Path) -> None:
    store = ImageStore(tmp_path)
    src = tmp_path / "car.png"
    # Minimal valid 1x1 PNG
    src.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
        )
    )
    key = "123:車"
    dest = store.set_image(VOCAB, key, src)
    assert dest.exists()
    assert store.has(VOCAB, key)
    assert store.path(VOCAB, key) == dest
    store.clear(VOCAB, key)
    assert not store.has(VOCAB, key)


def test_kanji_stem_uses_codepoint(tmp_path: Path) -> None:
    store = ImageStore(tmp_path)
    src = tmp_path / "sun.jpg"
    src.write_bytes(b"not-a-real-jpeg-but-copied")
    dest = store.set_image(KANJI, "日", src)
    assert dest.name.startswith("U+65E5")
    assert store.path(KANJI, "日") == dest
