"""List / extract embedded subtitle tracks via ffmpeg/ffprobe."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


@dataclass(frozen=True)
class SubtitleTrack:
    index: int          # stream index in the file
    sub_index: int      # 0-based among subtitle streams (for -map 0:s:N)
    codec: str
    language: str
    title: str
    is_text: bool

    @property
    def label(self) -> str:
        bits = [f"#{self.sub_index}"]
        if self.language:
            bits.append(self.language)
        if self.title:
            bits.append(self.title)
        bits.append(self.codec)
        return " · ".join(bits)


def _which(name: str) -> str | None:
    return shutil.which(name)


def resolve_ffmpeg(ffmpeg_path: str = "") -> tuple[str, str]:
    """Return (ffmpeg, ffprobe) executable paths."""
    custom = (ffmpeg_path or "").strip().strip('"')
    if custom:
        base = Path(custom)
        if base.is_dir():
            ff = base / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
            fp = base / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        else:
            ff = base
            fp = base.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
            if not fp.exists():
                fp = base.parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if ff.exists():
            return str(ff), str(fp) if fp.exists() else str(ff).replace("ffmpeg", "ffprobe")

    ff = _which("ffmpeg")
    fp = _which("ffprobe")
    if ff and fp:
        return ff, fp

    # Bundled binary from imageio-ffmpeg (ffmpeg only; ffprobe may be absent).
    try:
        import imageio_ffmpeg
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled:
            probe = _which("ffprobe")
            if probe:
                return bundled, probe
            # Some builds ship ffprobe next to ffmpeg.
            sibling = Path(bundled).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
            if sibling.exists():
                return bundled, str(sibling)
            return bundled, bundled  # last resort: ffmpeg -i probing via our JSON path below
    except Exception:  # noqa: BLE001
        pass

    raise FFmpegError(
        "ffmpeg/ffprobe not found. Install ffmpeg and add it to PATH, "
        "or set the ffmpeg path in Settings."
    )


def ffmpeg_available(ffmpeg_path: str = "") -> bool:
    try:
        resolve_ffmpeg(ffmpeg_path)
        return True
    except FFmpegError:
        return False


def _run(cmd: list[str], *, timeout: float = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except FileNotFoundError as exc:
        raise FFmpegError(f"Could not run {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError("ffmpeg timed out") from exc


def list_subtitle_tracks(media: Path | str, ffmpeg_path: str = "") -> list[SubtitleTrack]:
    media = Path(media)
    if not media.exists():
        raise FFmpegError(f"File not found: {media}")
    ffmpeg, ffprobe = resolve_ffmpeg(ffmpeg_path)

    tracks: list[SubtitleTrack] = []
    if Path(ffprobe).name.lower().startswith("ffprobe"):
        proc = _run([
            ffprobe, "-v", "quiet", "-print_format", "json",
            "-show_streams", "-select_streams", "s", str(media),
        ])
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            sub_i = 0
            for stream in data.get("streams") or []:
                if stream.get("codec_type") != "subtitle":
                    continue
                tags = stream.get("tags") or {}
                codec = (stream.get("codec_name") or "").lower()
                image_codecs = {
                    "hdmv_pgs_subtitle", "dvd_subtitle", "dvdsub", "pgssub", "xsub", "dvb_subtitle",
                }
                is_text = codec not in image_codecs
                tracks.append(SubtitleTrack(
                    index=int(stream.get("index", 0)),
                    sub_index=sub_i,
                    codec=codec or "unknown",
                    language=(tags.get("language") or tags.get("LANGUAGE") or "").strip(),
                    title=(tags.get("title") or tags.get("TITLE") or "").strip(),
                    is_text=is_text,
                ))
                sub_i += 1
            return tracks

    # Fallback: parse `ffmpeg -i` stderr
    proc = _run([ffmpeg, "-hide_banner", "-i", str(media)], timeout=60)
    blob = (proc.stderr or "") + "\n" + (proc.stdout or "")
    return re_find_streams(blob)


def re_find_streams(blob: str) -> list[SubtitleTrack]:
    import re
    # Stream #0:5(jpn): Subtitle: ass (default)
    pat = re.compile(
        r"Stream #0:(\d+)(?:\(([^)]+)\))?: Subtitle: ([^\s,(]+)",
        re.IGNORECASE,
    )
    out: list[SubtitleTrack] = []
    for i, m in enumerate(pat.finditer(blob)):
        codec = m.group(3).lower()
        is_text = codec not in {"hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvdsub", "xsub"}
        out.append(SubtitleTrack(
            index=int(m.group(1)),
            sub_index=i,
            codec=codec,
            language=(m.group(2) or "").strip(),
            title="",
            is_text=is_text,
        ))
    return out


def extract_subtitle_track(
    media: Path | str,
    track: SubtitleTrack,
    *,
    dest_dir: Path | str | None = None,
    ffmpeg_path: str = "",
) -> Path:
    """Extract a text subtitle stream to a temp .ass or .srt file."""
    if not track.is_text:
        raise FFmpegError(
            f"Track {track.label} looks like image subtitles (PGS/VobSub). "
            "Soft text tracks (ASS/SRT) are required for Immersion v1."
        )
    media = Path(media)
    ffmpeg, _ffprobe = resolve_ffmpeg(ffmpeg_path)
    dest_dir = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp(prefix="nq_subs_"))
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Prefer native copy into .ass when codec is ass/ssa; otherwise convert to srt.
    if track.codec in {"ass", "ssa"}:
        out = dest_dir / f"track_{track.sub_index}.ass"
        cmd = [
            ffmpeg, "-y", "-i", str(media),
            "-map", f"0:s:{track.sub_index}", "-c", "copy", str(out),
        ]
    else:
        out = dest_dir / f"track_{track.sub_index}.srt"
        cmd = [
            ffmpeg, "-y", "-i", str(media),
            "-map", f"0:s:{track.sub_index}", "-c:s", "srt", str(out),
        ]

    proc = _run(cmd, timeout=300)
    if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        # Retry forcing ass
        out = dest_dir / f"track_{track.sub_index}.ass"
        cmd = [
            ffmpeg, "-y", "-i", str(media),
            "-map", f"0:s:{track.sub_index}", "-c:s", "ass", str(out),
        ]
        proc = _run(cmd, timeout=300)
        if proc.returncode != 0 or not out.exists():
            err = (proc.stderr or proc.stdout or "").strip()[-500:]
            raise FFmpegError(f"Could not extract subtitle track.\n{err}")
    return out
