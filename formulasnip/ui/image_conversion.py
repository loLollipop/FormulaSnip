from __future__ import annotations

from io import BytesIO

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage

MAX_RECOGNITION_IMAGE_PIXELS = 4_000_000


def ensure_supported_image_size(width: int, height: int) -> None:
    if width > 0 and height > 0 and width * height <= MAX_RECOGNITION_IMAGE_PIXELS:
        return
    raise ValueError("截图尺寸过大（最多 400 万像素），请缩小截图范围后重试。")


def qimage_to_pil(image: QImage) -> Image.Image:
    """Convert an owned Qt image into an RGB Pillow image."""

    ensure_supported_image_size(image.width(), image.height())
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
