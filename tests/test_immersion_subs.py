"""Subtitle parsing and cue lookup for Immersion."""
from __future__ import annotations

from nihongo_quest.core.immersion.cues import Cue, CueTrack, active_cue
from nihongo_quest.core.immersion.subs import parse_ass, parse_srt, strip_ass_tags


def test_strip_ass_tags():
    assert strip_ass_tags(r"{\i1}こんにちは{\i0}") == "こんにちは"
    assert "line" in strip_ass_tags(r"first\Nline").lower() or "first" in strip_ass_tags(r"first\Nline")


def test_parse_srt_basic():
    srt = """1
00:00:01,000 --> 00:00:03,500
こんにちは

2
00:00:04,000 --> 00:00:06,000
世界
"""
    cues = parse_srt(srt)
    assert len(cues) == 2
    assert cues[0].text == "こんにちは"
    assert cues[0].start_ms == 1000
    assert cues[0].end_ms == 3500
    assert cues[1].text == "世界"


def test_parse_ass_dialogue():
    ass = """[Script Info]
Title: test

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,{\\i1}この日は{\\i0}録音
Dialogue: 0,0:00:04.00,0:00:05.00,Default,,0,0,0,,終わり
"""
    cues = parse_ass(ass)
    assert len(cues) == 2
    assert cues[0].text == "この日は録音"
    assert cues[0].start_ms == 1000
    assert cues[0].end_ms == 3500


def test_active_cue_bisect():
    cues = [
        Cue(0, 1000, "a"),
        Cue(1500, 2000, "b"),
        Cue(2000, 3000, "c"),
    ]
    assert active_cue(cues, 500).text == "a"
    assert active_cue(cues, 1200) is None
    assert active_cue(cues, 1500).text == "b"
    assert active_cue(cues, 2500).text == "c"
    track = CueTrack(cues)
    assert track.at(1800).text == "b"
