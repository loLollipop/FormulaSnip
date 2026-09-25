from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QScreen,
)
from PySide6.QtWidgets import QWidget

OVERLAY_COLOR = "#FFFFFF"
OVERLAY_ALPHA = 96
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
        self._selection_error = ""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setCursor(Qt.CursorShape.ArrowCursor)
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
        overlay_color = QColor(OVERLAY_COLOR)
        overlay_color.setAlpha(OVERLAY_ALPHA)
        painter.fillRect(self.rect(), overlay_color)

        selection = self._selection_rect()
        if selection.isValid():
            source = self._map_to_source(selection)
            painter.drawPixmap(selection, self._screenshot, source)
            accent = QColor("#4f46e5")
            painter.setPen(QPen(accent, 2))
            painter.drawRect(selection)
            self._draw_corner_marks(painter, selection, accent)
            label_text = self._selection_label_text(source)
            label_rect = self._selection_label_rect(selection, label_text)
            painter.fillRect(label_rect, QColor(255, 255, 255, 235))
            painter.setPen(QColor("#b91c1c" if self._selection_error else "#334155"))
            painter.drawText(
                label_rect.adjusted(8, 0, -8, 0),
                Qt.AlignmentFlag.AlignVCenter,
                label_text,
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._selection_error = ""
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
        source = self._map_to_source(selection)
        if source.width() < MIN_SELECTION_SIZE or source.height() < MIN_SELECTION_SIZE:
            self._selection_error = "选区过小，请拖大后重试"
            self.update()
            return
        crop = self._screenshot.copy(source)
        self._finished = True
        self.captured.emit(crop)
        self.close()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
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

    def _cancel(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.cancelled.emit()
        self.close()

    def _selection_label_rect(self, selection: QRect, text: str) -> QRect:
        width = min(max(190, self.fontMetrics().horizontalAdvance(text) + 18), self.width() - 16)
        height = 28
        x = min(max(8, selection.left()), max(8, self.width() - width - 8))
        preferred_y = selection.top() - height - 6
        y = preferred_y if preferred_y >= 8 else selection.bottom() + 7
        y = min(max(8, y), max(8, self.height() - height - 8))
        return QRect(x, y, width, height)

    def _selection_label_text(self, source: QRect) -> str:
        return self._selection_error or f"{source.width()} × {source.height()}"

    @staticmethod
    def _draw_corner_marks(painter: QPainter, selection: QRect, color: QColor) -> None:
        painter.save()
        pen = QPen(color, 4)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(pen)
        length = min(14, max(6, min(selection.width(), selection.height()) // 3))
        left, right = selection.left(), selection.right()
        top, bottom = selection.top(), selection.bottom()
        for start, horizontal_end, vertical_end in (
            (QPoint(left, top), QPoint(left + length, top), QPoint(left, top + length)),
            (QPoint(right, top), QPoint(right - length, top), QPoint(right, top + length)),
            (QPoint(left, bottom), QPoint(left + length, bottom), QPoint(left, bottom - length)),
            (QPoint(right, bottom), QPoint(right - length, bottom), QPoint(right, bottom - length)),
        ):
            painter.drawLine(start, horizontal_end)
            painter.drawLine(start, vertical_end)
        painter.restore()
