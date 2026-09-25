from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap

from formulasnip import __version__

ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
APP_ICON_PNG = ASSET_DIR / "formulasnip.png"
APP_ICON_ICO = ASSET_DIR / "formulasnip.ico"
TUTORIAL_FORMULA_PNG = ASSET_DIR / "tutorial_gaussian_integral.png"
TUTORIAL_FORMULA_LATEX = (
    r"\int_{-\infty}^{\infty} e^{-x^2}\,\mathrm{d}x = \sqrt{\pi}"
)


def application_version() -> str:
    """Return the version embedded in this application build."""
    return __version__


@lru_cache(maxsize=1)
def application_icon() -> QIcon:
    """Load the shared application icon used by windows and the taskbar."""
    icon = QIcon(str(APP_ICON_ICO))
    if icon.isNull():
        icon = QIcon(str(APP_ICON_PNG))
    return icon


def themed_brand_pixmap(accent_color: str, size: int = 30) -> QPixmap:
    """Render the in-app brand mark using the active interface accent."""

    side = max(1, size)
    accent = QColor(accent_color)
    if not accent.isValid():
        accent = QColor("#2563EB")
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    bounds = QRectF(1.0, 1.0, side - 2.0, side - 2.0)
    radius = side * 0.23
    painter.setBrush(accent)
    outline = accent.lighter(128)
    painter.setPen(QPen(outline, max(1.0, side / 30.0)))
    painter.drawRoundedRect(bounds, radius, radius)
    font = QFont("Segoe UI", max(7, round(side * 0.34)))
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, "fx")
    painter.end()
    return pixmap


@lru_cache(maxsize=1)
def tutorial_formula_image() -> QImage:
    """Load the professionally typeset Gaussian integral tutorial asset."""
    return QImage(str(TUTORIAL_FORMULA_PNG))
