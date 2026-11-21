"""Visual language: ink-night dojo with washi reading panels and seal-red accents."""

from __future__ import annotations

import re

# Palette -----------------------------------------------------------------
INK = "#0B1220"
INK_DEEP = "#070B14"
PANEL = "#141C2E"
PANEL_RAISED = "#1B253A"
WASHI = "#F4E7D4"
WASHI_DIM = "#E8D7BE"
INK_TEXT = "#1A1520"
FOG = "#C9D2E3"
FOG_DIM = "#8B97AD"
SEAL = "#C23B4B"
SEAL_HOT = "#E24B5C"
GOLD = "#D4A84B"
GOLD_SOFT = "#E6C97A"
SAKURA = "#E8A0B0"
MOSS = "#3FA67A"
SKY = "#5B8DEF"
SHADOW = "#05080F"

STATUS = {
    "unseen": FOG_DIM,
    "new": SKY,
    "learning": GOLD,
    "young": MOSS,
    "mature": "#6EC6A0",
    "known": FOG_DIM,
    "suspended": SEAL,
}

LEVEL_COLOR = {
    5: "#6EC6A0",
    4: "#5B8DEF",
    3: "#D4A84B",
    2: "#E08A4A",
    1: "#C23B4B",
    0: "#9B8CFF",
}


def stylesheet(scale: float = 1.0) -> str:
    """Return the app stylesheet, optionally scaled for UI zoom (0.85–1.75)."""
    scale = max(0.85, min(1.75, float(scale)))
    css = f"""
    * {{
        font-family: "Zen Maru Gothic", "Yu Gothic UI", "Meiryo UI", sans-serif;
        color: {FOG};
        outline: none;
    }}
    QMainWindow, QWidget#Root {{
        background: {INK};
        color: {FOG};
    }}
    QWidget#TopBar {{
        background: {INK_DEEP};
        border-bottom: 1px solid #243049;
    }}
    QWidget#NavRail {{
        background: {INK_DEEP};
        border-right: 1px solid #243049;
    }}
    QWidget#ContextRail {{
        background: {PANEL};
        border-left: 1px solid #243049;
    }}
    QWidget#MainStage {{
        background: {INK};
    }}
    QLabel#Brand {{
        font-family: "Dela Gothic One", "Yu Gothic UI", sans-serif;
        font-size: 22px;
        color: {GOLD_SOFT};
        letter-spacing: 1px;
    }}
    QLabel#BrandSub {{
        font-family: "DotGothic16", "Yu Gothic UI", sans-serif;
        font-size: 11px;
        color: {FOG_DIM};
    }}
    QLabel#HeroJP {{
        font-family: "Klee One", "Yu Mincho", serif;
        font-size: 64px;
        color: {WASHI};
    }}
    QLabel#HeroEN {{
        font-size: 16px;
        color: {FOG_DIM};
    }}
    QLabel#SectionTitle {{
        font-family: "Dela Gothic One", "Yu Gothic UI", sans-serif;
        font-size: 28px;
        color: {WASHI};
    }}
    QLabel#PanelTitle {{
        font-family: "Dela Gothic One", "Yu Gothic UI", sans-serif;
        font-size: 16px;
        color: {GOLD_SOFT};
    }}
    QLabel#WashiWord {{
        font-family: "Klee One", "Yu Mincho", serif;
        font-size: 72px;
        color: {INK_TEXT};
    }}
    QLabel#WashiReading {{
        font-family: "Klee One", "Yu Mincho", serif;
        font-size: 28px;
        color: #5A4638;
    }}
    QLabel#WashiMeaning {{
        font-family: "Zen Maru Gothic", sans-serif;
        font-size: 20px;
        color: #3A2E28;
    }}
    QLabel#StatValue {{
        font-family: "Dela Gothic One", sans-serif;
        font-size: 36px;
        color: {GOLD};
    }}
    QLabel#StatLabel {{
        font-size: 12px;
        color: {FOG_DIM};
    }}
    QPushButton {{
        background: {PANEL_RAISED};
        border: 1px solid #2E3C58;
        border-radius: 10px;
        padding: 10px 16px;
        font-size: 14px;
        color: {FOG};
    }}
    QPushButton:hover {{
        background: #24314A;
        border-color: {GOLD};
    }}
    QPushButton:pressed {{
        background: #1A2438;
    }}
    QPushButton:disabled {{
        color: #556178;
        border-color: #243049;
    }}
    QPushButton#NavBtn {{
        text-align: left;
        padding: 10px 12px;
        border: none;
        border-radius: 10px;
        background: transparent;
        font-size: 14px;
        min-height: 36px;
    }}
    QPushButton#NavBtn:hover {{
        background: {PANEL};
    }}
    QPushButton#NavBtn[active="true"] {{
        background: {PANEL_RAISED};
        color: {GOLD_SOFT};
        border-left: 3px solid {SEAL};
    }}
    QPushButton#Primary {{
        background: {SEAL};
        border: 1px solid {SEAL_HOT};
        color: white;
        font-family: "Dela Gothic One", sans-serif;
        font-size: 16px;
        padding: 14px 22px;
    }}
    QPushButton#Primary:hover {{
        background: {SEAL_HOT};
    }}
    QPushButton#Gold {{
        background: #3A2E14;
        border: 1px solid {GOLD};
        color: {GOLD_SOFT};
    }}
    QPushButton#Ghost {{
        background: transparent;
        border: 1px solid #2E3C58;
    }}
    QPushButton#GradeAgain {{ background: #3A1820; border-color: {SEAL}; color: #F2B4BC; }}
    QPushButton#GradeHard  {{ background: #3A2E14; border-color: {GOLD}; color: {GOLD_SOFT}; }}
    QPushButton#GradeGood  {{ background: #143528; border-color: {MOSS}; color: #A8E6C8; }}
    QPushButton#GradeEasy  {{ background: #14243A; border-color: {SKY}; color: #B7D0FF; }}
    QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
        background: {PANEL};
        border: 1px solid #2E3C58;
        border-radius: 8px;
        padding: 8px 12px;
        selection-background-color: {SEAL};
        font-size: 14px;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border-color: {GOLD};
    }}
    QComboBox QAbstractItemView {{
        background: {PANEL};
        border: 1px solid #2E3C58;
        selection-background-color: {PANEL_RAISED};
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: #2E3C58;
        border-radius: 5px;
        min-height: 30px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QListWidget {{
        background: {PANEL};
        border: 1px solid #243049;
        border-radius: 12px;
        padding: 6px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 10px 12px;
        border-radius: 8px;
        margin: 2px 0;
    }}
    QListWidget::item:selected {{
        background: {PANEL_RAISED};
        color: {GOLD_SOFT};
    }}
    QListWidget::item:hover {{
        background: #1A2438;
    }}
    QProgressBar {{
        background: #1A2438;
        border: none;
        border-radius: 6px;
        text-align: center;
        color: {FOG_DIM};
        height: 12px;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {SEAL}, stop:1 {GOLD});
        border-radius: 6px;
    }}
    QCheckBox, QRadioButton {{
        spacing: 8px;
        font-size: 14px;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 1px solid #2E3C58;
        background: {PANEL};
    }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {SEAL};
        border-color: {SEAL_HOT};
    }}
    QFrame#Card {{
        background: {PANEL};
        border: 1px solid #243049;
        border-radius: 16px;
    }}
    QFrame#Washi {{
        background: {WASHI};
        border: 1px solid {WASHI_DIM};
        border-radius: 18px;
    }}
    QFrame#SealChip {{
        background: {SEAL};
        border-radius: 8px;
        color: white;
        padding: 4px 8px;
    }}
    QSplitter::handle {{
        background: #1A2438;
    }}
    QSplitter::handle:horizontal {{
        width: 6px;
        margin: 8px 0;
        border-left: 1px solid #243049;
        border-right: 1px solid #243049;
    }}
    QSplitter::handle:hover {{
        background: {GOLD};
    }}
    QWidget#BodySplitter {{
        background: {INK};
    }}
    QTabWidget::pane {{
        border: 1px solid #243049;
        border-radius: 12px;
        background: {PANEL};
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        padding: 10px 18px;
        margin-right: 4px;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        color: {FOG_DIM};
    }}
    QTabBar::tab:selected {{
        background: {PANEL};
        color: {GOLD_SOFT};
    }}
    QSlider::groove:horizontal {{
        height: 6px;
        background: #1A2438;
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        width: 16px;
        margin: -5px 0;
        border-radius: 8px;
        background: {GOLD};
    }}
    """
    if abs(scale - 1.0) < 1e-6:
        return css

    def _scale_px(match: re.Match[str]) -> str:
        return f"{max(1, int(round(int(match.group(1)) * scale)))}px"

    return re.sub(r"(\d+)px", _scale_px, css)
