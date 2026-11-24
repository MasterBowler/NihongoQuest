"""Download the open datasets Nihongo Quest is built from into data/raw/.

Only the standard library is used so this can run before any dependency is
installed. Files that already exist are skipped, so the script is safe to
re-run; pass --force to download everything again.

Sources (see README.md → Credits for licences and links):
  * JMdict / KANJIDIC2 / KRADFILE  (EDRDG) via scriptin/jmdict-simplified
  * KanjiVG stroke order data      (Ulrich Apel)
  * JLPT word lists                (Jonathan Waller) via stephenmk/yomitan-jlpt-vocab
                                   and jamsinclair/open-anki-jlpt-decks
  * JLPT kanji levels              via davidluzgouveia/kanji-data
  * Pitch accent data              (Kanjium, mifunetoshiro)
  * Furigana transcriptions        (Tatoeba)
  * Radical names and meanings     (Kanji alive)
  * Per-kanji word readings        (JmdictFurigana, Doublevil)
  * Fonts                          (Google Fonts, OFL) -> assets/fonts/
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
FONT_DIR = ROOT / "assets" / "fonts"
UA = {"User-Agent": "NihongoQuest-data-builder/1.0 (python urllib)"}

# Bundled so the app looks the same on every machine.
FONTS = {
    "delagothicone": ["DelaGothicOne-Regular.ttf"],                      # display / titles
    "zenmarugothic": ["ZenMaruGothic-Medium.ttf", "ZenMaruGothic-Bold.ttf", "ZenMaruGothic-Black.ttf"],  # UI text
    "kleeone": ["KleeOne-SemiBold.ttf"],                                 # textbook-style glyphs for study cards
    "dotgothic16": ["DotGothic16-Regular.ttf"],                          # retro RPG numerals
}


def _open(url: str, timeout: int = 60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)


def download(url: str, dest: Path, force: bool = False) -> Path:
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"  cached  {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_err: Exception | None = None
    for attempt in range(1, 5):
        try:
            with _open(url) as resp, open(tmp, "wb") as fh:
                shutil.copyfileobj(resp, fh, length=1 << 20)
            tmp.replace(dest)
            print(f"  fetched {dest.name}  ({dest.stat().st_size / 1e6:.1f} MB)")
            return dest
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            last_err = err
            print(f"  attempt {attempt} failed for {dest.name}: {err}")
            time.sleep(2 * attempt)
    raise RuntimeError(f"could not download {url}: {last_err}")


def latest_release_assets(repo: str) -> dict[str, str]:
    """Return {asset name: download url} of the latest GitHub release."""
    with _open(f"https://api.github.com/repos/{repo}/releases/latest") as resp:
        rel = json.load(resp)
    return {a["name"]: a["browser_download_url"] for a in rel["assets"]}


def pick(assets: dict[str, str], prefix: str, suffix: str) -> tuple[str, str]:
    for name, url in assets.items():
        if name.startswith(prefix) and name.endswith(suffix):
            return name, url
    raise RuntimeError(f"no release asset matching {prefix}*{suffix}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    args = ap.parse_args(argv)
    RAW.mkdir(parents=True, exist_ok=True)

    print("JMdict / KANJIDIC2 / KRADFILE (jmdict-simplified)")
    assets = latest_release_assets("scriptin/jmdict-simplified")
    for prefix, target in (
        ("jmdict-examples-eng-", "jmdict-examples-eng.json.zip"),
        ("kanjidic2-en-", "kanjidic2-en.json.zip"),
        ("kradfile-", "kradfile.json.zip"),
    ):
        _, url = pick(assets, prefix, ".json.zip")
        download(url, RAW / target, args.force)

    print("JmdictFurigana (per-kanji readings of dictionary words)")
    assets = latest_release_assets("Doublevil/JmdictFurigana")
    download(assets["JmdictFurigana.json.zip"], RAW / "jmdict-furigana.json.zip", args.force)

    print("KanjiVG")
    assets = latest_release_assets("KanjiVG/kanjivg")
    name, url = next((n, u) for n, u in assets.items() if n.endswith(".xml.gz"))
    download(url, RAW / "kanjivg.xml.gz", args.force)

    print("JLPT vocabulary lists")
    for lvl in (5, 4, 3, 2, 1):
        download(
            f"https://raw.githubusercontent.com/stephenmk/yomitan-jlpt-vocab/main/original_data/n{lvl}.csv",
            RAW / f"jlpt_n{lvl}.csv",
            args.force,
        )

    gh = "https://raw.githubusercontent.com"
    for lvl in (5, 4, 3, 2, 1):     # a second transcription of the same lists, used to fill gaps
        download(f"{gh}/jamsinclair/open-anki-jlpt-decks/main/src/n{lvl}.csv", RAW / f"openanki_n{lvl}.csv", args.force)

    print("Kanji metadata, pitch accent, furigana, radicals")
    for url, target in (
        (f"{gh}/davidluzgouveia/kanji-data/master/kanji.json", "kanji-data.json"),
        (f"{gh}/mifunetoshiro/kanjium/master/data/source_files/raw/accents.txt", "kanjium_accents.txt"),
        ("https://downloads.tatoeba.org/exports/per_language/jpn/jpn_transcriptions.tsv.bz2", "tatoeba_jpn_transcriptions.tsv.bz2"),
        (f"{gh}/kanjialive/kanji-data-media/master/language-data/ka_data.csv", "kanjialive_ka_data.csv"),
        (f"{gh}/kanjialive/kanji-data-media/master/language-data/japanese-radicals.csv", "kanjialive_radicals.csv"),
    ):
        download(url, RAW / target, args.force)

    print("Fonts (SIL Open Font License, from google/fonts)")
    for family, files in FONTS.items():
        base = f"{gh}/google/fonts/main/ofl/{family}"
        for fname in files:
            download(f"{base}/{fname}", FONT_DIR / fname, args.force)
        download(f"{base}/OFL.txt", FONT_DIR / f"OFL-{family}.txt", args.force)

    print("done ->", RAW, "and", FONT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
