"""Kanji course browser with frequency filters, browse view, and stroke replay."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QCursor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from nihongo_quest.core import progress as P
from nihongo_quest.core.content import LEVEL_NAMES, Kanji
from nihongo_quest.ui import theme as T
from nihongo_quest.ui.services import AppServices
from nihongo_quest.ui.widgets.meaning_image import ImageHoverPopup
from nihongo_quest.ui.widgets.stroke_canvas import StrokeCanvas


CORE_OPTIONS = (
    ("All frequencies", None),
    ("Core 100", 100),
    ("Core 500", 500),
    ("Core 1,000", 1000),
    ("Core 2,000", 2000),
)


class KanjiBrowserPane(QWidget):
    def __init__(self, services: AppServices, parent=None) -> None:
        super().__init__(parent)
        self.svc = services
        self._hover = ImageHoverPopup()
        self._filtered: list[Kanji] = []
        self._browse_index = -1
        self._by_freq = sorted(
            (k for k in services.content.course if k.freq),
            key=lambda k: k.freq,
        ) + [k for k in services.content.course if not k.freq]

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_list_page())
        self.stack.addWidget(self._build_browse_page())

        self.svc.progress_changed.connect(self._refilter)
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

        title = QLabel("漢字図鑑 · Kanji Atlas")
        title.setObjectName("SectionTitle")
        lay.addWidget(title)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search character, meaning, or reading…")
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
            box.setStyleSheet(f"QCheckBox {{ color: {T.LEVEL_COLOR[level]}; }}")
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
        self.sort_box.addItem("Course order", "course")
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
            f"Course size: {len(self.svc.content.course)} kanji. "
            "Double-click or Open for full view (← → cycle, ← List to return)."
        )
        hint.setStyleSheet(f"color:{T.FOG_DIM};")
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

        body = QHBoxLayout()
        body.setSpacing(16)

        left = QVBoxLayout()
        self.browse_ch = QLabel()
        self.browse_ch.setAlignment(Qt.AlignCenter)
        self.browse_ch.setFont(QFont("Klee One", 96))
        self.browse_ch.setStyleSheet(f"color:{T.WASHI};")
        left.addWidget(self.browse_ch)
        self.browse_meaning = QLabel()
        self.browse_meaning.setAlignment(Qt.AlignCenter)
        self.browse_meaning.setWordWrap(True)
        self.browse_meaning.setStyleSheet(f"font-size:18px; color:{T.GOLD_SOFT};")
        left.addWidget(self.browse_meaning)
        self.browse_readings = QLabel()
        self.browse_readings.setAlignment(Qt.AlignCenter)
        self.browse_readings.setWordWrap(True)
        left.addWidget(self.browse_readings)
        self.browse_meta = QLabel()
        self.browse_meta.setAlignment(Qt.AlignCenter)
        self.browse_meta.setStyleSheet(f"color:{T.FOG_DIM};")
        left.addWidget(self.browse_meta)
        left.addStretch(1)
        body.addLayout(left, 2)

        right = QVBoxLayout()
        self.browse_canvas = StrokeCanvas()
        self.browse_canvas.setMinimumSize(240, 240)
        right.addWidget(self.browse_canvas, 1)
        self.replay_btn = QPushButton("▶ Replay strokes")
        self.replay_btn.clicked.connect(self.browse_canvas.animate)
        right.addWidget(self.replay_btn)
        body.addLayout(right, 2)

        lay.addLayout(body, 1)
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

    def _sorted_base(self) -> list[Kanji]:
        if self.sort_box.currentData() == "frequency":
            return list(self._by_freq)
        return list(self.svc.content.course)

    def _refilter(self) -> None:
        levels = {lv for lv, box in self.level_boxes.items() if box.isChecked()}
        core = self._core_limit()
        pool = [k for k in self._sorted_base() if (k.jlpt in levels) or (k.jlpt == 0 and 0 in levels)]
        if core is not None:
            pool = [k for k in pool if k.freq and k.freq <= core]
        q = self.search.text().strip()
        kanji = self.svc.content.search_kanji(q, pool=pool) if q else pool
        self._filtered = kanji[:800]
        self.list.clear()
        for k in self._filtered:
            item = QListWidgetItem(self._label(k))
            item.setData(Qt.UserRole, k.ch)
            status = self.svc.progress.status(P.KANJI, k.ch)
            item.setForeground(QColor(T.STATUS.get(status, T.FOG)))
            self.list.addItem(item)
        pictured = sum(1 for k in self._filtered if self.svc.images.has(P.KANJI, k.ch))
        self.count_lab.setText(f"showing {len(self._filtered)} / {len(pool)}  ·  {pictured} with images")
        if self.stack.currentIndex() == 1 and self._browse_index >= 0:
            if not self._filtered:
                self._back_to_list()
            else:
                self._browse_index = min(self._browse_index, len(self._filtered) - 1)
                self._show_browse_at(self._browse_index)

    def _label(self, k: Kanji) -> str:
        meaning = " · ".join(k.meanings[:2])
        on = " ".join(k.on[:2])
        kun = " ".join(k.kun[:2])
        mark = "◆ " if self.svc.images.has(P.KANJI, k.ch) else "   "
        freq = f"freq #{k.freq}" if k.freq else "freq —"
        return (
            f"{mark}{k.ch}   {meaning}    音:{on or '—'}  訓:{kun or '—'}   "
            f"[{k.level_name}]  {k.strokes}画  {freq}"
        )

    def _hovered(self, item: QListWidgetItem) -> None:
        ch = item.data(Qt.UserRole)
        path = self.svc.images.path(P.KANJI, ch) if ch else None
        if path is None:
            self._hover.hide()
            return
        self._hover.show_path(path, QCursor.pos())

    def hideEvent(self, event) -> None:  # noqa: N802
        self._hover.hide()
        super().hideEvent(event)

    def _picked(self, cur: QListWidgetItem | None, _prev=None) -> None:
        if cur is None:
            return
        self.svc.select_kanji(cur.data(Qt.UserRole))

    def _open_selected(self) -> None:
        if self.stack.currentIndex() == 1:
            return
        row = self.list.currentRow()
        if row < 0 and self._filtered:
            row = 0
            self.list.setCurrentRow(0)
        if row < 0 or row >= len(self._filtered):
            self.svc.toast.emit("Select a kanji first.")
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
        k = self._filtered[index]
        self.svc.select_kanji(k)
        self.pos_lab.setText(f"{index + 1} / {len(self._filtered)}")
        self.browse_ch.setText(k.ch)
        self.browse_meaning.setText(" · ".join(k.meanings[:4]) or "(no meaning)")
        self.browse_readings.setText(
            f"音 {' · '.join(k.on) or '—'}    訓 {' · '.join(k.kun) or '—'}"
        )
        freq = f"freq #{k.freq}" if k.freq else "freq —"
        self.browse_meta.setText(f"{k.level_name}  ·  {k.grade_name}  ·  {k.strokes} strokes  ·  {freq}")
        strokes = self.svc.content.strokes(k.ch)
        if strokes:
            self.browse_canvas.set_character(strokes.paths, write=False, guide=True)
            self.browse_canvas.animate()
            self.replay_btn.setEnabled(True)
        else:
            self.browse_canvas.set_character([], write=False, guide=False)
            self.replay_btn.setEnabled(False)
        self.prev_btn.setEnabled(len(self._filtered) > 1)
        self.next_btn.setEnabled(len(self._filtered) > 1)

    def _browse_speak(self) -> None:
        if 0 <= self._browse_index < len(self._filtered):
            self.svc.speak_kanji(self._filtered[self._browse_index])
