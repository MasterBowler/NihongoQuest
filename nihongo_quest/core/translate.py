"""Online gloss helpers (MyMemory). Best-effort drafts — not dictionary-grade."""
from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request

from nihongo_quest.paths import USER

_CACHE_LOCK = threading.Lock()
_CACHE_PATH = USER / "ro_gloss_cache.json"
_memory: dict[str, str] = {}
_loaded = False


def _load_cache() -> None:
    global _loaded, _memory
    if _loaded:
        return
    _loaded = True
    try:
        if _CACHE_PATH.exists():
            data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _memory = {str(k): str(v) for k, v in data.items() if v}
    except Exception:  # noqa: BLE001
        _memory = {}


def _save_cache() -> None:
    try:
        USER.mkdir(parents=True, exist_ok=True)
        # Cap growth — keep the most recently written ~4000 entries.
        items = list(_memory.items())
        if len(items) > 4000:
            items = items[-4000:]
            _memory.clear()
            _memory.update(items)
        _CACHE_PATH.write_text(json.dumps(_memory, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _mymemory(text: str, langpair: str, timeout: float = 8.0) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    try:
        q = urllib.parse.urlencode({"q": text[:450], "langpair": langpair})
        url = f"https://api.mymemory.translated.net/get?{q}"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = (data.get("responseData") or {}).get("translatedText") or ""
        out = out.strip()
        return "" if out == text.strip() else out
    except Exception:  # noqa: BLE001
        return ""


def translate_ja_to_en(text: str, timeout: float = 8.0) -> str:
    return _mymemory(text, "ja|en", timeout=timeout)


def translate_en_to_ro(text: str, timeout: float = 8.0) -> str:
    """Translate an English gloss to Romanian (cached). Empty string on failure."""
    text = (text or "").strip()
    if not text:
        return ""
    with _CACHE_LOCK:
        _load_cache()
        hit = _memory.get(text)
        if hit is not None:
            return hit
    out = _mymemory(text, "en|ro", timeout=timeout)
    with _CACHE_LOCK:
        _load_cache()
        _memory[text] = out
        _save_cache()
    return out


def translate_en_batch_to_ro(texts: list[str], timeout: float = 8.0) -> dict[str, str]:
    """Map each unique English string to Romanian (skips blanks)."""
    result: dict[str, str] = {}
    seen: set[str] = set()
    for raw in texts:
        text = (raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ro = translate_en_to_ro(text, timeout=timeout)
        if ro:
            result[text] = ro
    return result
