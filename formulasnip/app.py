from __future__ import annotations

import os
import sys
from typing import TextIO

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from formulasnip.ui.branding import application_icon, application_version
from formulasnip.ui.floating import FloatingFormulaAssistant
from formulasnip.ui.settings import FloatingPreferences
from formulasnip.ui.styles import apply_application_theme

_windowed_streams: list[TextIO] = []


def _configure_windowed_streams() -> None:
    """Provide writable streams when the Windows GUI bootloader omits them."""
    for stream_name in ("stdout", "stderr"):
        if getattr(sys, stream_name) is not None:
            continue
        stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        _windowed_streams.append(stream)
        setattr(sys, stream_name, stream)


def _configure_windows_identity() -> None:
    """Give Windows a stable taskbar identity for source and packaged runs."""
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll

        windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "FormulaSnip.FormulaSnip"
        )
    except (AttributeError, OSError):
        return


def create_application(argv: list[str] | None = None) -> QApplication:
    _configure_windowed_streams()
    _configure_windows_identity()
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("FormulaSnip")
    app.setApplicationDisplayName("FormulaSnip")
    app.setApplicationVersion(application_version())
    app.setOrganizationName("FormulaSnip")
    app.setWindowIcon(application_icon())
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    preferences = FloatingPreferences.load(QSettings())
    apply_application_theme(preferences.result_theme)
    app.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    return app


def main() -> int:
    app = create_application()
    app.setQuitOnLastWindowClosed(False)
    assistant = FloatingFormulaAssistant()
    assistant.show()
    assistant.start_update_checks()
    return app.exec()
