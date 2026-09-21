"""Reject an oversized edit as a whole, including paste and IME commits."""

from PySide6.QtCore import QMimeData, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QInputMethodEvent, QKeyEvent
from PySide6.QtWidgets import QPlainTextEdit

from formulasnip.core.limits import MAX_LATEX_CHARS


class LatexEditor(QPlainTextEdit):
    limit_exceeded = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._last_valid = ""
        # Also cover QTextCursor/document operations outside this widget's API.
        self.textChanged.connect(self._validate_document)

    def _accept(self, text: str, replaced: int | None = None) -> bool:
        if replaced is None:
            replaced = len(self.textCursor().selectedText())
        if len(text) > MAX_LATEX_CHARS or (
            self.document().characterCount() - 1 - replaced + len(text)
            > MAX_LATEX_CHARS
        ):
            self.limit_exceeded.emit()
            return False
        return True

    def _validate_document(self) -> None:
        if self.document().characterCount() - 1 > MAX_LATEX_CHARS:
            blocker = QSignalBlocker(self)
            super().setPlainText(self._last_valid)
            del blocker
            self.limit_exceeded.emit()
        else:
            self._last_valid = self.toPlainText()

    def setPlainText(self, text: str) -> None:  # noqa: N802
        if len(text) > MAX_LATEX_CHARS:
            self.limit_exceeded.emit()
            return
        super().setPlainText(text)
        self._last_valid = text

    def insertPlainText(self, text: str) -> None:  # noqa: N802
        if self._accept(text):
            super().insertPlainText(text)

    def appendPlainText(self, text: str) -> None:  # noqa: N802
        if self._accept(text + ("\n" if self.toPlainText() else ""), 0):
            super().appendPlainText(text)

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        if self._accept(source.text()):
            super().insertFromMimeData(source)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        editing_key = event.key() in {Qt.Key.Key_Backspace, Qt.Key.Key_Delete}
        shortcut = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if not editing_key and not shortcut and event.text() and not self._accept(event.text()):
            event.accept()
            return
        super().keyPressEvent(event)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:  # noqa: N802
        replaced = max(len(self.textCursor().selectedText()), event.replacementLength())
        if (not self._accept(event.commitString(), replaced)
                or not self._accept(event.preeditString(), replaced)):
            event.accept()
            return
        super().inputMethodEvent(event)
