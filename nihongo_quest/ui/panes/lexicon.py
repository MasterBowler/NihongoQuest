"""Searchable 10,000-word lexicon with JLPT / Core frequency filters and browse view."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from nihongo_quest.core import progress as P
from nihongo_quest.core.content import LEVEL_NAMES, Word
from nihongo_quest.ui import theme as T
from nihongo_quest.ui.services import AppServices
from nihongo_quest.ui.widgets.furigana import FuriganaLabel
from nihongo_quest.ui.widgets.meaning_image import ImageHoverPopup
from nihongo_quest.ui.widgets.pitch import PitchDiagram


CORE_OPTIONS = (
    ("All frequencies", None),
    ("Core 100", 100),
    ("Core 500", 500),
    ("Core 1,000", 1000),
    ("Core 2,000", 2000),
    ("Core 5,000", 5000),
    ("Core 10,000", 10000),
)


class LexiconPane(QWidget):
    def __init__(self, services: AppServices, parent=None) -> None:
        super().__init__(parent)
        self.svc = services
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._hover = ImageHoverPopup()
        self._filtered: list[Word] = []
        self._browse_index = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.stack.addWidget(self._build_list_page())
        self.stack.addWidget(self._build_browse_page())

        self.svc.progress_changed.connect(self._refresh_status_colors)
        self.svc.images_changed.connect(self._refilter)
        self._refilter()

        QShortcut(QKeySequence(Qt.Key_Left), self, self._browse_prev)
        QShortcut(QKeySequence(Qt.Key_Right), self, self._browse_next)
        QShortcut(QKeySequence(Qt.Key_Return), self, self._open_selected)
        QShortcut(QKeySequence(Qt.Key_Enter), self, self._open_selected)

    def _build_list_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        title = QLabel("辞典 · Lexicon")
        title.setObjectName("SectionTitle")
        lay.addWidget(title)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search kanji, kana, romaji or English…")
        self.search.textChanged.connect(self._refilter)
        search_row.addWidget(self.search, 1)
        self.open_btn = QPushButton("Open full view")
        self.open_btn.clicked.connect(self._open_selected)
        search_row.addWidget(self.open_btn)
        lay.addLayout(search_row)

        filters = QHBoxLayout()
        self.level_boxes: dict[int, QCheckBox] = {}
        for level in (5, 4, 3, 2, 1, 0):
            box = QCheckBox(LEVEL_NAMES[level])
            box.setChecked(True)
            box.stateChanged.connect(self._refilter)
            color = T.LEVEL_COLOR[level]
            box.setStyleSheet(f"QCheckBox {{ color: {color}; }}")
            self.level_boxes[level] = box
            filters.addWidget(box)
        filters.addStretch(1)
        lay.addLayout(filters)

        sort_row = QHBoxLayout()
        sort_row.addWidget(QLabel("Usage"))
        self.core_box = QComboBox()
        for label, _n in CORE_OPTIONS:
            self.core_box.addItem(label)
        self.core_box.currentIndexChanged.connect(self._refilter)
        sort_row.addWidget(self.core_box)
        sort_row.addWidget(QLabel("Sort"))
        self.sort_box = QComboBox()
        self.sort_box.addItem("Course / JLPT order", "course")
        self.sort_box.addItem("Frequency (most used first)", "frequency")
        self.sort_box.currentIndexChanged.connect(self._refilter)
        sort_row.addWidget(self.sort_box)
        sort_row.addStretch(1)
        self.count_lab = QLabel()
        self.count_lab.setStyleSheet(f"color:{T.FOG_DIM};")
        sort_row.addWidget(self.count_lab)
        lay.addLayout(sort_row)

        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.viewport().setMouseTracking(True)
        self.list.currentItemChanged.connect(self._picked)
        self.list.itemDoubleClicked.connect(lambda _item: self._open_selected())
        self.list.itemEntered.connect(self._hovered)
        self.list.viewport().installEventFilter(self)
        lay.addWidget(self.list, 1)

        hint = QLabel(
            "Double-click or Open for full view (← → cycle, ← List to return). "
            "Hover ◆ rows for meaning images."
        )
        hint.setStyleSheet(f"color:{T.FOG_DIM}; font-size:12px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return page

    def _build_browse_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        nav = QHBoxLayout()
        self.back_list_btn = QPushButton("← List")
        self.back_list_btn.clicked.connect(self._back_to_list)
        nav.addWidget(self.back_list_btn)
        self.prev_btn = QPushButton("◀ Previous")
        self.prev_btn.clicked.connect(self._browse_prev)
        nav.addWidget(self.prev_btn)
        self.pos_lab = QLabel()
        self.pos_lab.setAlignment(Qt.AlignCenter)
        self.pos_lab.setStyleSheet(f"color:{T.GOLD_SOFT};")
        nav.addWidget(self.pos_lab, 1)
        self.next_btn = QPushButton("Next ▶")
        self.next_btn.clicked.connect(self._browse_next)
        nav.addWidget(self.next_btn)
        self.browse_speak = QPushButton("♪")
        self.browse_speak.setFixedWidth(48)
        self.browse_speak.clicked.connect(self._browse_speak)
        nav.addWidget(self.browse_speak)
        lay.addLayout(nav)

        card = QWidget()
        card.setObjectName("Washi")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(28, 24, 28, 24)
        cl.setSpacing(10)
        self.browse_furi = FuriganaLabel(base_pt=64, ruby_pt=16)
        cl.addWidget(self.browse_furi)
        self.browse_reading = QLabel()
        self.browse_reading.setObjectName("WashiReading")
        self.browse_reading.setAlignment(Qt.AlignCenter)
        self.browse_reading.setWordWrap(True)
        cl.addWidget(self.browse_reading)
        self.browse_meaning = QLabel()
        self.browse_meaning.setObjectName("WashiMeaning")
        self.browse_meaning.setAlignment(Qt.AlignCenter)
        self.browse_meaning.setWordWrap(True)
        cl.addWidget(self.browse_meaning)
        self.browse_meta = QLabel()
        self.browse_meta.setAlignment(Qt.AlignCenter)
        self.browse_meta.setStyleSheet("color:#6A5544;")
        cl.addWidget(self.browse_meta)
        self.browse_pitch = PitchDiagram()
        self.browse_pitch.setMaximumHeight(72)
        self.browse_pitch.hide()
        cl.addWidget(self.browse_pitch)
        cl.addStretch(1)
        lay.addWidget(card, 1)

        tip = QLabel("Details & notes stay in the right panel. ← → to cycle · use ← List to return.")
        tip.setStyleSheet(f"color:{T.FOG_DIM}; font-size:12px;")
        lay.addWidget(tip)
        return page

    def eventFilter(self, obj, event):  # noqa: N802
        from PySide6.QtCore import QEvent
        if obj is self.list.viewport() and event.type() in (QEvent.Leave, QEvent.HoverLeave):
            self._hover.hide()
        return super().eventFilter(obj, event)

    def _core_limit(self) -> int | None:
        return CORE_OPTIONS[self.core_box.currentIndex()][1]

    def _sorted_base(self) -> list[Word]:
        if self.sort_box.currentData() == "frequency":
            return list(self.svc.content.by_frequency)
        return list(self.svc.content.words)

    def _refilter(self) -> None:
        levels = {lv for lv, box in self.level_boxes.items() if box.isChecked()}
        core = self._core_limit()
        pool = [w for w in self._sorted_base() if w.level in levels]
        if core is not None:
            pool = [w for w in pool if 0 < w.freq_rank <= core]
        q = self.search.text().strip()
        # Keep frequency order when browsing without a search query.
        words = self.svc.content.search(q, pool=pool, limit=800) if q else pool[:800]
        self._filtered = words
        self.list.clear()
        for w in words:
            item = QListWidgetItem(self._label(w))
            item.setData(Qt.UserRole, w.id)
            status = self.svc.progress.status(P.VOCAB, w.key)
            item.setForeground(QColor(T.STATUS.get(status, T.FOG)))
            self.list.addItem(item)
        pictured = sum(1 for w in words if self.svc.images.has(P.VOCAB, w.key))
        self.count_lab.setText(f"showing {len(words)} / {len(pool)}  ·  {pictured} with images")
        if self.stack.currentIndex() == 1 and self._browse_index >= 0:
            if not words:
                self._back_to_list()
            else:
                self._browse_index = min(self._browse_index, len(words) - 1)
                self._show_browse_at(self._browse_index)

    def _label(self, w: Word) -> str:
        meaning = w.meaning.split("／")[0][:48]
        mark = "◆ " if self.svc.images.has(P.VOCAB, w.key) else "   "
        return (
            f"{mark}{w.word}【{w.kana}】 {w.romaji}   —  {meaning}   "
            f"[{w.level_name}]  #{w.freq_rank}"
        )

    def _picked(self, cur: QListWidgetItem | None, _prev=None) -> None:
        if cur is None:
            return
        word = self.svc.content.word(cur.data(Qt.UserRole))
        self.svc.select_word(word)

    def _hovered(self, item: QListWidgetItem) -> None:
        word = self.svc.content.word(item.data(Qt.UserRole))
        if word is None:
            self._hover.hide()
            return
        path = self.svc.images.path(P.VOCAB, word.key)
        if path is None:
            self._hover.hide()
            return
        self._hover.show_path(path, QCursor.pos())

    def _refresh_status_colors(self) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            word = self.svc.content.word(item.data(Qt.UserRole))
            if word:
                status = self.svc.progress.status(P.VOCAB, word.key)
                item.setForeground(QColor(T.STATUS.get(status, T.FOG)))
                item.setText(self._label(word))

    def _open_selected(self) -> None:
        if self.stack.currentIndex() == 1:
            return
        row = self.list.currentRow()
        if row < 0 and self._filtered:
            row = 0
            self.list.setCurrentRow(0)
        if row < 0 or row >= len(self._filtered):
            self.svc.toast.emit("Select a word first.")
            return
        self._show_browse_at(row)
        self.stack.setCurrentIndex(1)

    def _back_to_list(self) -> None:
        if self.stack.currentIndex() == 0:
            return
        self.stack.setCurrentIndex(0)
        if 0 <= self._browse_index < self.list.count():
            self.list.setCurrentRow(self._browse_index)
            self.list.scrollToItem(self.list.item(self._browse_index))

    def _browse_prev(self) -> None:
        if self.stack.currentIndex() != 1 or not self._filtered:
            return
        self._show_browse_at((self._browse_index - 1) % len(self._filtered))

    def _browse_next(self) -> None:
        if self.stack.currentIndex() != 1 or not self._filtered:
            return
        self._show_browse_at((self._browse_index + 1) % len(self._filtered))

    def _show_browse_at(self, index: int) -> None:
        if not self._filtered:
            return
        index = max(0, min(index, len(self._filtered) - 1))
        self._browse_index = index
        w = self._filtered[index]
        self.svc.select_word(w)
        self.pos_lab.setText(f"{index + 1} / {len(self._filtered)}")
        if w.furi and self.svc.progress.setting("furigana"):
            self.browse_furi.set_segments([(a, b) for a, b in w.furi])
        else:
            self.browse_furi.set_plain(w.word)
        romaji = f"  ·  {w.romaji}" if self.svc.progress.setting("show_romaji") else ""
        self.browse_reading.setText(f"{w.kana}{romaji}")
        self.browse_meaning.setText(w.meaning)
        self.browse_meta.setText(f"{w.level_name}  ·  freq #{w.freq_rank}  ·  {', '.join(self.svc.content.pos_labels(w.pos)[:3])}")
        if w.pitch:
            self.browse_pitch.show()
            self.browse_pitch.set_pitch(w.kana, w.pitch[0])
        else:
            self.browse_pitch.hide()
        self.prev_btn.setEnabled(len(self._filtered) > 1)
        self.next_btn.setEnabled(len(self._filtered) > 1)

    def _browse_speak(self) -> None:
        if 0 <= self._browse_index < len(self._filtered):
            self.svc.speak_word(self._filtered[self._browse_index])

    def hideEvent(self, event) -> None:  # noqa: N802
        self._hover.hide()
        super().hideEvent(event)
