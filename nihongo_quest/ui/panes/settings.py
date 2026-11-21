"""Learner preferences."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from nihongo_quest.core import progress as P
from nihongo_quest.ui.services import AppServices


class SettingsPane(QWidget):
    def __init__(self, services: AppServices, parent=None) -> None:
        super().__init__(parent)
        self.svc = services
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("設定 · Settings")
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)

        self.new_vocab = QSpinBox()
        self.new_vocab.setRange(0, 100)
        form.addRow("New vocab / day", self.new_vocab)

        self.new_kanji = QSpinBox()
        self.new_kanji.setRange(0, 50)
        form.addRow("New kanji / day", self.new_kanji)

        self.review_cap = QSpinBox()
        self.review_cap.setRange(10, 500)
        form.addRow("Review cap / session", self.review_cap)

        self.daily_goal = QSpinBox()
        self.daily_goal.setRange(5, 500)
        form.addRow("Daily goal (cards)", self.daily_goal)

        self.vocab_mode = QComboBox()
        self.vocab_mode.addItem("Recognition", "recognition")
        self.vocab_mode.addItem("Listening", "listening")
        self.vocab_mode.addItem("Recall (EN→JP)", "recall")
        self.vocab_mode.addItem("Mixed", "mixed")
        form.addRow("Vocab quiz mode", self.vocab_mode)

        self.kanji_mode = QComboBox()
        self.kanji_mode.addItem("Recognition", "recognition")
        self.kanji_mode.addItem("Writing", "writing")
        self.kanji_mode.addItem("Mixed", "mixed")
        form.addRow("Kanji quiz mode", self.kanji_mode)

        self.new_phrase = QSpinBox()
        self.new_phrase.setRange(0, 50)
        form.addRow("New phrases / day", self.new_phrase)

        self.phrase_mode = QComboBox()
        self.phrase_mode.addItem("Recognition (JP→EN)", "recognition")
        self.phrase_mode.addItem("Recall (EN→JP)", "recall")
        self.phrase_mode.addItem("Mixed", "mixed")
        form.addRow("Phrase quiz mode", self.phrase_mode)

        self.auto_translate_ocr = QCheckBox("Auto-translate OCR results (online)")
        form.addRow("", self.auto_translate_ocr)

        self.ffmpeg_path = QLineEdit()
        self.ffmpeg_path.setPlaceholderText(r"e.g. C:\ffmpeg\bin or C:\ffmpeg\bin\ffmpeg.exe")
        form.addRow("ffmpeg path (Immersion)", self.ffmpeg_path)

        self.lmstudio_enabled = QCheckBox("Enable LM Studio for Immersion translations")
        form.addRow("", self.lmstudio_enabled)

        self.lmstudio_url = QLineEdit()
        self.lmstudio_url.setPlaceholderText("http://127.0.0.1:1234/v1")
        form.addRow("LM Studio URL", self.lmstudio_url)

        self.lmstudio_model = QLineEdit()
        self.lmstudio_model.setPlaceholderText("Model id (optional — uses loaded model)")
        form.addRow("LM Studio model", self.lmstudio_model)

        self.order = QComboBox()
        self.order.addItem("JLPT course order", "course")
        self.order.addItem("Frequency order", "frequency")
        form.addRow("New word order", self.order)

        self.voice = QComboBox()
        self.voice.addItem("Nanami (neural)", "nanami")
        self.voice.addItem("Keita (neural)", "keita")
        self.voice.addItem("Offline (Windows Japanese voice)", "offline")
        form.addRow("Voice", self.voice)

        self.rate = QSpinBox()
        self.rate.setRange(-50, 50)
        self.rate.setSuffix("%")
        form.addRow("Speech rate", self.rate)

        self.ui_scale = QDoubleSpinBox()
        self.ui_scale.setRange(0.85, 1.75)
        self.ui_scale.setSingleStep(0.05)
        self.ui_scale.setDecimals(2)
        self.ui_scale.setSuffix("×")
        form.addRow("UI zoom (Ctrl + / −)", self.ui_scale)

        self.loupe_factor = QDoubleSpinBox()
        self.loupe_factor.setRange(1.5, 4.0)
        self.loupe_factor.setSingleStep(0.25)
        self.loupe_factor.setDecimals(2)
        self.loupe_factor.setSuffix("×")
        form.addRow("Magnifier strength (F2)", self.loupe_factor)

        self.typing = QCheckBox("Require typed reading before reveal")
        self.autoplay = QCheckBox("Auto-play audio")
        self.romaji = QCheckBox("Show romaji")
        self.furigana = QCheckBox("Show furigana")
        self.petals = QCheckBox("Sakura petals")
        self.fullscreen = QCheckBox("Start fullscreen")
        self.kanji_from_vocab = QCheckBox("Prioritize kanji from studied words")

        for w in (self.typing, self.autoplay, self.romaji, self.furigana, self.petals,
                  self.fullscreen, self.kanji_from_vocab):
            form.addRow("", w)

        # JLPT level toggles
        level_row = QHBoxLayout()
        self.level_boxes = {}
        for level, name in ((5, "N5"), (4, "N4"), (3, "N3"), (2, "N2"), (1, "N1"), (0, "＋")):
            box = QCheckBox(name)
            self.level_boxes[level] = box
            level_row.addWidget(box)
        level_row.addStretch(1)
        form.addRow("New-word levels", level_row)

        root.addLayout(form)

        actions = QHBoxLayout()
        save = QPushButton("Save settings")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        actions.addWidget(save)
        mark_n5 = QPushButton("Mark all N5 as known")
        mark_n5.clicked.connect(lambda: self._mark_known(5))
        actions.addWidget(mark_n5)
        reset = QPushButton("Reset all progress…")
        reset.clicked.connect(self._reset)
        actions.addWidget(reset)
        actions.addStretch(1)
        root.addLayout(actions)
        root.addStretch(1)

        self._load()

    def _load(self) -> None:
        self._busy = True
        p = self.svc.progress
        self.new_vocab.setValue(int(p.setting("new_vocab_per_day")))
        self.new_kanji.setValue(int(p.setting("new_kanji_per_day")))
        self.new_phrase.setValue(int(p.setting("new_phrase_per_day")))
        self.review_cap.setValue(int(p.setting("review_cap")))
        self.daily_goal.setValue(int(p.setting("daily_goal")))
        self._set_combo(self.vocab_mode, p.setting("vocab_mode"))
        self._set_combo(self.kanji_mode, p.setting("kanji_mode"))
        self._set_combo(self.phrase_mode, p.setting("phrase_mode"))
        self.auto_translate_ocr.setChecked(bool(p.setting("auto_translate_ocr")))
        self.ffmpeg_path.setText(str(p.setting("ffmpeg_path") or ""))
        self.lmstudio_enabled.setChecked(bool(p.setting("lmstudio_enabled")))
        self.lmstudio_url.setText(str(p.setting("lmstudio_url") or "http://127.0.0.1:1234/v1"))
        self.lmstudio_model.setText(str(p.setting("lmstudio_model") or ""))
        self._set_combo(self.order, p.setting("order"))
        self._set_combo(self.voice, p.setting("voice"))
        self.rate.setValue(int(p.setting("speech_rate")))
        self.ui_scale.setValue(float(p.setting("ui_scale")))
        self.loupe_factor.setValue(float(p.setting("loupe_factor")))
        self.typing.setChecked(bool(p.setting("typing")))
        self.autoplay.setChecked(bool(p.setting("autoplay")))
        self.romaji.setChecked(bool(p.setting("show_romaji")))
        self.furigana.setChecked(bool(p.setting("furigana")))
        self.petals.setChecked(bool(p.setting("petals")))
        self.fullscreen.setChecked(bool(p.setting("fullscreen")))
        self.kanji_from_vocab.setChecked(bool(p.setting("kanji_from_vocab")))
        levels = set(p.setting("levels"))
        for lv, box in self.level_boxes.items():
            box.setChecked(lv in levels)
        self._busy = False

    @staticmethod
    def _set_combo(combo: QComboBox, value) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _save(self) -> None:
        p = self.svc.progress
        p.set_setting("new_vocab_per_day", self.new_vocab.value())
        p.set_setting("new_kanji_per_day", self.new_kanji.value())
        p.set_setting("new_phrase_per_day", self.new_phrase.value())
        p.set_setting("review_cap", self.review_cap.value())
        p.set_setting("daily_goal", self.daily_goal.value())
        p.set_setting("vocab_mode", self.vocab_mode.currentData())
        p.set_setting("kanji_mode", self.kanji_mode.currentData())
        p.set_setting("phrase_mode", self.phrase_mode.currentData())
        p.set_setting("auto_translate_ocr", self.auto_translate_ocr.isChecked())
        p.set_setting("ffmpeg_path", self.ffmpeg_path.text().strip())
        p.set_setting("lmstudio_enabled", self.lmstudio_enabled.isChecked())
        p.set_setting("lmstudio_url", self.lmstudio_url.text().strip() or "http://127.0.0.1:1234/v1")
        p.set_setting("lmstudio_model", self.lmstudio_model.text().strip())
        p.set_setting("order", self.order.currentData())
        p.set_setting("voice", self.voice.currentData())
        p.set_setting("speech_rate", self.rate.value())
        p.set_setting("ui_scale", round(self.ui_scale.value(), 2))
        p.set_setting("loupe_factor", round(self.loupe_factor.value(), 2))
        p.set_setting("typing", self.typing.isChecked())
        p.set_setting("autoplay", self.autoplay.isChecked())
        p.set_setting("show_romaji", self.romaji.isChecked())
        p.set_setting("furigana", self.furigana.isChecked())
        p.set_setting("petals", self.petals.isChecked())
        p.set_setting("fullscreen", self.fullscreen.isChecked())
        p.set_setting("kanji_from_vocab", self.kanji_from_vocab.isChecked())
        p.set_setting("levels", [lv for lv, box in self.level_boxes.items() if box.isChecked()])
        self.svc.apply_voice_settings()
        self.svc.settings_changed.emit()
        self.svc.notify_progress()
        self.svc.toast.emit("Settings saved.")

    def _mark_known(self, level: int) -> None:
        n = self.svc.progress.mark_level_known(level)
        self.svc.notify_progress()
        self.svc.toast.emit(f"Marked {n} N{level} words as known.")

    def _reset(self) -> None:
        if QMessageBox.question(
            self, "Reset progress",
            "This erases all SRS cards, XP and review history.\nA backup is saved first. Continue?",
        ) != QMessageBox.Yes:
            return
        from nihongo_quest.paths import BACKUPS
        self.svc.progress.reset_all(BACKUPS)
        self.svc.notify_progress()
        self.svc.toast.emit("Progress reset.")
