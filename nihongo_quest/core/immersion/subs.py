"""Parse SRT / ASS subtitle files into timed cues."""
from __future__ import annotations

import re
from pathlib import Path

from nihongo_quest.core.immersion.cues import Cue

_ASS_TAG = re.compile(r"\{[^}]*\}")
_ASS_DRAW = re.compile(r"\\p[1-9][^\\]*")
_HTML_TAG = re.compile(r"<[^>]+>")
_SRT_TIME = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)
_ASS_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[.](\d{1,2})")


def _pad_ms(frac: str, *, ass: bool = False) -> int:
    if ass:
        # ASS centiseconds (1–2 digits)
        return int(frac.ljust(2, "0")[:2]) * 10
    return int(frac.ljust(3, "0")[:3])


def _hms_to_ms(h: str, m: str, s: str, frac: str, *, ass: bool = False) -> int:
    return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + _pad_ms(frac, ass=ass)


def strip_ass_tags(text: str) -> str:
    text = _ASS_TAG.sub("", text)
    text = text.replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")
    text = _HTML_TAG.sub("", text)
    # Drop drawing commands remnants
    lines = []
    for line in text.splitlines():
        if _ASS_DRAW.search(line):
            continue
        lines.append(line.strip())
    return "\n".join(p for p in lines if p).strip()


def parse_srt(text: str) -> list[Cue]:
    cues: list[Cue] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = block.split("\n")
        if not lines:
            continue
        # Skip index line if present
        if lines[0].strip().isdigit() and len(lines) >= 2:
            lines = lines[1:]
        if not lines:
            continue
        m = _SRT_TIME.search(lines[0])
        if not m:
            continue
        start = _hms_to_ms(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _hms_to_ms(m.group(5), m.group(6), m.group(7), m.group(8))
        body = strip_ass_tags("\n".join(lines[1:]))
        if body:
            cues.append(Cue(start, end, body))
    return cues


def parse_ass(text: str) -> list[Cue]:
    cues: list[Cue] = []
    in_events = False
    format_fields: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            in_events = line.lower() == "[events]"
            continue
        if not in_events:
            continue
        if line.lower().startswith("format:"):
            format_fields = [f.strip().lower() for f in line.split(":", 1)[1].split(",")]
            continue
        if not line.lower().startswith("dialogue:"):
            continue
        payload = line.split(":", 1)[1].lstrip()
        # Dialogue lines: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
        # Text may contain commas — split with a limit based on Format if known.
        if format_fields and "text" in format_fields:
            text_idx = format_fields.index("text")
            parts = payload.split(",", text_idx)
            if len(parts) <= text_idx:
                continue
            fields = {format_fields[i]: parts[i].strip() for i in range(min(text_idx, len(format_fields)))}
            start_s = fields.get("start", "")
            end_s = fields.get("end", "")
            body = parts[text_idx]
        else:
            parts = payload.split(",", 9)
            if len(parts) < 10:
                continue
            start_s, end_s, body = parts[1], parts[2], parts[9]
        sm = _ASS_TIME.fullmatch(start_s.strip())
        em = _ASS_TIME.fullmatch(end_s.strip())
        if not sm or not em:
            continue
        start = _hms_to_ms(sm.group(1), sm.group(2), sm.group(3), sm.group(4), ass=True)
        end = _hms_to_ms(em.group(1), em.group(2), em.group(3), em.group(4), ass=True)
        cleaned = strip_ass_tags(body)
        if cleaned:
            cues.append(Cue(start, end, cleaned))
    return cues


def parse_subtitle_file(path: Path | str) -> list[Cue]:
    path = Path(path)
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    suffix = path.suffix.lower()
    if suffix in {".ass", ".ssa"}:
        return parse_ass(raw)
    if suffix == ".srt":
        return parse_srt(raw)
    # Sniff
    if "[Events]" in raw or "Dialogue:" in raw:
        return parse_ass(raw)
    return parse_srt(raw)
