from __future__ import annotations

import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from formulasnip.ui.floating import FloatingFormulaAssistant
from formulasnip.ui.settings import FloatingPreferences
from formulasnip.ui.styles import apply_application_theme


def create_application(argv: list[str] | None = None) -> QApplication:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("FormulaSnip")
    app.setOrganizationName("FormulaSnip")
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
    return app.exec()
