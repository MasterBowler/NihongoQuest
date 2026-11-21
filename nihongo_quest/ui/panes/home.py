"""Dojo home: daily quests, due counts, streak, and quick-start actions."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from nihongo_quest.core import progress as P
from nihongo_quest.ui import theme as T
from nihongo_quest.ui.services import AppServices


class HomePane(QWidget):
    open_vocab = Signal()
    open_kanji = Signal()
    open_lexicon = Signal()

    def __init__(self, services: AppServices, parent=None) -> None:
        super().__init__(parent)
        self.svc = services
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        shell.addWidget(scroll)

        content = QWidget()
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        hero = QHBoxLayout()
        left = QVBoxLayout()
        title = QLabel("日本語クエスト")
        title.setObjectName("SectionTitle")
        sub = QLabel("Train vocabulary, kanji and reading in one fullscreen dojo.")
        sub.setObjectName("HeroEN")
        left.addWidget(title)
        left.addWidget(sub)
        hero.addLayout(left, 1)
        self.rank = QLabel()
        self.rank.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.rank.setStyleSheet(f"font-family:'Dela Gothic One'; font-size:20px; color:{T.GOLD_SOFT};")
        hero.addWidget(self.rank)
        root.addLayout(hero)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.stat_widgets = {}
        for key, label in (("streak", "日連続"), ("due", "今日の復習"), ("new", "新出"), ("xp", "経験値")):
            card = QFrame()
            card.setObjectName("Card")
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 12, 16, 12)
            value = QLabel("0")
            value.setObjectName("StatValue")
            value.setAlignment(Qt.AlignCenter)
            caption = QLabel(label)
            caption.setObjectName("StatLabel")
            caption.setAlignment(Qt.AlignCenter)
            cl.addWidget(value)
            cl.addWidget(caption)
            stats.addWidget(card, 1)
            self.stat_widgets[key] = value
        root.addLayout(stats)

        mid = QHBoxLayout()
        mid.setSpacing(12)

        goal_card = QFrame()
        goal_card.setObjectName("Card")
        goal_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        gl = QVBoxLayout(goal_card)
        gl.setContentsMargins(16, 14, 16, 14)
        gl.addWidget(self._title("今日の目標"))
        self.goal_bar = QProgressBar()
        self.goal_bar.setTextVisible(True)
        self.goal_bar.setMinimumHeight(18)
        gl.addWidget(self.goal_bar)
        self.goal_label = QLabel()
        self.goal_label.setWordWrap(True)
        self.goal_label.setStyleSheet(f"color:{T.FOG_DIM};")
        gl.addWidget(self.goal_label)
        gl.addStretch(1)
        mid.addWidget(goal_card, 1)

        quest_card = QFrame()
        quest_card.setObjectName("Card")
        quest_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        ql = QVBoxLayout(quest_card)
        ql.setContentsMargins(16, 14, 16, 14)
        ql.addWidget(self._title("日課クエスト"))
        self.quest_box = QVBoxLayout()
        self.quest_box.setSpacing(8)
        ql.addLayout(self.quest_box)
        ql.addStretch(1)
        mid.addWidget(quest_card, 1)
        root.addLayout(mid, 2)

        actions = QGridLayout()
        actions.setSpacing(10)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        self.vocab_btn = QPushButton("単語修行  ·  Vocab SRS")
        self.vocab_btn.setObjectName("Primary")
        self.vocab_btn.setMinimumHeight(58)
        self.vocab_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.vocab_btn.clicked.connect(self.open_vocab.emit)
        self.kanji_btn = QPushButton("漢字道場  ·  Kanji Dojo")
        self.kanji_btn.setObjectName("Gold")
        self.kanji_btn.setMinimumHeight(58)
        self.kanji_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.kanji_btn.clicked.connect(self.open_kanji.emit)
        lex_btn = QPushButton("辞典  ·  Browse 10,000 words")
        lex_btn.setMinimumHeight(44)
        lex_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lex_btn.clicked.connect(self.open_lexicon.emit)
        actions.addWidget(self.vocab_btn, 0, 0)
        actions.addWidget(self.kanji_btn, 0, 1)
        actions.addWidget(lex_btn, 1, 0, 1, 2)
        root.addLayout(actions)

        course = QFrame()
        course.setObjectName("Card")
        course.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        clayout = QVBoxLayout(course)
        clayout.setContentsMargins(16, 14, 16, 14)
        clayout.addWidget(self._title("コース進捗"))
        self.level_box = QHBoxLayout()
        self.level_box.setSpacing(10)
        clayout.addLayout(self.level_box)
        root.addWidget(course)

        root.addStretch(1)

        self.svc.progress_changed.connect(self.refresh)
        self.refresh()

    def _title(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("PanelTitle")
        return lab

    def refresh(self) -> None:
        now = self.svc.now()
        prog = self.svc.progress
        claimed = prog.claim_quests(now)
        if claimed:
            self.svc.toast.emit("Quest complete: " + ", ".join(q.en for q in claimed))
            self.svc.notify_progress()

        info = prog.level_info()
        self.rank.setText(f"Lv.{info['level']}  {info['rank_jp']}\n{info['rank_en']}")

        v = prog.counts(P.VOCAB, now)
        k = prog.counts(P.KANJI, now)
        self.stat_widgets["streak"].setText(str(prog.streak(now)))
        self.stat_widgets["due"].setText(str(v["review"] + k["review"]))
        self.stat_widgets["new"].setText(str(v["new"] + k["new"]))
        self.stat_widgets["xp"].setText(str(info["xp"]))

        done, goal = prog.goal_progress(now)
        self.goal_bar.setMaximum(max(goal, 1))
        self.goal_bar.setValue(min(done, goal))
        self.goal_bar.setFormat(f"{done} / {goal}")
        self.goal_label.setText("Daruma fills as you clear reviews and new lessons.")

        self.vocab_btn.setText(
            f"単語修行  ·  {v['review']} due · {v['new']} new · {v['learning']} learning"
        )
        self.kanji_btn.setText(
            f"漢字道場  ·  {k['review']} due · {k['new']} new · {k['learning']} learning"
        )

        while self.quest_box.count():
            item = self.quest_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for q, value, rewarded in prog.quests(now):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            mark = "✓" if rewarded or value >= q.target else "○"
            lab = QLabel(f"{mark}  {q.jp}\n     {q.en}")
            lab.setWordWrap(True)
            lab.setStyleSheet(f"color:{T.GOLD_SOFT if value >= q.target else T.FOG};")
            bar = QProgressBar()
            bar.setMaximum(q.target)
            bar.setValue(value)
            bar.setMinimumWidth(90)
            bar.setMaximumWidth(140)
            bar.setFormat(f"{value}/{q.target}")
            row.addWidget(lab, 1)
            row.addWidget(bar, 0)
            wrap = QWidget()
            wrap.setLayout(row)
            self.quest_box.addWidget(wrap)

        while self.level_box.count():
            item = self.level_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                pass
        counts = prog.status_counts(P.VOCAB)
        for level in (5, 4, 3, 2, 1, 0):
            bucket = counts.get(level, {})
            total = max(bucket.get("total", 1), 1)
            learned = bucket.get("mature", 0) + bucket.get("young", 0) + bucket.get("known", 0)
            name = {5: "N5", 4: "N4", 3: "N3", 2: "N2", 1: "N1", 0: "＋"}[level]
            col = QVBoxLayout()
            col.setSpacing(4)
            lab = QLabel(name)
            lab.setAlignment(Qt.AlignCenter)
            lab.setStyleSheet(f"color:{T.LEVEL_COLOR[level]}; font-family:'Dela Gothic One';")
            bar = QProgressBar()
            bar.setMaximum(total)
            bar.setValue(learned)
            bar.setFormat(f"{learned}/{total}")
            bar.setMinimumHeight(16)
            col.addWidget(lab)
            col.addWidget(bar)
            wrap = QWidget()
            wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            wrap.setLayout(col)
            self.level_box.addWidget(wrap, 1)
