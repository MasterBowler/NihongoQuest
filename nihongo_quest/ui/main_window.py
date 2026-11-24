"""Fullscreen shell: top bar, nav rail, main stage, resizable context pane."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton, QSizePolicy,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from nihongo_quest.core import progress as P
from nihongo_quest.ui import theme as T
from nihongo_quest.ui.panes.home import HomePane
from nihongo_quest.ui.panes.immersion import ImmersionPane
from nihongo_quest.ui.panes.kana import KanaPane
from nihongo_quest.ui.panes.kanji_browser import KanjiBrowserPane
from nihongo_quest.ui.panes.lexicon import LexiconPane
from nihongo_quest.ui.panes.phrases import PhrasesPane
from nihongo_quest.ui.panes.settings import SettingsPane
from nihongo_quest.ui.panes.stats import StatsPane
from nihongo_quest.ui.panes.study import StudyPane
from nihongo_quest.ui.services import AppServices
from nihongo_quest.ui.theme import stylesheet
from nihongo_quest.ui.widgets.detail import DetailPane
from nihongo_quest.ui.widgets.en_ro_pane import EnRoPane
from nihongo_quest.ui.widgets.loupe import MagnifierLoupe
from nihongo_quest.ui.widgets.petals import PetalField


NAV = [
    ("home", "道場", "Home"),
    ("vocab", "単語", "Vocab SRS"),
    ("kanji_study", "漢字", "Kanji SRS"),
    ("phrases", "句", "Phrases"),
    ("phrase_study", "句習", "Phrase SRS"),
    ("lexicon", "辞典", "Lexicon"),
    ("kanji_atlas", "図鑑", "Kanji Atlas"),
    ("immersion", "浸透", "Immersion"),
    ("kana", "仮名", "Kana"),
    ("stats", "統計", "Stats"),
    ("settings", "設定", "Settings"),
]

# Pages that may show the detail rail (study still gates on answer/lesson).
DETAIL_PAGES = {"vocab", "kanji_study", "lexicon", "kanji_atlas", "immersion"}
STUDY_DETAIL_PAGES = {"vocab", "kanji_study"}


class MainWindow(QMainWindow):
    def __init__(self, services: AppServices) -> None:
        super().__init__()
        self.svc = services
        self.setWindowTitle("Nihongo Quest · 日本語クエスト")
        self.setMinimumSize(1100, 700)
        self.resize(1600, 900)
        self._page = "home"
        self._study_wants_detail = False

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_top())
        outer.addWidget(self._build_body(), 1)

        self.petals = PetalField(root)
        self.petals.setGeometry(root.rect())
        self.petals.raise_()

        self.pages: dict[str, QWidget] = {}
        self.home = HomePane(services)
        self.home.open_vocab.connect(lambda: self.show_page("vocab"))
        self.home.open_kanji.connect(lambda: self.show_page("kanji_study"))
        self.home.open_lexicon.connect(lambda: self.show_page("lexicon"))
        self._add("home", self.home)
        self.phrases = PhrasesPane(services)
        self.phrases.open_study.connect(lambda: self.show_page("phrase_study"))
        self._add("phrases", self.phrases)
        self._add("lexicon", LexiconPane(services))
        self._add("kanji_atlas", KanjiBrowserPane(services))
        self._add("immersion", ImmersionPane(services))
        self._add("kana", KanaPane(services))
        self._add("stats", StatsPane(services))
        self._add("settings", SettingsPane(services))

        self._study_vocab: StudyPane | None = None
        self._study_kanji: StudyPane | None = None
        self._study_phrase: StudyPane | None = None

        self.loupe = MagnifierLoupe()
        self.loupe.set_factor(float(self.svc.progress.setting("loupe_factor")))

        QShortcut(QKeySequence(Qt.Key_F11), self, self.toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self._escape)
        QShortcut(QKeySequence(Qt.Key_F2), self, self.loupe.toggle)
        QShortcut(QKeySequence.ZoomIn, self, lambda: self.adjust_zoom(0.05))
        QShortcut(QKeySequence.ZoomOut, self, lambda: self.adjust_zoom(-0.05))
        QShortcut(QKeySequence("Ctrl+0"), self, lambda: self.set_zoom(1.0))
        # Extra bindings common on Windows keyboards
        QShortcut(QKeySequence("Ctrl+="), self, lambda: self.adjust_zoom(0.05))
        QShortcut(QKeySequence("Ctrl+-"), self, lambda: self.adjust_zoom(-0.05))

        self.svc.progress_changed.connect(self._refresh_top)
        self.svc.selection_changed.connect(self._sync_detail)
        self.svc.toast.connect(self._toast)
        self.svc.settings_changed.connect(self._apply_settings)
        self._refresh_top()
        self._apply_settings()
        self.show_page("home")

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(lambda: self.toast_lab.clear())

    def _build_top(self) -> QWidget:
        top = QWidget()
        top.setObjectName("TopBar")
        top.setFixedHeight(56)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(16, 6, 16, 6)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand = QLabel("日本語クエスト")
        brand.setObjectName("Brand")
        sub = QLabel("NIHONGO QUEST")
        sub.setObjectName("BrandSub")
        brand_box.addWidget(brand)
        brand_box.addWidget(sub)
        tl.addLayout(brand_box)
        tl.addStretch(1)
        self.streak_lab = QLabel()
        self.xp_lab = QLabel()
        self.due_lab = QLabel()
        for lab in (self.streak_lab, self.due_lab, self.xp_lab):
            lab.setStyleSheet(
                f"font-family:'Dela Gothic One'; font-size:13px; color:{T.GOLD_SOFT}; padding:0 10px;"
            )
            tl.addWidget(lab)
        self.toast_lab = QLabel()
        self.toast_lab.setStyleSheet(f"color:{T.SAKURA}; padding:0 12px;")
        tl.addWidget(self.toast_lab)
        return top

    def _build_body(self) -> QWidget:
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("BodySplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)

        nav = QWidget()
        nav.setObjectName("NavRail")
        nav.setMinimumWidth(132)
        nav.setMaximumWidth(220)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(8, 12, 8, 12)
        nl.setSpacing(4)
        self.nav_btns: dict[str, QPushButton] = {}
        for key, jp, en in NAV:
            btn = QPushButton(f"{jp}  {en}")
            btn.setObjectName("NavBtn")
            btn.setProperty("active", "false")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda _=False, k=key: self.show_page(k))
            nl.addWidget(btn)
            self.nav_btns[key] = btn
        nl.addStretch(1)
        hint = QLabel("F11 fullscreen\nF2 magnifier\nCtrl± zoom\nEsc leave study")
        hint.setStyleSheet(f"color:{T.FOG_DIM}; font-size:11px; padding:6px;")
        nl.addWidget(hint)
        self.splitter.addWidget(nav)

        self.stack = QStackedWidget()
        self.stack.setObjectName("MainStage")
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.splitter.addWidget(self.stack)

        self.rail = self._build_rail()
        self.splitter.addWidget(self.rail)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([160, 1100, 380])
        return self.splitter

    def _build_rail(self) -> QWidget:
        """Right context rail: 詳細 (JA lexicon) or EN→RO (English immersion helper)."""
        rail = QWidget()
        rail.setObjectName("ContextRail")
        rail.setMinimumWidth(280)
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        switch = QHBoxLayout()
        switch.setContentsMargins(10, 10, 10, 4)
        switch.setSpacing(6)
        self.rail_ja_btn = QPushButton("詳 細")
        self.rail_en_btn = QPushButton("EN→RO")
        for btn, mode in ((self.rail_ja_btn, "ja"), (self.rail_en_btn, "en_ro")):
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, m=mode: self.svc.set_rail_mode(m))
            switch.addWidget(btn)
        switch.addStretch(1)
        lay.addLayout(switch)

        self.rail_stack = QStackedWidget()
        self.detail = DetailPane(self.svc)
        self.en_ro = EnRoPane(self.svc)
        self.rail_stack.addWidget(self.detail)
        self.rail_stack.addWidget(self.en_ro)
        lay.addWidget(self.rail_stack, 1)

        self.svc.rail_mode_changed.connect(self._on_rail_mode)
        self._on_rail_mode(self.svc.rail_mode())
        return rail

    def _on_rail_mode(self, mode: str) -> None:
        en = mode == "en_ro"
        self.rail_ja_btn.setChecked(not en)
        self.rail_en_btn.setChecked(en)
        self.rail_stack.setCurrentWidget(self.en_ro if en else self.detail)

    def _add(self, key: str, widget: QWidget) -> None:
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.pages[key] = widget
        self.stack.addWidget(widget)

    def show_page(self, key: str) -> None:
        if key == "vocab":
            self._ensure_study(P.VOCAB)
            key = "vocab"
        elif key == "kanji_study":
            self._ensure_study(P.KANJI)
            key = "kanji_study"
        elif key == "phrase_study":
            self._ensure_study(P.PHRASE)
            key = "phrase_study"

        widget = self.pages.get(key)
        if widget is None:
            return
        # Always detach Immersion VLC before any page change — a stuck HWND blocks nav.
        immersion = self.pages.get("immersion")
        if immersion is not None and key != "immersion":
            release = getattr(immersion, "release_for_navigation", None)
            if callable(release):
                release()
        self._page = key
        self.stack.setCurrentWidget(widget)
        for k, btn in self.nav_btns.items():
            active = k == key
            btn.setProperty("active", "true" if active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._sync_detail()

    def _ensure_study(self, kind: str) -> None:
        key = {P.VOCAB: "vocab", P.KANJI: "kanji_study", P.PHRASE: "phrase_study"}[kind]
        existing = {
            P.VOCAB: self._study_vocab,
            P.KANJI: self._study_kanji,
            P.PHRASE: self._study_phrase,
        }[kind]
        if existing is not None:
            self.stack.removeWidget(existing)
            existing.deleteLater()
        pane = StudyPane(self.svc, kind)
        done_page = "phrases" if kind == P.PHRASE else "home"
        pane.finished.connect(lambda: self.show_page(done_page))
        if kind in (P.VOCAB, P.KANJI):
            self._study_wants_detail = False
            pane.detail_wanted.connect(self._on_study_detail_wanted)
        if kind == P.VOCAB:
            self._study_vocab = pane
        elif kind == P.KANJI:
            self._study_kanji = pane
        else:
            self._study_phrase = pane
        self.pages[key] = pane
        self.stack.addWidget(pane)
        pane.start()

    def _on_study_detail_wanted(self, on: bool) -> None:
        self._study_wants_detail = bool(on)
        if self._page in STUDY_DETAIL_PAGES:
            self._sync_detail()

    def _sync_detail(self) -> None:
        if self._page in STUDY_DETAIL_PAGES:
            show = self._study_wants_detail
        else:
            show = self._page in DETAIL_PAGES
        was = self.rail.isVisible()
        self.rail.setVisible(show)
        # EN→RO rail is mainly for Immersion English softsubs.
        self.rail_en_btn.setVisible(self._page == "immersion")
        if self._page != "immersion" and self.svc.rail_mode() == "en_ro":
            self.svc.set_rail_mode("ja")
        if show and not was:
            sizes = self.splitter.sizes()
            total = sum(sizes) or 1
            nav = max(sizes[0], 140)
            detail = max(320, min(420, total // 4))
            stage = max(total - nav - detail, 480)
            self.splitter.setSizes([nav, stage, detail])

    def _refresh_top(self) -> None:
        now = self.svc.now()
        prog = self.svc.progress
        info = prog.level_info()
        v = prog.counts(P.VOCAB, now)
        k = prog.counts(P.KANJI, now)
        self.streak_lab.setText(f"連続 {prog.streak(now)}日")
        self.due_lab.setText(f"復習 {v['review'] + k['review']}")
        self.xp_lab.setText(f"Lv.{info['level']}  {info['xp']} XP")

    def _toast(self, text: str) -> None:
        self.toast_lab.setText(text)
        self._toast_timer.start(3500)

    def _apply_settings(self) -> None:
        on = bool(self.svc.progress.setting("petals"))
        self.petals.set_enabled(on)
        if on:
            self.petals.start()
        self.loupe.set_factor(float(self.svc.progress.setting("loupe_factor")))
        self.apply_zoom(float(self.svc.progress.setting("ui_scale")))

    def apply_zoom(self, scale: float) -> None:
        scale = max(0.85, min(1.75, round(float(scale), 2)))
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet(scale))
        # Top bar height tracks zoom a little so titles don't clip.
        top = self.findChild(QWidget, "TopBar")
        if top is not None:
            top.setFixedHeight(max(48, int(56 * scale)))

    def set_zoom(self, scale: float) -> None:
        self.svc.progress.set_setting("ui_scale", round(float(scale), 2))
        self.apply_zoom(scale)
        self.svc.toast.emit(f"UI zoom {scale:.0%}")

    def adjust_zoom(self, delta: float) -> None:
        current = float(self.svc.progress.setting("ui_scale"))
        self.set_zoom(current + delta)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _escape(self) -> None:
        if self.loupe.active:
            self.loupe.stop()
            return
        if self._page == "immersion":
            immersion = self.pages.get("immersion")
            force = getattr(immersion, "_force_release_embed", None)
            if callable(force):
                force()
            self.show_page("home")
            return
        if self.stack.currentWidget() in (self._study_vocab, self._study_kanji, self._study_phrase):
            page = "phrases" if self.stack.currentWidget() is self._study_phrase else "home"
            self.show_page(page)
        elif self.isFullScreen():
            self.showNormal()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.petals.setGeometry(self.centralWidget().rect())

    def closeEvent(self, event) -> None:  # noqa: N802
        self.loupe.stop()
        self.svc.close()
        super().closeEvent(event)
