from __future__ import annotations

from io import BytesIO

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage


def qimage_to_pil(image: QImage) -> Image.Image:
    """Convert an owned Qt image into an RGB Pillow image."""

    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ValueError("无法准备图片数据。")
    if not image.save(buffer, "PNG"):
        raise ValueError("无法转换公式图片。")
    data = bytes(buffer.data())
    buffer.close()
    pil_image = Image.open(BytesIO(data))
    pil_image.load()
    return pil_image.convert("RGB")
