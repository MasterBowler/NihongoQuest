# Nihongo Quest · 日本語クエスト

Fullscreen Japanese learning dojo for Windows. Built in Python with PySide6.

## What’s inside

- **10,000 vocabulary items** for fluency (JLPT N5→N1 plus high-frequency extras), each with kanji/kana, romaji, pitch accent, example sentences, and TTS audio
- **FSRS spaced repetition** for vocab and kanji (Again / Hard / Good / Easy)
- **Kanji course** (~2,270 characters) with KanjiVG stroke-order animation and handwriting practice
- **Lexicon + Kanji atlas** search (kanji, kana, romaji, English)
- **Kana dojo** gojūon chart and drills
- **Daily quests, XP ranks, streak, retention stats**
- Anime / JRPG-inspired ink-night UI with washi reading panels
- **Immersion (Anime)**: play MKV/MP4 with soft subtitle tracks, synced JA / romaji / EN, clickable dictionary, save phrases; optional LM Studio EN drafts

Data sources: JMdict, KANJIDIC, KanjiVG, frequency corpora, JLPT word lists (see `tools/`).

## Run

```bat
run.bat
```

Or manually:

```bat
py -3.14 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m nihongo_quest
```

`data/content.db` is already built. To rebuild from upstream sources:

```bat
.venv\Scripts\python tools\fetch_sources.py
.venv\Scripts\python tools\build_data.py
```

## Controls

| Key | Action |
|-----|--------|
| F11 | Toggle fullscreen |
| F2 | Toggle magnifier loupe |
| Ctrl + / − / 0 | UI zoom in / out / reset |
| Esc | Close loupe / leave study / exit fullscreen |
| Space | Reveal / Good / continue lesson |
| 1–4 | Again / Hard / Good / Easy |
| R | Replay audio |

## Phrases

Nav → **Phrases**: save your own Japanese lines with English.

- Type with **IME** or **romaji** (`arigatou` → ありがとう)
- **Ctrl+V** / drop a screenshot → Windows Japanese OCR (optional online JA→EN gloss)
- **Phrase SRS** reviews them with the same Again/Hard/Good/Easy scheduler

## Meaning images

In the detail pane (Lexicon / Kanji Atlas / study), use **Add image…** to attach your own illustration of a word or kanji’s meaning (car for 車, sun for 日, …). Files are stored under `userdata/images/`. Rows with a picture are marked ◆ and show a hover preview. This is set up so ComfyUI (or similar) can fill the same folder later.

## Immersion (Anime)

Nav → **Immersion**: open an anime file that has **soft** subtitle tracks (ASS/SRT inside the MKV — the same tracks VLC lists). Burned-in hardsubs and PGS/VobSub image tracks are not supported yet.

**Requires:**
- [VLC](https://www.videolan.org/) installed (libVLC; typically `C:\Program Files\VideoLAN\VLC`)
- [ffmpeg](https://ffmpeg.org/) on PATH (or set **Settings → ffmpeg path**), used to list/extract subtitle tracks
- Optional: [LM Studio](https://lmstudio.ai/) local server for “Translate line” when you have no English track (enable in Settings)

Video opens in a **separate VLC window** (controlled over VLC’s HTTP interface). That keeps Nihongo Quest responsive — in-process embedding froze the Qt UI on Windows. Drag VLC to your other screen; Japanese / romaji / English stay synced here. **Close video** quits that VLC instance.

Click underlined Japanese words to open them in the detail rail; select a span or use **Save phrase** to send the line into Phrases / Phrase SRS.

Progress lives in `userdata/` (ignored by git). Neural TTS (Nanami/Keita) needs network the first time a phrase is spoken; audio is cached. Offline mode uses the installed Japanese Windows voice.
