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


class ModelWarmupSignals(QObject):
    started = Signal(str)
    succeeded = Signal(str)
    failed = Signal(str, str)
    finished = Signal()


class ModelWarmupWorker(QRunnable):
    """Warm installed recognition engines sequentially in one background task."""

    def __init__(self, manager: BackendManager, backend_keys: tuple[str, ...]) -> None:
        super().__init__()
        self.manager = manager
        self.backend_keys = backend_keys
        self.signals = ModelWarmupSignals()

    @Slot()
    def run(self) -> None:
        for key in self.backend_keys:
            self.signals.started.emit(key)
            try:
                self.manager.warmup(key)
            except Exception as exc:
                message = str(exc).strip() or type(exc).__name__
                self.signals.failed.emit(key, message)
                continue
            self.signals.succeeded.emit(key)
        self.signals.finished.emit()
