from __future__ import annotations

from PySide6.QtCore import (
    QMimeData,
    QObject,
    QPoint,
    QRect,
    QSettings,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QCursor,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from formulasnip.core.latex import latex_to_mathml
from formulasnip.domain import RecognitionResult
from formulasnip.exceptions import FormulaSnipError
from formulasnip.recognition import BackendManager
from formulasnip.ui.image_conversion import qimage_to_pil
from formulasnip.ui.preview import render_formula_svg
from formulasnip.ui.settings import (
    DEFAULT_RING_COLOR,
    RING_PRESETS,
    FloatingPreferences,
    SettingsPanel,
    normalize_hex_color,
    read_logo_image,
)
from formulasnip.ui.snip_overlay import SnipOverlay
from formulasnip.ui.styles import apply_application_theme
from formulasnip.ui.widgets import FormulaSvgWidget
from formulasnip.ui.worker import RecognitionWorker

ORB_PALETTES = {
    "blue": (RING_PRESETS["blue"], "#1A2434"),
    "green": (RING_PRESETS["green"], "#1A2434"),
    "orange": (RING_PRESETS["orange"], "#1A2434"),
}


class FloatingOrb(QWidget):
    capture_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, color: str = "blue", logo_path: str = "") -> None:
        super().__init__()
        self._press_global: QPoint | None = None
        self._window_at_press = QPoint()
        self._dragged = False
        self._busy = False
        self._has_result = False
        self._color = "blue"
        self._ring_color = DEFAULT_RING_COLOR
        self._logo = QImage()
        self._logo_path = ""
        self._positioned = False
        self.setObjectName("FloatingOrb")
        self.setWindowTitle("FormulaSnip")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(68, 68)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("左键截取公式 · 拖动调整位置 · 右键打开菜单")
        self.set_color(color)
        self.set_logo_path(logo_path)

        self._menu = QMenu(self)
        settings_action = self._menu.addAction("打开设置")
        quit_action = self._menu.addAction("退出软件")
        settings_action.triggered.connect(self.settings_requested.emit)
        quit_action.triggered.connect(self.quit_requested.emit)

    def menu_action_texts(self) -> list[str]:
        return [action.text() for action in self._menu.actions()]

    def show_at_default_position(self) -> None:
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is not None and not self._positioned:
            area = screen.availableGeometry()
            self.move(area.right() - self.width() - 20, area.center().y() - self.height() // 2)
            self._positioned = True
        self.show()
        self.raise_()

    def set_color(self, color: str) -> None:
        if color in ORB_PALETTES:
            self._color = color
            self._ring_color = ORB_PALETTES[color][0]
        else:
            self._ring_color = normalize_hex_color(color)
            self._color = next(
                (
                    name
                    for name, (ring, _fill) in ORB_PALETTES.items()
                    if ring == self._ring_color
                ),
                self._ring_color,
            )
        self.update()

    @property
    def color_name(self) -> str:
        return self._color

    @property
    def ring_color(self) -> str:
        return self._ring_color

    @property
    def logo_path(self) -> str:
        return self._logo_path

    def set_logo_path(self, path: str) -> None:
        image = read_logo_image(path, 34)
        self._logo = image if image is not None else QImage()
        self._logo_path = path if image is not None else ""
        self.update()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.setCursor(Qt.CursorShape.BusyCursor if busy else Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            "正在识别公式…" if busy else "左键截取公式 · 拖动调整位置 · 右键打开菜单"
        )
        self.update()

    def set_result_available(self, available: bool) -> None:
        self._has_result = available
        self.update()

    @property
    def has_result(self) -> bool:
        return self._has_result

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        circle = self.rect().adjusted(4, 4, -4, -4)
        painter.setPen(QPen(QColor(self._ring_color), 4))
        painter.setBrush(QColor("#1A2434") if not self._busy else QColor("#3B4658"))
        painter.drawEllipse(circle)

        if not self._busy and not self._logo.isNull():
            target = self._logo.size().scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio)
            logo_rect = QRect(QPoint(), target)
            logo_rect.moveCenter(circle.center())
            painter.drawImage(logo_rect, self._logo)
        else:
            painter.setPen(QColor("#ffffff"))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(15 if not self._busy else 13)
            painter.setFont(font)
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, "···" if self._busy else "fx")

        if self._has_result and not self._busy:
            painter.setPen(QPen(QColor("#0f172a"), 2))
            painter.setBrush(QColor("#34d399"))
            painter.drawEllipse(self.width() - 18, 7, 11, 11)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu_below()
            return
        if event.button() == Qt.MouseButton.LeftButton and not self._busy:
            self._press_global = event.globalPosition().toPoint()
            self._window_at_press = self.pos()
            self._dragged = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_global is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        delta = event.globalPosition().toPoint() - self._press_global
        if delta.manhattanLength() >= QApplication.startDragDistance():
            self._dragged = True
        if self._dragged:
            self.move(self._clamped_position(self._window_at_press + delta))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._press_global is None:
            return
        was_dragged = self._dragged
        self._press_global = None
        self._dragged = False
        if was_dragged:
            self._snap_to_edge()
        elif not self._busy:
            self.capture_requested.emit()

    def _clamped_position(self, position: QPoint) -> QPoint:
        screen = QApplication.screenAt(position + self.rect().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return position
        area = screen.availableGeometry()
        return QPoint(
            min(max(position.x(), area.left()), area.right() - self.width() + 1),
            min(max(position.y(), area.top()), area.bottom() - self.height() + 1),
        )

    def _show_context_menu_below(self) -> None:
        self._menu.popup(self._context_menu_position_below())

    def _context_menu_position_below(self) -> QPoint:
        menu_size = self._menu.sizeHint()
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        if screen is None:
            return self.mapToGlobal(QPoint(0, self.height() + 6))

        area = screen.availableGeometry()
        required_bottom = self.y() + self.height() + 6 + menu_size.height()
        if required_bottom > area.bottom() + 1:
            available_y = area.bottom() - menu_size.height() - self.height() - 5
            self.move(self.x(), max(area.top(), available_y))

        x = self.x() + (self.width() - menu_size.width()) // 2
        x = min(max(x, area.left()), area.right() - menu_size.width() + 1)
        y = self.y() + self.height() + 6
        return QPoint(x, y)

    def _snap_to_edge(self) -> None:
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        left = area.left() + 12
        right = area.right() - self.width() - 11
        target_x = left if abs(self.x() - left) <= abs(self.x() - right) else right
        self.move(target_x, self._clamped_position(self.pos()).y())


class FloatingResultPanel(QWidget):
    recapture_requested = Signal()
    result_consumed = Signal()

    def __init__(self, theme: str = "dark") -> None:
        super().__init__()
        self._result: RecognitionResult | None = None
        self._theme = "dark"
        self.setObjectName("FloatingResultPanel")
        self.setWindowTitle("FormulaSnip 识别结果")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._build_ui()
        self.set_theme(theme)

    @property
    def theme_name(self) -> str:
        return self._theme

    def set_theme(self, theme: str) -> None:
        self._theme = theme if theme in {"dark", "light"} else "dark"
        self.setProperty("theme", self._theme)
        _refresh_style(self)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 13, 14, 14)
        outer.setSpacing(9)

        header = QHBoxLayout()
        title = QLabel("公式识别结果")
        title.setObjectName("FloatingResultTitle")
        self.backend_label = QLabel()
        self.backend_label.setObjectName("FloatingMeta")
        close_button = QPushButton("×")
        close_button.setObjectName("IconButton")
        close_button.setToolTip("收起结果")
        close_button.setFixedSize(32, 32)
        close_button.clicked.connect(self._dismiss_result)
        header.addWidget(title)
        header.addWidget(self.backend_label)
        header.addStretch(1)
        header.addWidget(close_button)
        outer.addLayout(header)

        self.preview_stack = QStackedWidget()
        self.preview_stack.setObjectName("FloatingPreviewStack")
        self.preview_stack.setFixedHeight(126)
        self.preview_message = QLabel("等待识别")
        self.preview_message.setObjectName("FloatingPreviewMessage")
        self.preview_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_message.setWordWrap(True)
        self.preview_frame = QWidget()
        self.preview_frame.setObjectName("FloatingPreviewFrame")
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(30, 22, 30, 22)
        preview_layout.setSpacing(0)
        self.svg_preview = FormulaSvgWidget()
        self.svg_preview.setObjectName("FloatingSvgPreview")
        preview_layout.addWidget(self.svg_preview, 1)
        self.preview_stack.addWidget(self.preview_message)
        self.preview_stack.addWidget(self.preview_frame)
        outer.addWidget(self.preview_stack)

        self.quality_label = QLabel()
        self.quality_label.setObjectName("FloatingQuality")
        self.quality_label.setWordWrap(True)
        outer.addWidget(self.quality_label)

        self.latex_view = QPlainTextEdit()
        self.latex_view.setObjectName("FloatingLatex")
        self.latex_view.setReadOnly(True)
        self.latex_view.setMaximumHeight(68)
        outer.addWidget(self.latex_view)

        copy_row = QHBoxLayout()
        self.copy_latex_button = QPushButton("复制 LaTeX")
        self.copy_latex_button.setObjectName("FloatingPrimary")
        self.copy_mathml_button = QPushButton("复制 MathML")
        for button in (self.copy_latex_button, self.copy_mathml_button):
            button.setMinimumHeight(40)
            copy_row.addWidget(button)
        outer.addLayout(copy_row)

        self.recapture_button = QPushButton("重新截图")
        self.recapture_button.setMinimumHeight(40)
        self.recapture_button.clicked.connect(self.recapture_requested.emit)
        outer.addWidget(self.recapture_button)

        self.status_label = QLabel()
        self.status_label.setObjectName("FloatingStatus")
        outer.addWidget(self.status_label)

        self.copy_latex_button.clicked.connect(self._copy_latex)
        self.copy_mathml_button.clicked.connect(self._copy_mathml)

    def show_result(self, result: RecognitionResult, anchor: QRect) -> None:
        self._result = result
        self.copy_latex_button.setEnabled(True)
        self.copy_mathml_button.setEnabled(True)
        self.backend_label.setText(f"{result.backend_name} · {result.elapsed_seconds:.2f} 秒")
        self.latex_view.setPlainText(result.latex)
        try:
            self.svg_preview.set_formula_svg(render_formula_svg(result.latex))
            self.preview_stack.setCurrentWidget(self.preview_frame)
        except Exception:
            self.preview_message.setText("当前公式暂时无法生成电子预览，请核对 LaTeX。")
            self.preview_stack.setCurrentWidget(self.preview_message)
        adopted_issues: tuple[str, ...] = ()
        for candidate in result.alternatives:
            if candidate.latex == result.latex and candidate.backend == result.backend_name:
                adopted_issues = candidate.issues
                break
        if adopted_issues:
            self.quality_label.setText("识别结果需要人工校对：" + "；".join(adopted_issues))
            self.quality_label.setProperty("warning", True)
        elif result.warnings and any(
            marker in result.warnings[0] for marker in ("未安装", "失败", "需要人工校对")
        ):
            self.quality_label.setText(result.warnings[0])
            self.quality_label.setProperty("warning", True)
        else:
            self.quality_label.setText("电子公式已生成，请与原公式核对后复制")
            self.quality_label.setProperty("warning", False)
        _refresh_style(self.quality_label)
        self.status_label.setText("")
        self._show_near(anchor)

    def show_error(self, message: str, anchor: QRect) -> None:
        self._result = None
        self.backend_label.setText("识别失败")
        self.preview_message.setText(message)
        self.preview_stack.setCurrentWidget(self.preview_message)
        self.quality_label.setText("请检查模型安装后重新截图。")
        self.quality_label.setProperty("warning", True)
        _refresh_style(self.quality_label)
        self.latex_view.clear()
        self.copy_latex_button.setDisabled(True)
        self.copy_mathml_button.setDisabled(True)
        self._show_near(anchor)

    def _show_near(self, anchor: QRect) -> None:
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        if screen is None:
            self.resize(500, self.sizeHint().height())
            self.show()
            return
        area = screen.availableGeometry()
        panel_width = min(500, max(280, area.width() - 24))
        self.setFixedWidth(panel_width)
        self.adjustSize()
        x = anchor.left() - self.width() - 12
        if x < area.left():
            x = anchor.right() + 12
        x = min(max(x, area.left()), area.right() - self.width() + 1)
        y = min(max(anchor.top(), area.top()), area.bottom() - self.height() + 1)
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    @Slot()
    def _copy_latex(self) -> None:
        if self._result is None:
            return
        try:
            QApplication.clipboard().setText(self._result.latex)
        except Exception as exc:
            self.status_label.setText(f"复制失败：{exc}")
            return
        self.status_label.setText("LaTeX 已复制")
        self._result = None
        self.hide()
        self.result_consumed.emit()

    @Slot()
    def _copy_mathml(self) -> None:
        if self._result is None:
            return
        try:
            mathml = latex_to_mathml(self._result.latex)
            mime_data = QMimeData()
            mime_data.setText(mathml)
            mime_data.setData("application/mathml+xml", mathml.encode("utf-8"))
            QApplication.clipboard().setMimeData(mime_data)
        except (FormulaSnipError, RuntimeError) as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("MathML 已复制，可粘贴到 Word/MathType")
        self._result = None
        self.hide()
        self.result_consumed.emit()

    @Slot()
    def _dismiss_result(self) -> None:
        self._result = None
        self.hide()
        self.result_consumed.emit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._result is not None:
            self._result = None
            self.result_consumed.emit()
        event.accept()


class FloatingFormulaAssistant(QObject):
    """Own the settings, floating capture and compact result workflow."""

    def __init__(
        self,
        *,
        settings: QSettings | None = None,
        manager: BackendManager | None = None,
    ) -> None:
        super().__init__()
        self.settings_store = settings or QSettings()
        self.preferences = FloatingPreferences.load(self.settings_store)
        apply_application_theme(self.preferences.result_theme)
        self.manager = manager or BackendManager()
        self.orb = FloatingOrb(
            self.preferences.effective_ring_color,
            self.preferences.effective_logo_path,
        )
        self.panel = FloatingResultPanel(self.preferences.result_theme)
        self.settings_panel = SettingsPanel(self.settings_store, self.preferences)
        self._overlay: SnipOverlay | None = None
        self._worker: RecognitionWorker | None = None
        self._capture_pending = False
        self._last_image: QImage | None = None
        self._last_result: RecognitionResult | None = None
        self._pending_result = False
        self._pending_error: str | None = None
        self._settings_visible = False
        self._thread_pool = QThreadPool.globalInstance()

        self.orb.capture_requested.connect(self.start_capture)
        self.orb.settings_requested.connect(self.open_settings)
        self.orb.quit_requested.connect(QApplication.quit)
        self.panel.recapture_requested.connect(self.start_capture)
        self.panel.result_consumed.connect(self._result_consumed)
        self.settings_panel.start_requested.connect(self.enter_floating_mode)
        self.settings_panel.preferences_changed.connect(self._apply_preferences)

    def show(self) -> None:
        if self.preferences.show_settings_on_startup:
            self.open_settings()
        else:
            self.enter_floating_mode()

    @Slot()
    def open_settings(self) -> None:
        self._settings_visible = True
        if self._last_result is not None and self.panel.isVisible():
            self._pending_result = True
        self.panel.hide()
        self.orb.hide()
        self.settings_panel.show_settings_page()
        self.settings_panel.show()
        self.settings_panel.raise_()
        self.settings_panel.activateWindow()

    @Slot()
    def enter_floating_mode(self) -> None:
        self._settings_visible = False
        self.settings_panel.hide()
        self.orb.show_at_default_position()
        if self._pending_result and self._last_result is not None:
            self._pending_result = False
            self.panel.show_result(self._last_result, self.orb.geometry())
        elif self._pending_error is not None:
            message = self._pending_error
            self._pending_error = None
            self.panel.show_error(message, self.orb.geometry())

    @Slot(object)
    def _apply_preferences(self, preferences: FloatingPreferences) -> None:
        self.preferences = preferences
        self.orb.set_color(preferences.effective_ring_color)
        self.orb.set_logo_path(preferences.effective_logo_path)
        self.panel.set_theme(preferences.result_theme)
        apply_application_theme(preferences.result_theme)

    @Slot()
    def start_capture(self) -> None:
        if self._worker is not None or self._capture_pending or self._overlay is not None:
            return
        self._capture_pending = True
        self.panel.hide()
        self.orb.hide()
        QTimer.singleShot(180, self._show_screen_overlay)

    def _show_screen_overlay(self) -> None:
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            self._capture_pending = False
            self.orb.show()
            self.panel.show_error("没有找到可截图的屏幕。", self.orb.geometry())
            return
        screenshot = screen.grabWindow(0)
        if screenshot.isNull():
            self._capture_pending = False
            self.orb.show()
            self.panel.show_error("屏幕截图失败。", self.orb.geometry())
            return
        self._overlay = SnipOverlay(screen, screenshot)
        self._overlay.captured.connect(self._captured)
        self._overlay.cancelled.connect(self._capture_cancelled)
        self._overlay.show_overlay()

    @Slot(QPixmap)
    def _captured(self, pixmap: QPixmap) -> None:
        self._capture_pending = False
        self._overlay = None
        self.orb.show()
        self.orb.raise_()
        self.orb.set_busy(True)
        self.orb.set_result_available(False)
        self._last_image = pixmap.toImage()
        self._last_result = None
        self._pending_result = False
        self._pending_error = None
        try:
            image = qimage_to_pil(self._last_image)
        except ValueError as exc:
            self._recognition_failed(str(exc))
            return
        worker = RecognitionWorker(self.manager, image, self.preferences.recognition_mode)
        worker.signals.finished.connect(self._recognition_finished)
        worker.signals.failed.connect(self._recognition_failed)
        self._worker = worker
        self._thread_pool.start(worker)

    @Slot()
    def _capture_cancelled(self) -> None:
        self._capture_pending = False
        self._overlay = None
        self.orb.show()
        self.orb.raise_()
        if self._last_result is not None and not self._settings_visible:
            self.panel.show_result(self._last_result, self.orb.geometry())

    @Slot(object)
    def _recognition_finished(self, result: RecognitionResult) -> None:
        self._worker = None
        self._last_result = result
        self._pending_error = None
        self.orb.set_busy(False)
        self.orb.set_result_available(True)
        if self._settings_visible:
            self._pending_result = True
            return
        self.panel.show_result(result, self.orb.geometry())

    @Slot(str)
    def _recognition_failed(self, message: str) -> None:
        self._worker = None
        self.orb.set_busy(False)
        if self._settings_visible:
            self._pending_error = message
            return
        self.panel.show_error(message, self.orb.geometry())

    @Slot()
    def _result_consumed(self) -> None:
        self._pending_result = False
        self._last_image = None
        self._last_result = None
        self.orb.set_result_available(False)


def _refresh_style(widget: QWidget) -> None:
    widgets = (widget, *widget.findChildren(QWidget))
    for item in widgets:
        item.style().unpolish(item)
        item.style().polish(item)
