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
- **Immersion (Manga)**: page images with manga-specific OCR overlays (click bubbles / drag-crop), dictionary, translate, save phrases
- **Immersion (Novel)**: `.txt` / `.md` / `.epub` reader with clickable Japanese, translate, save phrases
- **Detail rail**: optional Romanian under JA English glosses; Immersion also has a separate **EN→RO** rail for clicking English softsub words

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

### Windows release (.exe)

```bat
tools\build_exe.bat
```

Run **`dist\NihongoQuest\NihongoQuest.exe`** (keep the whole `dist\NihongoQuest\` folder together — the `_internal\` directory next to the exe is required). Do **not** launch `build\NihongoQuest\NihongoQuest.exe`; that is a PyInstaller intermediate and will fail with “Failed to load Python DLL”.

Zip the entire `dist\NihongoQuest` folder for a GitHub Release. Learner data is written to `userdata\` beside the exe. **Immersion Manga OCR** (torch / manga-ocr / mokuro) is not bundled in the slim exe — use `run.bat` for full manga OCR.

## Controls

| Key | Action |
|-----|--------|
| F11 | Toggle fullscreen |
| F2 | Toggle magnifier loupe |
| Ctrl + / − / 0 | UI zoom in / out / reset |
| Esc | Close loupe / leave study / exit fullscreen |
| Space | Reveal / Good / continue lesson (Anime: pause/resume VLC) |
| 1–4 | Again / Hard / Good / Easy |
| R | Replay audio |

## Phrases

Nav → **Phrases**: save your own Japanese lines with English.

- Type with **IME** or **romaji** (`arigatou` → ありがとう)
- **Ctrl+V** / drop a screenshot → Windows Japanese OCR (optional online JA→EN gloss)
- **Phrase SRS** reviews them with the same Again/Hard/Good/Easy scheduler

## Meaning images

In the detail pane (Lexicon / Kanji Atlas / study), use **Add image…** to attach your own illustration of a word or kanji’s meaning (car for 車, sun for 日, …). Files are stored under `userdata/images/`. Rows with a picture are marked ◆ and show a hover preview. This is set up so ComfyUI (or similar) can fill the same folder later.

## Immersion

Nav → **Immersion** has three modes:

### Anime
Open an MKV/MP4 with **soft** subtitle tracks (ASS/SRT — the same tracks VLC lists). Burned-in hardsubs and PGS/VobSub are not supported yet.

**Requires:** [VLC](https://www.videolan.org/), [ffmpeg](https://ffmpeg.org/) on PATH (or **Settings → ffmpeg path**), optional [LM Studio](https://lmstudio.ai/) for JA→EN drafts.

Video opens in a **separate VLC window** (HTTP control — keeps this app responsive). Drag VLC to another screen; JA / romaji / EN stay synced here.

Japanese softsubs are optional. **English-only** files work for the **EN→RO** rail: pick the EN track (auto-selected when no Japanese track is found), click words in the English line, and look them up in Romanian. Leave **JA subs** on `(none)` if the file has no Japanese track.

### Manga
Open images or a folder (or paste/drop a page). Manga-trained OCR detects text regions on the page; click a bubble or drag-select a crop. Dictionary / translate / save phrases work on the active region. ← → flips pages.

**Requires:** `manga-ocr` + `mokuro` (see `requirements.txt`). First OCR may download models (~400MB+).

### Novel
Open `.txt` / `.md` / `.epub`. Browse chapters and paragraphs; clickable dictionary, translate, save phrases. ← → moves through paragraphs.

In all modes: underlined Japanese opens the **詳 細** rail. In Anime, English softsub words are clickable even without Japanese tracks — use the right-rail switch **EN→RO** (or click an EN word) for Romanian lookups, separate from the Japanese lexicon. Lookups use the free [MyMemory](https://mymemory.translated.net/) `en|ro` API (cached under `userdata/ro_gloss_cache.json`); treat results as drafts, not a polished dictionary. The 詳細 header still has an optional **RO gloss** toggle for Romanian under JMdict English meanings. **Save phrase** goes to Phrases / Phrase SRS.

Progress lives in `userdata/` (ignored by git). Neural TTS (Nanami/Keita) needs network the first time a phrase is spoken; audio is cached. Offline mode uses the installed Japanese Windows voice.

## Credits & third-party resources

Nihongo Quest stands on many open datasets, models, and libraries. Thank you to their authors and maintainers.

### Lexical & learning data

| Resource | Project / author | Use |
|----------|------------------|-----|
| [JMdict](https://www.edrdg.org/jmdict/j_jmdict.html) / [KANJIDIC2](https://www.edrdg.org/wiki/index.php/KANJIDIC_Project) / KRADFILE | Electronic Dictionary Research and Development Group (EDRDG) | Dictionary senses, kanji readings/meanings, radicals |
| [jmdict-simplified](https://github.com/scriptin/jmdict-simplified) | scriptin | JSON packaging of JMdict / KANJIDIC / KRADFILE |
| [JmdictFurigana](https://github.com/Doublevil/JmdictFurigana) | Doublevil | Per-kanji readings on dictionary headwords |
| [KanjiVG](https://github.com/KanjiVG/kanjivg) | Ulrich Apel / KanjiVG | Stroke-order paths |
| [yomitan-jlpt-vocab](https://github.com/stephenmk/yomitan-jlpt-vocab) | stephenmk (lists via Jonathan Waller) | JLPT vocabulary lists |
| [open-anki-jlpt-decks](https://github.com/jamsinclair/open-anki-jlpt-decks) | jamsinclair | Secondary JLPT list coverage |
| [kanji-data](https://github.com/davidluzgouveia/kanji-data) | davidluzgouveia | JLPT kanji metadata |
| [kanjium](https://github.com/mifunetoshiro/kanjium) | mifunetoshiro | Pitch accent |
| [Tatoeba](https://tatoeba.org/) transcriptions | Tatoeba project | Furigana / example support data |
| [Kanji alive](https://github.com/kanjialive/kanji-data-media) | Kanji alive | Radical names and meanings |
| [wordfreq](https://github.com/rspeer/wordfreq) | Robyn Speer | Frequency ranks |

Rebuild helpers live under `tools/` (`fetch_sources.py`, `build_data.py`).

### Immersion / OCR / media

| Resource | Project | Use |
|----------|---------|-----|
| [manga-ocr](https://github.com/kha-white/manga-ocr) | kha-white | Japanese manga text recognition |
| [mokuro](https://github.com/kha-white/mokuro) | kha-white | Page OCR orchestration |
| [comic-text-detector](https://github.com/dmMaze/comic-text-detector) | dmMaze | Text-region detection (via mokuro) |
| [Windows.Media.Ocr](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr) | Microsoft | Screenshot / phrase OCR |
| [VLC](https://www.videolan.org/) | VideoLAN | External Immersion Anime playback |
| [ffmpeg](https://ffmpeg.org/) | FFmpeg project | Soft-subtitle probing / extraction |
| [LM Studio](https://lmstudio.ai/) | Element Labs (optional) | Local JA→EN draft translations |
| [MyMemory](https://mymemory.translated.net/) | Translated | Online JA→EN and EN→RO gloss drafts |

### UI, runtime & TTS

| Resource | Project | Use |
|----------|---------|-----|
| [PySide6](https://doc.qt.io/qtforpython/) / Qt | Qt Company / Riverbank | Desktop UI |
| [edge-tts](https://github.com/rany2/edge-tts) | rany2 | Neural Japanese TTS (Nanami / Keita) |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | imageio | Bundled ffmpeg helper binary |
| [winrt](https://github.com/pywinrt/pywinrt) | PyWinRT | Windows OCR bindings |
| [Dela Gothic One](https://fonts.google.com/specimen/Dela+Gothic+One), [Zen Maru Gothic](https://fonts.google.com/specimen/Zen+Maru+Gothic), [Klee One](https://fonts.google.com/specimen/Klee+One), [DotGothic16](https://fonts.google.com/specimen/DotGothic16) | Google Fonts (OFL) | App typography |

Licences for fonts are under `assets/fonts/OFL-*.txt`. Upstream dataset licences are those of EDRDG, KanjiVG, Tatoeba, and the respective GitHub projects — respect them if you redistribute rebuilt `content.db` or raw downloads.
