from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtSvgWidgets import QSvgWidget


class FormulaSvgWidget(QSvgWidget):
    """Compact, aspect-preserving formula surface used by the floating result panel."""

    def __init__(self) -> None:
        super().__init__()
        self.renderer().setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.setMinimumSize(80, 44)
        self.setMaximumHeight(78)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(360, 72)

    def set_formula_svg(self, svg: bytes) -> None:
        if not self.renderer().load(QByteArray(svg)):
            raise ValueError("电子公式 SVG 加载失败")
        self.update()
