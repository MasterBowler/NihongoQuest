"""Minimal EPUB reader (stdlib only) → ordered chapter plain-text blocks."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET


_TAG_NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "o": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
        elif tag in {"p", "div", "li", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_data(self, data):  # noqa: ANN001
        if self._skip:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    def text(self) -> str:
        raw = " ".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n[ \t]+", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


@dataclass
class EpubChapter:
    title: str
    paragraphs: list[str]


def _strip_html(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def load_epub(path: Path | str) -> list[EpubChapter]:
    path = Path(path)
    with zipfile.ZipFile(path) as zf:
        container = zf.read("META-INF/container.xml")
        root = ET.fromstring(container)
        rootfile = None
        for el in root.iter():
            if _local(el.tag) == "rootfile":
                rootfile = el.attrib.get("full-path")
                break
        if not rootfile:
            raise ValueError("EPUB missing rootfile")
        opf_path = rootfile
        opf_dir = str(Path(opf_path).parent).replace("\\", "/")
        if opf_dir == ".":
            opf_dir = ""

        opf = ET.fromstring(zf.read(opf_path))
        manifest: dict[str, str] = {}
        spine: list[str] = []
        for el in opf.iter():
            name = _local(el.tag)
            if name == "item":
                iid = el.attrib.get("id")
                href = el.attrib.get("href")
                if iid and href:
                    manifest[iid] = href
            elif name == "itemref":
                idref = el.attrib.get("idref")
                if idref:
                    spine.append(idref)

        chapters: list[EpubChapter] = []
        for i, idref in enumerate(spine):
            href = manifest.get(idref)
            if not href:
                continue
            full = f"{opf_dir}/{href}" if opf_dir else href
            full = full.replace("\\", "/")
            # normalize .//
            while "/./" in full:
                full = full.replace("/./", "/")
            try:
                data = zf.read(full)
            except KeyError:
                # try basename search
                name = Path(href).name
                match = next((n for n in zf.namelist() if n.endswith(name)), None)
                if not match:
                    continue
                data = zf.read(match)
            html = data.decode("utf-8", errors="replace")
            text = _strip_html(html)
            if not text:
                continue
            paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
            if not paras:
                paras = [text]
            title = paras[0][:40] if paras else f"Chapter {i + 1}"
            # Prefer <title> if present
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            if m:
                t = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                if t:
                    title = t[:60]
            chapters.append(EpubChapter(title=title or f"Chapter {i + 1}", paragraphs=paras))
        return chapters
