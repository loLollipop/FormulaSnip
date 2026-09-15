from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PySide6.QtGui import QIcon, QImage

ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
APP_ICON_PNG = ASSET_DIR / "formulasnip.png"
APP_ICON_ICO = ASSET_DIR / "formulasnip.ico"
TUTORIAL_FORMULA_PNG = ASSET_DIR / "tutorial_gaussian_integral.png"
TUTORIAL_FORMULA_LATEX = (
    r"\int_{-\infty}^{\infty} e^{-x^2}\,\mathrm{d}x = \sqrt{\pi}"
)


def application_version() -> str:
    """Return the installed package version with a source-tree fallback."""
    try:
        return version("formulasnip")
    except PackageNotFoundError:
        return "0.1.0"


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
