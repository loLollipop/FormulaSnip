from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QScreen,
)
from PySide6.QtWidgets import QWidget

OVERLAY_ALPHA = 72
MIN_SELECTION_SIZE = 12


class SnipOverlay(QWidget):
    captured = Signal(QPixmap)
    cancelled = Signal()

    def __init__(self, screen: QScreen, screenshot: QPixmap) -> None:
        super().__init__()
        self._screen = screen
        self._screenshot = screenshot
        self._start: QPoint | None = None
        self._end: QPoint | None = None
        self._finished = False
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setCursor(_crosshair_cursor())
        self.setGeometry(screen.geometry())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def show_overlay(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.rect(), self._screenshot)
        painter.fillRect(self.rect(), QColor(5, 10, 20, OVERLAY_ALPHA))

        selection = self._selection_rect()
        if selection.isValid() and selection.width() > 1 and selection.height() > 1:
            source = self._map_to_source(selection)
            painter.drawPixmap(selection, self._screenshot, source)
            painter.setPen(QPen(QColor("#60a5fa"), 2))
            painter.drawRect(selection)
            label_rect = QRect(selection.left(), max(8, selection.top() - 32), 260, 26)
            painter.fillRect(label_rect, QColor(15, 23, 42, 220))
            painter.setPen(QColor("#e5edf8"))
            painter.drawText(
                label_rect.adjusted(8, 0, -8, 0),
                Qt.AlignmentFlag.AlignVCenter,
                f"{selection.width()} × {selection.height()}  松开鼠标完成",
            )
        elif self._start is None:
            help_rect = QRect(0, 0, 420, 52)
            help_rect.moveCenter(self.rect().center())
            painter.fillRect(help_rect, QColor(15, 23, 42, 225))
            painter.setPen(QColor("#f8fafc"))
            painter.drawText(
                help_rect,
                Qt.AlignmentFlag.AlignCenter,
                "拖动框选公式 · Esc 取消",
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._end = self._start
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._start is not None:
            self._end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._end = event.position().toPoint()
        selection = self._selection_rect().intersected(self.rect())
        if selection.width() < MIN_SELECTION_SIZE or selection.height() < MIN_SELECTION_SIZE:
            self._start = None
            self._end = None
            self.update()
            return
        crop = self._screenshot.copy(self._map_to_source(selection))
        self._finished = True
        self.captured.emit(crop)
        self.close()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._finished = True
            self.cancelled.emit()
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: object) -> None:  # noqa: N802
        if not self._finished:
            self._finished = True
            self.cancelled.emit()
        super().closeEvent(event)  # type: ignore[arg-type]

    def _selection_rect(self) -> QRect:
        if self._start is None or self._end is None:
            return QRect()
        return QRect(self._start, self._end).normalized()

    def _map_to_source(self, rect: QRect) -> QRect:
        scale_x = self._screenshot.width() / max(1, self.width())
        scale_y = self._screenshot.height() / max(1, self.height())
        return QRect(
            round(rect.x() * scale_x),
            round(rect.y() * scale_y),
            max(1, round(rect.width() * scale_x)),
            max(1, round(rect.height() * scale_y)),
        )


def _crosshair_cursor() -> QCursor:
    pixmap = QPixmap(31, 31)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(QPen(QColor("#101827"), 5))
    painter.drawLine(15, 1, 15, 29)
    painter.drawLine(1, 15, 29, 15)
    painter.setPen(QPen(QColor("#f8fafc"), 2))
    painter.drawLine(15, 2, 15, 28)
    painter.drawLine(2, 15, 28, 15)
    painter.setPen(QPen(QColor("#2563eb"), 1))
    painter.drawPoint(15, 15)
    painter.end()
    return QCursor(pixmap, 15, 15)
