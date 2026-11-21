"""Interactive gojūon chart + quick drill for hiragana/katakana."""
from __future__ import annotations

import random

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from nihongo_quest.core import kana as K
from nihongo_quest.ui import theme as T
from nihongo_quest.ui.services import AppServices


class KanaPane(QWidget):
    def __init__(self, services: AppServices, parent=None) -> None:
        super().__init__(parent)
        self.svc = services
        self._katakana = False
        self._target = ""
        self._options: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("五十音 · Kana Dojo")
        title.setObjectName("SectionTitle")
        head.addWidget(title, 1)
        self.toggle = QPushButton("Show Katakana")
        self.toggle.clicked.connect(self._flip_script)
        head.addWidget(self.toggle)
        root.addLayout(head)

        # drill card
        drill = QWidget()
        dl = QVBoxLayout(drill)
        self.prompt = QLabel("あ")
        self.prompt.setAlignment(Qt.AlignCenter)
        self.prompt.setStyleSheet(f"font-family:'Klee One'; font-size:96px; color:{T.WASHI};")
        dl.addWidget(self.prompt)
        self.hint = QLabel("Pick the romaji")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setStyleSheet(f"color:{T.FOG_DIM};")
        dl.addWidget(self.hint)
        self.opt_row = QHBoxLayout()
        self.opt_btns: list[QPushButton] = []
        for _ in range(4):
            btn = QPushButton("?")
            btn.setMinimumHeight(48)
            btn.clicked.connect(lambda _=False, b=btn: self._answer(b.text()))
            self.opt_btns.append(btn)
            self.opt_row.addWidget(btn)
        dl.addLayout(self.opt_row)
        next_btn = QPushButton("Next kana")
        next_btn.setObjectName("Primary")
        next_btn.clicked.connect(self._new_drill)
        dl.addWidget(next_btn)
        root.addWidget(drill)

        # chart
        chart_title = QLabel("Chart — click a kana to hear it")
        chart_title.setObjectName("PanelTitle")
        root.addWidget(chart_title)
        self.chart = QGridLayout()
        self.chart.setSpacing(4)
        root.addLayout(self.chart)
        root.addStretch(1)
        self._rebuild_chart()
        self._new_drill()

    def _flip_script(self) -> None:
        self._katakana = not self._katakana
        self.toggle.setText("Show Hiragana" if self._katakana else "Show Katakana")
        self._rebuild_chart()
        self._new_drill()

    def _rebuild_chart(self) -> None:
        while self.chart.count():
            item = self.chart.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        tables = [("gojuon", K.GOJUON), ("dakuon", K.DAKUON), ("yoon", K.YOON)]
        row = 0
        for _, table in tables:
            for col_name, cells in table:
                lab = QLabel(col_name)
                lab.setStyleSheet(f"color:{T.GOLD}; font-size:11px;")
                self.chart.addWidget(lab, row, 0)
                for c, kana in enumerate(cells, 1):
                    if not kana or kana == "　":
                        continue
                    ch = K.hira_to_kata(kana) if self._katakana else kana
                    btn = QPushButton(ch)
                    btn.setFixedSize(44, 36)
                    btn.setStyleSheet("padding:0; font-family:'Klee One'; font-size:16px;")
                    btn.clicked.connect(lambda _=False, x=ch: self.svc.speak_text(x))
                    self.chart.addWidget(btn, row, c)
                row += 1

    def _pool(self) -> list[str]:
        return K.chart_kana(katakana=self._katakana)

    def _new_drill(self) -> None:
        pool = [k for k in self._pool() if k and k != "　"]
        self._target = random.choice(pool)
        self.prompt.setText(self._target)
        correct = K.to_romaji(K.kata_to_hira(self._target))
        opts = {correct}
        while len(opts) < 4:
            opts.add(K.to_romaji(K.kata_to_hira(random.choice(pool))))
        self._options = list(opts)
        random.shuffle(self._options)
        for btn, text in zip(self.opt_btns, self._options):
            btn.setText(text)
            btn.setEnabled(True)
            btn.setStyleSheet("")
        self.hint.setText("Pick the romaji")
        if self.svc.progress.setting("autoplay"):
            self.svc.speak_text(self._target)

    def _answer(self, choice: str) -> None:
        correct = K.to_romaji(K.kata_to_hira(self._target))
        for btn in self.opt_btns:
            btn.setEnabled(False)
            if btn.text() == correct:
                btn.setStyleSheet(f"background:{T.MOSS}; color:white;")
            elif btn.text() == choice and choice != correct:
                btn.setStyleSheet(f"background:{T.SEAL}; color:white;")
        self.hint.setText("正解！" if choice == correct else f"Answer: {correct}")
