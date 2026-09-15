from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image

from formulasnip.domain import RecognitionResult


class RecognitionBackend(ABC):
    key: str
    display_name: str
    install_hint: str

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Return whether the local backend package can be imported."""

    @abstractmethod
    def recognize(self, image: Image.Image) -> RecognitionResult:
        """Recognize one already-cropped formula image."""
