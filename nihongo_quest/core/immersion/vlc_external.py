"""Drive a separate VLC.exe process via its HTTP interface.

In-process python-vlc + Qt freezes the UI on Windows (HWND / lock contention).
Launching VLC out-of-process keeps Nihongo Quest responsive while we poll time
for subtitle sync.
"""
from __future__ import annotations

import base64
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


DEFAULT_PASSWORD = "nihongoquest"
DEFAULT_PORT = 9090


@dataclass
class VlcStatus:
    time_ms: int = 0
    length_ms: int = 0
    state: str = "stopped"  # playing | paused | stopped | …
    fullscreen: bool = False

    @property
    def is_playing(self) -> bool:
        return self.state == "playing"


def find_vlc_exe() -> Path | None:
    env = os.environ.get("VLC_PATH", "").strip().strip('"')
    candidates: list[Path] = []
    if env:
        p = Path(env)
        candidates.append(p if p.suffix.lower() == ".exe" else p / "vlc.exe")
    candidates += [
        Path(r"C:\Program Files\VideoLAN\VLC\vlc.exe"),
        Path(r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"),
    ]
    which = __import__("shutil").which("vlc")
    if which:
        candidates.append(Path(which))
    for c in candidates:
        if c.exists():
            return c
    return None


class ExternalVlc:
    """One VLC process + HTTP remote."""

    def __init__(
        self,
        *,
        port: int = DEFAULT_PORT,
        password: str = DEFAULT_PASSWORD,
    ) -> None:
        self.port = port
        self.password = password
        self._proc: subprocess.Popen | None = None
        self._exe = find_vlc_exe()

    @property
    def available(self) -> bool:
        return self._exe is not None

    @property
    def exe_path(self) -> Path | None:
        return self._exe

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _auth_header(self) -> str:
        token = base64.b64encode(f":{self.password}".encode()).decode()
        return f"Basic {token}"

    def _request(self, query: str = "", *, timeout: float = 0.4) -> str | None:
        url = f"http://127.0.0.1:{self.port}/requests/status.xml"
        if query:
            url = f"{url}?{query}"
        req = urllib.request.Request(
            url,
            headers={"Authorization": self._auth_header()},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError):
            return None

    def start(self, media: Path | str, *, extra_args: list[str] | None = None) -> None:
        if self._exe is None:
            raise RuntimeError("VLC.exe not found. Install VLC from videolan.org.")
        self.stop()
        media = Path(media)
        args = [
            str(self._exe),
            str(media),
            "--extraintf", "http",
            "--http-host", "127.0.0.1",
            "--http-port", str(self.port),
            "--http-password", self.password,
            "--no-video-title-show",
            "--sub-track", "-1",
            "--no-qt-privacy-ask",
            "--no-qt-updates-notif",
        ]
        if extra_args:
            args.extend(extra_args)
        creation = 0
        if os.name == "nt":
            creation = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation,
        )
        # Wait briefly for HTTP to come up.
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError("VLC exited immediately — check the video file.")
            if self._request(timeout=0.3) is not None:
                return
            time.sleep(0.2)
        # Process up but HTTP slow — still usable; status poll will retry.

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._request("command=pl_stop", timeout=0.3)
            except Exception:  # noqa: BLE001
                pass
            try:
                self._proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None

    def status(self) -> VlcStatus | None:
        xml = self._request(timeout=0.35)
        if not xml:
            return None
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return None
        def _int(tag: str) -> int:
            el = root.find(tag)
            if el is None or el.text is None:
                return 0
            try:
                return int(float(el.text))
            except ValueError:
                return 0
        state_el = root.find("state")
        state = (state_el.text or "stopped") if state_el is not None else "stopped"
        fs = root.find("fullscreen")
        fullscreen = (fs is not None and (fs.text or "").strip() in {"1", "true", "yes"})
        return VlcStatus(
            time_ms=_int("time") * 1000,
            length_ms=_int("length") * 1000,
            state=state,
            fullscreen=fullscreen,
        )

    def toggle_pause(self) -> None:
        self._request("command=pl_pause")

    def play(self) -> None:
        self._request("command=pl_play")

    def pause(self) -> None:
        # pl_pause toggles; prefer pause if playing
        st = self.status()
        if st and st.is_playing:
            self._request("command=pl_pause")

    def seek_ms(self, ms: int) -> None:
        sec = max(0, int(ms // 1000))
        self._request(f"command=seek&val={urllib.parse.quote(str(sec))}")
