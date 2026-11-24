# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a slim Windows release (no torch / manga-ocr)."""
from __future__ import annotations

from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve()

datas: list = [
    (str(ROOT / "data" / "content.db"), "data"),
    (str(ROOT / "assets" / "fonts"), "assets/fonts"),
]
try:
    datas += collect_data_files("edge_tts")
except Exception:
    pass

hiddenimports = [
    "nihongo_quest",
    "nihongo_quest.app",
    "edge_tts",
    "wordfreq",
    "imageio_ffmpeg",
    "winrt",
    "winrt.windows.media.ocr",
    "winrt.windows.globalization",
    "winrt.windows.graphics.imaging",
    "winrt.windows.storage",
    "winrt.windows.storage.streams",
    "winrt.windows.foundation",
    # Used by Immersion / TTS / OCR paths
    "PySide6.QtMultimedia",
    "PySide6.QtTextToSpeech",
]

# Keep the release slim — manga OCR stack is multi-hundred MB;
# also drop unused Qt modules that hooks might otherwise pull.
excludes = [
    "torch",
    "torchvision",
    "torchaudio",
    "manga_ocr",
    "mokuro",
    "transformers",
    "tensorflow",
    "tensorboard",
    "matplotlib",
    "scipy",
    "sklearn",
    "cv2",
    "IPython",
    "notebook",
    "PySide6.QtWebEngine",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebView",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
]

a = Analysis(
    [str(ROOT / "nihongo_quest" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# Drop heavy Qt plugin trees if Analysis still collected them.
_DROP_SUBSTR = (
    "Qt6WebEngine",
    "QtWebEngine",
    "Qt6Pdf",
    "Qt6Charts",
    "Qt6DataVisualization",
    "Qt63D",
    "Qt6Quick3D",
    "Qt6ShaderTools",
    "translations\\qtwebengine",
)


def _keep(entry) -> bool:
    # TOC entries are (dest, source, type) tuples.
    name = str(entry[0]) if entry else ""
    src = str(entry[1]) if len(entry) > 1 else ""
    blob = name + "|" + src
    return not any(s in blob for s in _DROP_SUBSTR)


a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NihongoQuest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NihongoQuest",
)
