"""Load plain-text / markdown novels into paragraphs."""
from __future__ import annotations

from pathlib import Path


def _decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis", "euc_jp", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def load_text_file(path: Path | str) -> str:
    path = Path(path)
    return _decode_bytes(path.read_bytes())


def split_paragraphs(text: str) -> list[str]:
    """Split on blank lines; keep non-empty blocks."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    parts = []
    for block in text.split("\n\n"):
        block = "\n".join(line.rstrip() for line in block.split("\n")).strip()
        if block:
            parts.append(block)
    # Very long single block with many lines → also split on single newlines in chunks
    if len(parts) == 1 and parts[0].count("\n") > 40:
        lines = [ln.strip() for ln in parts[0].split("\n") if ln.strip()]
        chunk: list[str] = []
        out: list[str] = []
        for ln in lines:
            chunk.append(ln)
            if len(chunk) >= 6:
                out.append("\n".join(chunk))
                chunk = []
        if chunk:
            out.append("\n".join(chunk))
        return out
    return parts
