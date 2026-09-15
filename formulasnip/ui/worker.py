from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from formulasnip.domain import RecognitionResult
from formulasnip.recognition import BackendManager


class RecognitionSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class RecognitionWorker(QRunnable):
    def __init__(self, manager: BackendManager, image: Image.Image, backend_key: str) -> None:
        super().__init__()
        self.manager = manager
        self.image = image.copy()
        self.backend_key = backend_key
        self.signals = RecognitionSignals()

    @Slot()
    def run(self) -> None:
        try:
            result: RecognitionResult = self.manager.recognize(self.image, self.backend_key)
        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__
            self.signals.failed.emit(message)
            return
        self.signals.finished.emit(result)
