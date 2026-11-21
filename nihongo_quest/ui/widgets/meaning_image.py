"""Meaning-illustration preview with Add / Replace / Remove for a word or kanji."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from nihongo_quest.ui import theme as T


class MeaningImageCard(QWidget):
    """Shows an attached meaning picture and lets the learner manage the file."""

    changed = Signal()

    def __init__(self, store, kind: str, item: str, parent=None, *, editable: bool = True,
                 max_height: int = 220) -> None:
        super().__init__(parent)
        self.store = store
        self.kind = kind
        self.item = item
        self.editable = editable
        self.max_height = max_height

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(120)
        self.preview.setMaximumHeight(max_height)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.preview.setStyleSheet(
            f"background:#0E1524; border:1px solid #243049; border-radius:12px; color:{T.FOG_DIM};"
        )
        root.addWidget(self.preview)

        if editable:
            row = QHBoxLayout()
            self.add_btn = QPushButton("Add image…")
            self.add_btn.clicked.connect(self._pick)
            self.clear_btn = QPushButton("Remove")
            self.clear_btn.clicked.connect(self._clear)
            row.addWidget(self.add_btn)
            row.addWidget(self.clear_btn)
            row.addStretch(1)
            root.addLayout(row)

        self.refresh()

    def refresh(self) -> None:
        path = self.store.path(self.kind, self.item)
        if path is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("No meaning image yet.\nAdd a picture of what this means.")
            if self.editable:
                self.add_btn.setText("Add image…")
                self.clear_btn.setEnabled(False)
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            self.preview.setText(f"Could not load\n{path.name}")
            return
        scaled = pix.scaled(
            self.preview.width() or 280,
            self.max_height - 8,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview.setPixmap(scaled)
        self.preview.setText("")
        if self.editable:
            self.add_btn.setText("Replace image…")
            self.clear_btn.setEnabled(True)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.store.path(self.kind, self.item):
            self.refresh()

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a meaning illustration",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp)",
        )
        if not path:
            return
        self.store.set_image(self.kind, self.item, Path(path), source_tag="manual")
        self.refresh()
        self.changed.emit()

    def _clear(self) -> None:
        self.store.clear(self.kind, self.item)
        self.refresh()
        self.changed.emit()


class ImageHoverPopup(QLabel):
    """Floating preview shown while hovering a lexicon / atlas row that has an image."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(
            f"background:{T.PANEL}; border:1px solid {T.GOLD}; border-radius:10px; padding:6px;"
        )
        self.setFixedSize(260, 200)
        self.setAlignment(Qt.AlignCenter)
        self.hide()

    def show_path(self, path: Path, global_pos) -> None:
        pix = QPixmap(str(path))
        if pix.isNull():
            self.hide()
            return
        self.setPixmap(pix.scaled(248, 188, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.move(global_pos.x() + 18, global_pos.y() + 18)
        self.show()
        self.raise_()
