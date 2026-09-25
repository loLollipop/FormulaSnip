from __future__ import annotations

import logging
import multiprocessing
import sys

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from formulasnip.diagnostics import initialize_logging
from formulasnip.runtime import _configure_windowed_streams, configure_runtime  # noqa: F401
from formulasnip.single_instance import SingleInstanceGuard
from formulasnip.ui.branding import application_icon, application_version
from formulasnip.ui.settings import FloatingPreferences
from formulasnip.ui.styles import apply_application_theme

AFTER_UPDATE_ARGUMENT = "--after-update"
MODEL_WARMUP_DELAY_MS = 500
PREVIEW_WARMUP_DELAY_MS = 800


def _consume_startup_arguments(argv: list[str]) -> tuple[list[str], bool]:
    """Remove FormulaSnip-only arguments before passing argv to Qt."""

    after_update = AFTER_UPDATE_ARGUMENT in argv[1:]
    qt_argv = [
        argv[0],
        *(argument for argument in argv[1:] if argument != AFTER_UPDATE_ARGUMENT),
    ]
    return qt_argv, after_update


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
    configure_runtime()
    initialize_logging()
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
    apply_application_theme(
        preferences.result_theme,
        preferences.effective_accent_theme,
    )
    app.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    return app


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    qt_argv, after_update = _consume_startup_arguments(
        list(sys.argv if argv is None else argv)
    )
    guard = SingleInstanceGuard()
    if not guard.acquire():
        return 0
    try:
        return _run_application(qt_argv, after_update=after_update)
    finally:
        guard.close()


def _run_application(argv: list[str], *, after_update: bool = False) -> int:
    from formulasnip.ui.floating import FloatingFormulaAssistant

    app = create_application(argv)
    app.setQuitOnLastWindowClosed(False)
    assistant = FloatingFormulaAssistant()
    app.aboutToQuit.connect(assistant.shutdown)
    assistant.show(after_update=after_update)
    QTimer.singleShot(MODEL_WARMUP_DELAY_MS, assistant.start_model_warmup)
    QTimer.singleShot(PREVIEW_WARMUP_DELAY_MS, assistant.start_preview_warmup)
    assistant.start_update_checks()
    try:
        return app.exec()
    finally:
        assistant.shutdown()
        logging.getLogger(__name__).info("application-stop")
