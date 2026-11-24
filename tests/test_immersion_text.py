from pathlib import Path

from nihongo_quest.core.immersion.epub import load_epub
from nihongo_quest.core.immersion.textload import split_paragraphs
from nihongo_quest.core.ocr import OcrLine, join_page_lines


def test_split_paragraphs_blank_lines():
    text = "こんにちは。\n\n今日はいい天気です。\n\n\n終わり。"
    parts = split_paragraphs(text)
    assert len(parts) == 3
    assert "こんにちは" in parts[0]


def test_join_page_lines_orders_by_y():
    lines = [
        OcrLine("下", y=40, height=10, width=20),
        OcrLine("上", y=10, height=10, width=20),
    ]
    assert join_page_lines(lines) == "上\n下"


def test_load_epub_minimal(tmp_path: Path):
    # Build a tiny EPUB zip by hand.
    import zipfile

    rootfile = "OEBPS/content.opf"
    html = "<html><head><title>一章</title></head><body><p>これは試験です。</p><p>二段落。</p></body></html>"
    opf = f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <manifest>
    <item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
  </spine>
</package>
"""
    container = f"""<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="{rootfile}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    epub = tmp_path / "sample.epub"
    with zipfile.ZipFile(epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container)
        zf.writestr(rootfile, opf)
        zf.writestr("OEBPS/chap1.xhtml", html)
    chapters = load_epub(epub)
    assert chapters
    assert any("試験" in p for p in chapters[0].paragraphs)
