from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QIcon, QImage

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


@lru_cache(maxsize=1)
def tutorial_formula_image() -> QImage:
    """Load the professionally typeset Gaussian integral tutorial asset."""
    return QImage(str(TUTORIAL_FORMULA_PNG))
