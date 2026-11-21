"""Progress statistics: retention, forecast, leeches, history."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from nihongo_quest.core import progress as P
from nihongo_quest.ui import theme as T
from nihongo_quest.ui.services import AppServices


class BarChart(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._values: list[int] = []
        self._labels: list[str] = []
        self.setMinimumHeight(140)

    def set_data(self, values: list[int], labels: list[str] | None = None) -> None:
        self._values = values
        self._labels = labels or [""] * len(values)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._values:
            p.setPen(QColor(T.FOG_DIM))
            p.drawText(self.rect(), Qt.AlignCenter, "No data yet")
            p.end()
            return
        top, bottom, left = 10, self.height() - 22, 8
        usable_h = bottom - top
        usable_w = self.width() - 16
        peak = max(max(self._values), 1)
        bar_w = usable_w / len(self._values)
        for i, v in enumerate(self._values):
            h = usable_h * v / peak
            x = left + i * bar_w
            p.setBrush(QColor(T.SEAL if i == 0 else T.GOLD))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(int(x + 2), int(bottom - h), int(bar_w - 4), int(h), 4, 4)
            if self._labels[i]:
                p.setPen(QColor(T.FOG_DIM))
                p.drawText(int(x), bottom + 2, int(bar_w), 18, Qt.AlignHCenter, self._labels[i])
        p.end()


class StatsPane(QWidget):
    def __init__(self, services: AppServices, parent=None) -> None:
        super().__init__(parent)
        self.svc = services

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("統計 · Stats")
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        row = QHBoxLayout()
        hist_card = QFrame()
        hist_card.setObjectName("Card")
        hl = QVBoxLayout(hist_card)
        hl.addWidget(self._h("Last 14 days — reviews"))
        self.hist = BarChart()
        hl.addWidget(self.hist)
        row.addWidget(hist_card, 1)

        forecast_card = QFrame()
        forecast_card.setObjectName("Card")
        fl = QVBoxLayout(forecast_card)
        fl.addWidget(self._h("Next 14 days — due forecast"))
        self.forecast = BarChart()
        fl.addWidget(self.forecast)
        row.addWidget(forecast_card, 1)
        root.addLayout(row)

        self.leech_lab = QLabel()
        self.leech_lab.setWordWrap(True)
        root.addWidget(self._h("Leeches (forgotten often)"))
        root.addWidget(self.leech_lab)
        root.addStretch(1)

        self.svc.progress_changed.connect(self.refresh)
        self.refresh()

    def _h(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("PanelTitle")
        return lab

    def refresh(self) -> None:
        now = self.svc.now()
        prog = self.svc.progress
        totals = prog.totals()
        ok, n = prog.retention(30, now)
        info = prog.level_info()
        v_learned = prog.learned_count(P.VOCAB)
        k_learned = prog.learned_count(P.KANJI)
        self.summary.setText(
            f"Level {info['level']} {info['rank_jp']} ({info['rank_en']}) · {info['xp']} XP\n"
            f"Words learned {v_learned} / {len(self.svc.content.words)} · "
            f"Kanji learned {k_learned} / {len(self.svc.content.course)}\n"
            f"Lifetime reviews {totals['reviews']} across {totals['days']} study days · "
            f"{totals['seconds'] // 60} minutes total\n"
            f"30-day retention on graduated cards: "
            + (f"{ok}/{n} ({ok / n:.0%})" if n else "not enough data yet")
        )

        history = prog.history(14, now)
        self.hist.set_data(
            [d["reviews"] + d["new_vocab"] + d["new_kanji"] for d in history],
            [str(i - 13) if i else "今日" for i in range(14)],
        )
        forecast = prog.forecast(14, now)
        self.forecast.set_data(forecast, [str(i) if i else "今日" for i in range(14)])

        leeches = prog.leeches(P.VOCAB, 8) + prog.leeches(P.KANJI, 4)
        if not leeches:
            self.leech_lab.setText("None yet — keep reviewing.")
        else:
            lines = []
            for c in leeches:
                if c.kind == P.VOCAB:
                    w = self.svc.content.word_by_key(c.item)
                    label = f"{w.word}【{w.kana}】" if w else c.item
                else:
                    label = c.item
                lines.append(f"· {label}  —  {c.s.lapses} lapses")
            self.leech_lab.setText("\n".join(lines))
