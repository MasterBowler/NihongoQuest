"""Application entry point."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from nihongo_quest import __version__
from nihongo_quest.paths import CONTENT_DB
from nihongo_quest.ui.fonts import load_fonts
from nihongo_quest.ui.main_window import MainWindow
from nihongo_quest.ui.services import AppServices
from nihongo_quest.ui.theme import stylesheet


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv)
    app.setApplicationName("Nihongo Quest")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("NihongoQuest")
    load_fonts()

    if not CONTENT_DB.exists():
        QMessageBox.critical(
            None,
            "Content missing",
            f"Could not find {CONTENT_DB}.\n\n"
            "Run:\n  python tools/fetch_sources.py\n  python tools/build_data.py",
        )
        return 1

    try:
        services = AppServices()
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(None, "Failed to start", str(exc))
        return 1

    app.setStyleSheet(stylesheet(float(services.progress.setting("ui_scale"))))
    window = MainWindow(services)
    if services.progress.setting("fullscreen"):
        window.showFullScreen()
    else:
        window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
