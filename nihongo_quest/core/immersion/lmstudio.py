"""Optional JA→EN translation via LM Studio's OpenAI-compatible HTTP API."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


def translate_ja_to_en_lm(
    text: str,
    *,
    base_url: str = "http://127.0.0.1:1234/v1",
    model: str = "",
    timeout: float = 60.0,
) -> str:
    """Return English draft or '' on failure."""
    text = (text or "").strip()
    if not text:
        return ""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model or "local",
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You translate Japanese dialogue/subtitles into natural English. "
                    "Return only the English translation, no quotes or commentary."
                ),
            },
            {"role": "user", "content": text},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return ""
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""
    return (content or "").strip().strip('"').strip()


def lmstudio_reachable(base_url: str = "http://127.0.0.1:1234/v1", timeout: float = 2.0) -> bool:
    url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:  # noqa: BLE001
        return False
