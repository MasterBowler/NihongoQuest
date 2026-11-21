"""Anime immersion: MKV softsubs, cue sync, lexicon match, LM Studio helpers."""

from nihongo_quest.core.immersion.cues import Cue, CueTrack, active_cue
from nihongo_quest.core.immersion.ffprobe import (
    SubtitleTrack,
    extract_subtitle_track,
    ffmpeg_available,
    list_subtitle_tracks,
)
from nihongo_quest.core.immersion.lmstudio import translate_ja_to_en_lm
from nihongo_quest.core.immersion.subs import parse_subtitle_file
from nihongo_quest.core.immersion.tokenize import Token, tokenize_japanese
from nihongo_quest.core.immersion.vlc_external import ExternalVlc, find_vlc_exe

__all__ = [
    "Cue",
    "CueTrack",
    "Token",
    "SubtitleTrack",
    "ExternalVlc",
    "active_cue",
    "extract_subtitle_track",
    "ffmpeg_available",
    "find_vlc_exe",
    "list_subtitle_tracks",
    "parse_subtitle_file",
    "tokenize_japanese",
    "translate_ja_to_en_lm",
]
