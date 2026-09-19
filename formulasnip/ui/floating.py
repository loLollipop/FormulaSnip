from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import (
    QMimeData,
    QObject,
    QPoint,
    QProcess,
    QRect,
    QSettings,
    QSignalBlocker,
    QStandardPaths,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtCore import QTimer as PreviewTimer
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QCursor,
    QDesktopServices,
    QHideEvent,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from formulasnip.core.latex import latex_to_mathml
from formulasnip.credentials import CredentialError, OpenAIApiKeyStore
from formulasnip.domain import RecognitionCandidate, RecognitionResult
from formulasnip.exceptions import FormulaSnipError
from formulasnip.recognition import BackendManager
from formulasnip.recognition.quality import assess_latex
from formulasnip.ui.branding import application_icon, application_version
from formulasnip.ui.image_conversion import qimage_to_pil
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
from formulasnip.ui.update_dialog import (
    UpdateCheckWorker,
    UpdateDialog,
    UpdateDownloadWorker,
)
from formulasnip.ui.widgets import FormulaPreviewWidget
from formulasnip.ui.worker import ModelWarmupWorker, RecognitionWorker
from formulasnip.update import (
    CHECK_INTERVAL_SECONDS,
    ReleaseInfo,
    is_installed_build,
    launch_verified_installer,
    should_check_for_updates,
)

ORB_PALETTES = {
    "blue": (RING_PRESETS["blue"], "#1A2434"),
    "green": (RING_PRESETS["green"], "#1A2434"),
    "orange": (RING_PRESETS["orange"], "#1A2434"),
}


class FloatingOrb(QWidget):
    capture_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()
    close_requested = Signal()

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

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if event.spontaneous():
            event.ignore()
            self.close_requested.emit()
            return
        event.accept()


class FloatingResultPanel(QWidget):
    recapture_requested = Signal()
    result_consumed = Signal()
    draft_changed = Signal(str)
    source_changed = Signal(str)

    def __init__(self, theme: str = "dark") -> None:
        super().__init__()
        self._result: RecognitionResult | None = None
        self._source_candidates: dict[str, RecognitionCandidate] = {}
        self._active_source = ""
        self._preview_request_id: int | None = None
        self._preview_request_edited = False
        self._preview_request_candidate: RecognitionCandidate | None = None
        self._theme = "dark"
        self._preview_timer = PreviewTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(300)
        self._preview_timer.timeout.connect(self._refresh_edited_preview)
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
        self.preview_stack.setFixedHeight(168)
        self.preview_message = QLabel("等待识别")
        self.preview_message.setObjectName("FloatingPreviewMessage")
        self.preview_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_message.setWordWrap(True)
        self.preview_frame = QWidget()
        self.preview_frame.setObjectName("FloatingPreviewFrame")
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(0)
        self.formula_preview = FormulaPreviewWidget()
        self.formula_preview.setObjectName("FloatingFormulaPreview")
        self.formula_preview.rendered.connect(self._preview_rendered)
        self.formula_preview.failed.connect(self._preview_failed)
        preview_layout.addWidget(self.formula_preview, 1)
        self.preview_stack.addWidget(self.preview_message)
        self.preview_stack.addWidget(self.preview_frame)
        outer.addWidget(self.preview_stack)

        self.quality_label = QLabel()
        self.quality_label.setObjectName("FloatingQuality")
        self.quality_label.setWordWrap(True)
        outer.addWidget(self.quality_label)

        self.source_switch = QWidget()
        self.source_switch.setObjectName("FloatingSourceSwitch")
        self.source_switch.setAccessibleName("识别结果来源")
        self.source_switch.setAccessibleDescription(
            "在本地识别和 AI 识别结果之间切换"
        )
        source_layout = QHBoxLayout(self.source_switch)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(0)
        self.local_result_button = QPushButton("本地结果")
        self.ai_result_button = QPushButton("AI 结果")
        self.local_source_button = self.local_result_button
        self.ai_source_button = self.ai_result_button
        self._source_button_group = QButtonGroup(self)
        self._source_button_group.setExclusive(True)
        for source, button, description in (
            ("local", self.local_result_button, "显示本地 MathCraft 识别结果"),
            ("ai", self.ai_result_button, "显示 AI 图像识别结果"),
        ):
            button.setObjectName("FloatingSourceButton")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setAccessibleName(button.text())
            button.setAccessibleDescription(description)
            button.clicked.connect(lambda _checked=False, value=source: self._select_source(value))
            self._source_button_group.addButton(button)
            source_layout.addWidget(button)
        self.source_switch.hide()
        outer.addWidget(self.source_switch)

        self.latex_view = QPlainTextEdit()
        self.latex_view.setObjectName("FloatingLatex")
        self.latex_view.setMaximumHeight(68)
        self.latex_view.setPlaceholderText("在此修改 LaTeX，预览会自动更新")
        outer.addWidget(self.latex_view)
        QWidget.setTabOrder(self.local_result_button, self.ai_result_button)
        QWidget.setTabOrder(self.ai_result_button, self.latex_view)

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
        self.latex_view.textChanged.connect(self._latex_edited)

    def show_result(
        self,
        result: RecognitionResult,
        anchor: QRect,
        draft: str | None = None,
        source: str | None = None,
    ) -> None:
        self._result = result
        self._preview_timer.stop()
        selected_candidate = self._configure_source_switch(result, draft, source)
        self._update_backend_label(selected_candidate)
        baseline_latex = selected_candidate.latex if selected_candidate else result.latex
        displayed_latex = baseline_latex if draft is None else draft
        edited_draft = displayed_latex != baseline_latex
        blocker = QSignalBlocker(self.latex_view)
        self.latex_view.setPlainText(displayed_latex)
        del blocker
        self._update_copy_buttons()
        self._render_preview(
            displayed_latex,
            edited=edited_draft,
            candidate=None if edited_draft else selected_candidate,
        )
        self._show_near(anchor)

    def show_error(self, message: str, anchor: QRect) -> None:
        self._clear_source_switch()
        self._result = None
        self.backend_label.setText("识别失败")
        self.preview_message.setText(message)
        self.preview_stack.setCurrentWidget(self.preview_message)
        self.quality_label.setText("请检查模型安装后重新截图。")
        self.quality_label.setProperty("warning", True)
        _refresh_style(self.quality_label)
        self._preview_timer.stop()
        self._preview_request_id = None
        blocker = QSignalBlocker(self.latex_view)
        self.latex_view.clear()
        del blocker
        self.copy_latex_button.setDisabled(True)
        self.copy_mathml_button.setDisabled(True)
        self.status_label.clear()
        self._show_near(anchor)

    def _configure_source_switch(
        self,
        result: RecognitionResult,
        draft: str | None,
        source: str | None,
    ) -> RecognitionCandidate | None:
        self._clear_source_switch()
        self._source_candidates = {
            candidate.source: candidate
            for candidate in result.alternatives
            if candidate.source in {"local", "ai"}
        }
        show_switch = (
            result.comparison == "different"
            and "local" in self._source_candidates
            and "ai" in self._source_candidates
        )
        self.source_switch.setVisible(show_switch)
        if show_switch:
            if source in self._source_candidates:
                selected_source = source
            else:
                selected_source = next(
                    (
                        candidate_source
                        for candidate_source, candidate in self._source_candidates.items()
                        if draft is not None and draft == candidate.latex
                    ),
                    "ai",
                )
            self._active_source = selected_source
            selected_button = (
                self.local_result_button
                if selected_source == "local"
                else self.ai_result_button
            )
            selected_button.setChecked(True)
            return self._source_candidates[selected_source]
        return next(
            (
                candidate
                for candidate in result.alternatives
                if candidate.latex == result.latex
                and candidate.backend == result.backend_name
            ),
            None,
        )

    def _clear_source_switch(self) -> None:
        self._source_candidates.clear()
        self._active_source = ""
        self._source_button_group.setExclusive(False)
        self.local_result_button.setChecked(False)
        self.ai_result_button.setChecked(False)
        self._source_button_group.setExclusive(True)
        self.source_switch.hide()

    def _update_backend_label(
        self, candidate: RecognitionCandidate | None = None
    ) -> None:
        if candidate is not None:
            backend = candidate.backend
            elapsed = candidate.elapsed_seconds
        elif self._result is not None:
            backend = self._result.backend_name
            elapsed = self._result.elapsed_seconds
        else:
            return
        self.backend_label.setText(f"{backend} · {elapsed:.2f} 秒")

    @Slot(str)
    def _select_source(self, source: str) -> None:
        if self._result is None:
            return
        candidate = self._source_candidates.get(source)
        if candidate is None:
            return
        source_changed = source != self._active_source
        self._active_source = source
        button = self.local_result_button if source == "local" else self.ai_result_button
        button.setChecked(True)
        self._preview_timer.stop()
        blocker = QSignalBlocker(self.latex_view)
        self.latex_view.setPlainText(candidate.latex)
        del blocker
        if source_changed:
            self.source_changed.emit(source)
        self.draft_changed.emit(candidate.latex)
        self._update_backend_label(candidate)
        self._update_copy_buttons()
        self._render_preview(candidate.latex, edited=False, candidate=candidate)

    def _show_candidate_quality(
        self,
        candidate: RecognitionCandidate | None,
        *,
        preview_pending: bool = False,
    ) -> None:
        warnings = list(self._result.warnings if self._result is not None else ())
        if candidate is not None and candidate.issues:
            warnings.insert(0, "识别结果需要人工校对：" + "；".join(candidate.issues))
        if candidate is not None and candidate.previewable is False:
            warnings.insert(0, "当前结果无法预览，可继续修改 LaTeX 后重试。")
        if warnings:
            self.quality_label.setText("\n".join(dict.fromkeys(warnings)))
            self.quality_label.setProperty("warning", True)
        elif preview_pending:
            self.quality_label.setText("正在生成预览…")
            self.quality_label.setProperty("warning", False)
        else:
            self.quality_label.setText("电子公式已生成，请与原公式核对后复制")
            self.quality_label.setProperty("warning", False)
        _refresh_style(self.quality_label)

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
        latex = self.latex_view.toPlainText()
        if not latex.strip():
            return
        try:
            QApplication.clipboard().setText(latex)
        except Exception as exc:
            self.status_label.setText(f"复制失败：{exc}")
            return
        self.status_label.setText("LaTeX 已复制")
        self._clear_source_switch()
        self._result = None
        self._preview_timer.stop()
        self.hide()
        self.result_consumed.emit()

    @Slot()
    def _copy_mathml(self) -> None:
        if self._result is None:
            return
        latex = self.latex_view.toPlainText()
        if not latex.strip():
            return
        try:
            mathml = latex_to_mathml(latex)
            mime_data = QMimeData()
            mime_data.setText(mathml)
            mime_data.setData("application/mathml+xml", mathml.encode("utf-8"))
            QApplication.clipboard().setMimeData(mime_data)
        except (FormulaSnipError, RuntimeError) as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("MathML 已复制，可粘贴到 Word/MathType")
        self._clear_source_switch()
        self._result = None
        self._preview_timer.stop()
        self.hide()
        self.result_consumed.emit()

    @Slot()
    def _latex_edited(self) -> None:
        latex = self.latex_view.toPlainText()
        self._preview_request_id = None
        self.draft_changed.emit(latex)
        self._update_copy_buttons()
        if latex.strip():
            self._show_pending_preview_quality(
                latex,
                edited=True,
                candidate=None,
            )
        self.status_label.setText("正在更新预览…" if latex.strip() else "")
        self._preview_timer.start()

    @Slot()
    def _refresh_edited_preview(self) -> None:
        self._render_preview(self.latex_view.toPlainText(), edited=True)

    def _update_copy_buttons(self) -> None:
        enabled = self._result is not None and bool(self.latex_view.toPlainText().strip())
        self.copy_latex_button.setEnabled(enabled)
        self.copy_mathml_button.setEnabled(enabled)

    def _render_preview(
        self,
        latex: str,
        *,
        edited: bool,
        candidate: RecognitionCandidate | None = None,
    ) -> None:
        self._preview_request_id = None
        self._preview_request_edited = edited
        self._preview_request_candidate = candidate
        if not latex.strip():
            self.preview_message.setText("请输入 LaTeX 以生成电子公式预览。")
            self.preview_stack.setCurrentWidget(self.preview_message)
            if edited:
                self.quality_label.setText("LaTeX 为空，请继续修改。")
                self.quality_label.setProperty("warning", True)
                self.status_label.clear()
                _refresh_style(self.quality_label)
            return
        try:
            request_id = self.formula_preview.set_formula(latex)
        except Exception:
            self.preview_message.setText(
                "当前 LaTeX 暂时无法生成电子公式预览，可继续修改后重试。"
            )
            self.preview_stack.setCurrentWidget(self.preview_message)
            if edited:
                warnings = ["预览生成失败，可继续修改 LaTeX 后重试。"]
                warnings.extend(self._persistent_result_warnings())
                self.quality_label.setText("\n".join(dict.fromkeys(warnings)))
                self.quality_label.setProperty("warning", True)
                self.status_label.setText("预览生成失败，可继续修改")
                _refresh_style(self.quality_label)
            return
        self._preview_request_id = request_id
        self.preview_stack.setCurrentWidget(self.preview_frame)
        self._show_pending_preview_quality(latex, edited=edited, candidate=candidate)
        self.status_label.setText("正在生成预览…")

    def _show_pending_preview_quality(
        self,
        latex: str,
        *,
        edited: bool,
        candidate: RecognitionCandidate | None,
    ) -> None:
        if edited:
            report = assess_latex(latex)
            warnings = list(self._persistent_result_warnings())
            if report.issues:
                warnings.insert(0, "识别结果需要人工校对：" + "；".join(report.issues))
            if warnings:
                self.quality_label.setText("\n".join(dict.fromkeys(warnings)))
                self.quality_label.setProperty("warning", True)
            else:
                self.quality_label.setText("正在生成预览…")
                self.quality_label.setProperty("warning", False)
        else:
            self._show_candidate_quality(candidate, preview_pending=True)
            return
        _refresh_style(self.quality_label)

    @Slot(int, str)
    def _preview_rendered(self, request_id: int, _backend: str) -> None:
        if request_id != self._preview_request_id:
            return
        if request_id != self.formula_preview.request_id:
            return
        self.preview_stack.setCurrentWidget(self.preview_frame)
        if self._preview_request_edited:
            latex = self.latex_view.toPlainText()
            report = assess_latex(latex)
            warnings = list(self._persistent_result_warnings())
            if report.issues:
                warnings.insert(0, "识别结果需要人工校对：" + "；".join(report.issues))
            if warnings:
                self.quality_label.setText("\n".join(dict.fromkeys(warnings)))
                self.quality_label.setProperty("warning", True)
            else:
                self.quality_label.setText("电子公式预览已更新，请核对后复制")
                self.quality_label.setProperty("warning", False)
            self.status_label.setText("预览已更新")
        else:
            self._show_candidate_quality(
                self._preview_request_candidate,
                preview_pending=False,
            )
            self.status_label.setText("电子公式已生成")
        _refresh_style(self.quality_label)

    @Slot(int, str)
    def _preview_failed(self, request_id: int, _detail: str) -> None:
        if request_id != self._preview_request_id:
            return
        if request_id != self.formula_preview.request_id:
            return
        self.preview_message.setText(
            "当前 LaTeX 暂时无法生成电子公式预览，可继续修改后重试。"
        )
        self.preview_stack.setCurrentWidget(self.preview_message)
        warnings = ["预览生成失败，可继续修改 LaTeX 后重试。"]
        warnings.extend(self._persistent_result_warnings())
        self.quality_label.setText("\n".join(dict.fromkeys(warnings)))
        self.quality_label.setProperty("warning", True)
        self.status_label.setText("预览生成失败，可继续修改")
        _refresh_style(self.quality_label)

    def _persistent_result_warnings(self) -> tuple[str, ...]:
        if self._result is None:
            return ()
        text_dependent_markers = (
            "识别结果需要人工校对",
            "当前识别结果无法生成电子公式预览",
            "两个引擎均未生成可预览候选",
        )
        return tuple(
            warning
            for warning in self._result.warnings
            if not any(marker in warning for marker in text_dependent_markers)
        )

    @Slot()
    def _dismiss_result(self) -> None:
        self._clear_source_switch()
        self._result = None
        self._preview_timer.stop()
        self._preview_request_id = None
        self.hide()
        self.result_consumed.emit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._result is not None:
            self._clear_source_switch()
            self._result = None
            self._preview_timer.stop()
            self.result_consumed.emit()
        event.accept()

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        self._preview_timer.stop()
        super().hideEvent(event)


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
        self._api_key_store = OpenAIApiKeyStore()
        self.orb = FloatingOrb(
            self.preferences.effective_ring_color,
            self.preferences.effective_logo_path,
        )
        self.panel = FloatingResultPanel(self.preferences.result_theme)
        self.settings_panel = SettingsPanel(
            self.settings_store,
            self.preferences,
            api_key_store=self._api_key_store,
        )
        self.preferences = self.settings_panel.preferences
        self._overlay: SnipOverlay | None = None
        self._worker: RecognitionWorker | None = None
        self._capture_pending = False
        self._last_image: QImage | None = None
        self._last_result: RecognitionResult | None = None
        self._last_result_draft: str | None = None
        self._last_result_source: str | None = None
        self._pending_result = False
        self._pending_error: str | None = None
        self._settings_visible = False
        self._shutdown = False
        self._tray_icon: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._thread_pool = QThreadPool.globalInstance()
        self._warmup_worker: ModelWarmupWorker | None = None
        self._update_check_worker: UpdateCheckWorker | None = None
        self._update_download_worker: UpdateDownloadWorker | None = None
        self._update_dialog: UpdateDialog | None = None
        self._update_check_manual_requested = False
        self._pending_update_install: tuple[Path, ReleaseInfo] | None = None
        from PySide6.QtCore import QTimer as RepeatingTimer

        self._update_timer = RepeatingTimer(self)
        self._update_timer.setInterval(CHECK_INTERVAL_SECONDS * 1000)
        self._update_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._update_timer.timeout.connect(self.check_for_updates)
        self._tray_trigger_timer = RepeatingTimer(self)
        self._tray_trigger_timer.setSingleShot(True)
        self._tray_trigger_timer.timeout.connect(self._run_delayed_tray_trigger)

        self.orb.capture_requested.connect(self.start_capture)
        self.orb.settings_requested.connect(self.open_settings)
        self.orb.quit_requested.connect(QApplication.quit)
        self.orb.close_requested.connect(self._orb_close_requested)
        self.panel.recapture_requested.connect(self.start_capture)
        self.panel.result_consumed.connect(self._result_consumed)
        self.panel.draft_changed.connect(self._result_draft_changed)
        self.panel.source_changed.connect(self._result_source_changed)
        self.settings_panel.start_requested.connect(self.enter_floating_mode)
        self.settings_panel.preferences_changed.connect(self._apply_preferences)
        self.settings_panel.ai_credential_changed.connect(
            self._cancel_active_recognition
        )
        self.settings_panel.update_check_requested.connect(
            lambda: self.check_for_updates(manual=True)
        )
        self._create_system_tray()

    def _create_system_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        menu = QMenu()
        start_action = menu.addAction("开始识别")
        show_action = menu.addAction("显示悬浮球")
        settings_action = menu.addAction("打开设置")
        update_action = menu.addAction("检查更新")
        menu.addSeparator()
        quit_action = menu.addAction("退出软件")
        start_action.triggered.connect(self._start_capture_from_tray)
        show_action.triggered.connect(self._show_floating_from_tray)
        settings_action.triggered.connect(self._open_settings_from_tray)
        update_action.triggered.connect(self._check_for_updates_from_tray)
        quit_action.triggered.connect(self._quit_from_tray)

        tray = QSystemTrayIcon(application_icon(), self)
        tray.setToolTip("FormulaSnip 公式识别")
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        self._tray_menu = menu
        self._tray_icon = tray
        tray.show()

    @Slot()
    def _orb_close_requested(self) -> None:
        if self._tray_icon is not None:
            self.orb.hide()
            return
        QApplication.quit()

    def start_model_warmup(self) -> None:
        """Start one ordered, non-blocking model warmup run."""

        if self._warmup_worker is not None:
            return
        worker = ModelWarmupWorker(self.manager, ("mathcraft",))
        worker.signals.started.connect(
            lambda key: self.settings_panel.set_engine_status(key, "started")
        )
        worker.signals.succeeded.connect(
            lambda key: self.settings_panel.set_engine_status(key, "succeeded")
        )
        worker.signals.failed.connect(
            lambda key, _message: self.settings_panel.set_engine_status(key, "failed")
        )
        worker.signals.finished.connect(self._model_warmup_finished)
        self._warmup_worker = worker
        self._thread_pool.start(worker)

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._update_timer.stop()
        self._tray_trigger_timer.stop()
        update_check_worker = self._update_check_worker
        update_download_worker = self._update_download_worker
        self._update_check_worker = None
        self._update_download_worker = None
        if update_check_worker is not None:
            update_check_worker.cancel()
        if update_download_worker is not None:
            update_download_worker.cancel()
            if (
                self._pending_update_install is None
                and update_download_worker.completed_path is not None
            ):
                self._pending_update_install = (
                    update_download_worker.completed_path,
                    update_download_worker.release,
                )
        if self._worker is not None:
            self._worker.cancel()
        self.settings_panel.cancel_ai_request()
        if self._pending_update_install is not None:
            self._try_launch_pending_installer(force=True, quit_application=False)
        else:
            if update_download_worker is not None:
                self._reset_update_throttle_for_retry()
            self.manager.close()
        tray = self._tray_icon
        menu = self._tray_menu
        self._tray_icon = None
        self._tray_menu = None
        if tray is not None:
            tray.hide()
            tray.setContextMenu(None)
            tray.deleteLater()
        if menu is not None:
            menu.close()
            menu.deleteLater()

    @Slot()
    def _model_warmup_finished(self) -> None:
        self._warmup_worker = None
        if self._shutdown:
            return
        self._try_launch_pending_installer()

    def show(self) -> None:
        if self.preferences.show_settings_on_startup:
            self.open_settings()
        else:
            self.enter_floating_mode()

    def start_update_checks(self) -> None:
        if self._shutdown:
            return
        if self._update_timer.isActive():
            return
        self._update_timer.start()
        QTimer.singleShot(1500, lambda: self.check_for_updates(force=True))

    def _restart_update_timer(self) -> None:
        if not self._shutdown and self._update_timer.isActive():
            self._update_timer.start()

    @Slot()
    def check_for_updates(self, *, manual: bool = False, force: bool = False) -> None:
        if self._shutdown:
            return
        if self._update_check_worker is not None:
            if manual:
                self._update_check_manual_requested = True
                self.settings_panel.set_update_status("正在检查更新…", checking=True)
            return
        now = int(time.time())
        last_check = self.settings_store.value("updates/last_check_utc")
        if not should_check_for_updates(
            last_check,
            now_seconds=now,
            manual=manual or force,
        ):
            return
        if manual:
            self.settings_panel.set_update_status("正在检查更新…", checking=True)
        self._update_check_manual_requested = manual
        worker = UpdateCheckWorker(application_version())
        worker.signals.available.connect(
            lambda release, requested=manual: self._update_available(release, requested)
        )
        worker.signals.no_update.connect(
            lambda requested=manual: self._update_not_available(requested)
        )
        worker.signals.failed.connect(
            lambda message, requested=manual: self._update_check_failed(message, requested)
        )
        self._update_check_worker = worker
        self._thread_pool.start(worker)

    @Slot(object)
    def _update_available(self, release: ReleaseInfo, manual: bool) -> None:
        self._update_check_worker = None
        if self._shutdown:
            return
        manual = manual or self._update_check_manual_requested
        self._update_check_manual_requested = False
        self._restart_update_timer()
        self.settings_store.setValue("updates/last_check_utc", int(time.time()))
        self.settings_store.sync()
        if manual:
            self.settings_panel.set_update_status(f"发现新版本 v{release.version}")
        dialog = UpdateDialog(application_version(), release)
        dialog.update_requested.connect(lambda: self._begin_update(release))
        self._update_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    @Slot()
    def _update_not_available(self, manual: bool) -> None:
        self._update_check_worker = None
        if self._shutdown:
            return
        manual = manual or self._update_check_manual_requested
        self._update_check_manual_requested = False
        self._restart_update_timer()
        self.settings_store.setValue("updates/last_check_utc", int(time.time()))
        self.settings_store.sync()
        if manual:
            self.settings_panel.set_update_status("已是最新版本")

    @Slot(str)
    def _update_check_failed(self, message: str, manual: bool) -> None:
        self._update_check_worker = None
        if self._shutdown:
            return
        manual = manual or self._update_check_manual_requested
        self._update_check_manual_requested = False
        self._restart_update_timer()
        if manual:
            self.settings_panel.set_update_status(f"检查失败：{message}")

    def _begin_update(self, release: ReleaseInfo) -> None:
        if self._shutdown:
            return
        dialog = self._update_dialog
        if dialog is None or self._update_download_worker is not None:
            return
        if not is_installed_build():
            QDesktopServices.openUrl(QUrl(release.page_url))
            dialog.show_source_build_message()
            return
        cache_root = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.CacheLocation
        )
        if not cache_root:
            dialog.show_error("无法找到用户缓存目录。")
            return
        dialog.show_downloading()
        worker = UpdateDownloadWorker(release, Path(cache_root) / "updates")
        worker.signals.progress.connect(self._update_download_progress)
        worker.signals.finished.connect(
            lambda path, selected=release: self._update_downloaded(path, selected)
        )
        worker.signals.failed.connect(self._update_download_failed)
        self._update_download_worker = worker
        self._thread_pool.start(worker)

    @Slot(object)
    def _update_downloaded(self, path: Path, release: ReleaseInfo) -> None:
        self._update_download_worker = None
        if self._shutdown:
            return
        self._pending_update_install = (Path(path), release)
        self._try_launch_pending_installer()

    def _try_launch_pending_installer(
        self,
        *,
        force: bool = False,
        quit_application: bool = True,
    ) -> bool:
        pending = self._pending_update_install
        if pending is None:
            return False
        dialog = self._update_dialog
        if not force and (
            self._worker is not None
            or self._warmup_worker is not None
            or self._capture_pending
            or self._overlay is not None
        ):
            if dialog is not None:
                dialog.show_waiting_for_recognition()
            return False
        path, release = pending
        self._pending_update_install = None
        try:
            self.manager.close()
            logging.getLogger(__name__).info("update-installer-launch")
            started = launch_verified_installer(
                path,
                release.asset,
                start_detached=QProcess.startDetached,
            )
        except Exception as exc:
            if self._shutdown:
                self._reset_update_throttle_for_retry()
                logging.getLogger(__name__).warning(
                    "update-installer-launch-failed: %s", exc
                )
            else:
                self.manager = BackendManager()
            if dialog is not None and not self._shutdown:
                dialog.show_error(f"安装包校验失败：{exc}")
            return False
        if not started:
            if self._shutdown:
                self._reset_update_throttle_for_retry()
                logging.getLogger(__name__).warning("update-installer-start-failed")
            else:
                self.manager = BackendManager()
            if dialog is not None and not self._shutdown:
                dialog.show_error("无法启动更新安装程序。")
            return False
        if quit_application:
            QApplication.quit()
        return True

    def _reset_update_throttle_for_retry(self) -> None:
        self.settings_store.remove("updates/last_check_utc")
        self.settings_store.sync()

    @Slot(object, object)
    def _update_download_progress(self, received: int, total: int) -> None:
        if self._shutdown or self._update_dialog is None:
            return
        self._update_dialog.set_download_progress(received, total)

    @Slot(str)
    def _update_download_failed(self, message: str) -> None:
        self._update_download_worker = None
        if self._shutdown:
            return
        if self._update_dialog is not None:
            self._update_dialog.show_error(f"更新失败：{message}")

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
            self.panel.show_result(
                self._last_result,
                self.orb.geometry(),
                self._last_result_draft,
                self._last_result_source,
            )
        elif self._pending_error is not None:
            message = self._pending_error
            self._pending_error = None
            self.panel.show_error(message, self.orb.geometry())

    def _capture_in_progress(self) -> bool:
        return self._capture_pending or self._overlay is not None

    def _can_start_capture(self) -> bool:
        return (
            not self._shutdown
            and self._pending_update_install is None
            and self._worker is None
            and not self._capture_in_progress()
        )

    @Slot()
    def _start_capture_from_tray(self) -> None:
        if not self._can_start_capture():
            return
        self.enter_floating_mode()
        self.start_capture()

    @Slot()
    def _show_floating_from_tray(self) -> None:
        if self._shutdown or self._capture_in_progress():
            return
        self.enter_floating_mode()

    @Slot()
    def _run_delayed_tray_trigger(self) -> None:
        self._show_floating_from_tray()

    @Slot()
    def _open_settings_from_tray(self) -> None:
        if self._shutdown or self._capture_in_progress():
            return
        self.open_settings()

    @Slot()
    def _check_for_updates_from_tray(self) -> None:
        if self._shutdown or self._capture_in_progress():
            return
        self.open_settings()
        self.check_for_updates(manual=True)

    @staticmethod
    @Slot()
    def _quit_from_tray() -> None:
        QApplication.quit()

    @Slot(object)
    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if not self._shutdown:
                self._tray_trigger_timer.start(QApplication.doubleClickInterval())
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_trigger_timer.stop()
            self._start_capture_from_tray()

    @Slot(object)
    def _apply_preferences(self, preferences: FloatingPreferences) -> None:
        previous = self.preferences
        self.preferences = preferences
        if self._worker is not None and (
            not preferences.ai_correction_enabled
            or preferences.ai_base_url != previous.ai_base_url
            or preferences.ai_model != previous.ai_model
        ):
            self._worker.cancel()
        self.orb.set_color(preferences.effective_ring_color)
        self.orb.set_logo_path(preferences.effective_logo_path)
        self.panel.set_theme(preferences.result_theme)
        apply_application_theme(preferences.result_theme)

    @Slot()
    def _cancel_active_recognition(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    @Slot()
    def start_capture(self) -> None:
        if not self._can_start_capture():
            return
        self._capture_pending = True
        self.panel.hide()
        self.orb.hide()
        QTimer.singleShot(180, self._show_screen_overlay)

    def _show_screen_overlay(self) -> None:
        if self._shutdown:
            self._capture_pending = False
            return
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            self._capture_pending = False
            self.orb.show()
            if self._try_launch_pending_installer():
                return
            self.panel.show_error("没有找到可截图的屏幕。", self.orb.geometry())
            return
        screenshot = screen.grabWindow(0)
        if screenshot.isNull():
            self._capture_pending = False
            self.orb.show()
            if self._try_launch_pending_installer():
                return
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
        self._last_image = None
        self._last_result = None
        self._last_result_draft = None
        self._last_result_source = None
        self._pending_result = False
        self._pending_error = None
        try:
            image = qimage_to_pil(pixmap.toImage())
        except ValueError as exc:
            self._recognition_failed(str(exc))
            return
        ai_api_key: str | None = None
        if self.preferences.ai_correction_enabled:
            try:
                ai_api_key = self._api_key_store.load()
            except CredentialError:
                ai_api_key = None
        worker = RecognitionWorker(
            self.manager,
            image,
            self.preferences.recognition_mode,
            ai_enabled=self.preferences.ai_correction_enabled,
            ai_api_key=ai_api_key,
            ai_base_url=self.preferences.ai_base_url,
            ai_model=self.preferences.ai_model,
        )
        worker.signals.finished.connect(self._worker_recognition_finished)
        worker.signals.failed.connect(self._worker_recognition_failed)
        self._worker = worker
        self._thread_pool.start(worker)

    @Slot()
    def _capture_cancelled(self) -> None:
        self._capture_pending = False
        self._overlay = None
        self.orb.show()
        self.orb.raise_()
        if self._try_launch_pending_installer():
            return
        if self._last_result is not None and not self._settings_visible:
            self.panel.show_result(
                self._last_result,
                self.orb.geometry(),
                self._last_result_draft,
                self._last_result_source,
            )

    @Slot(object)
    def _recognition_finished(self, result: RecognitionResult) -> None:
        self._worker = None
        self._last_result = result
        self._last_result_draft = result.latex
        self._last_result_source = None
        self._pending_error = None
        self.orb.set_busy(False)
        self.orb.set_result_available(True)
        if self._try_launch_pending_installer():
            return
        if self._settings_visible:
            self._pending_result = True
            return
        self.panel.show_result(result, self.orb.geometry())

    @Slot(object, object)
    def _worker_recognition_finished(
        self,
        worker: RecognitionWorker,
        result: RecognitionResult,
    ) -> None:
        if worker is not self._worker:
            worker.release_resources()
            return
        delivery = worker.result_for_delivery(result)
        worker.release_resources()
        if delivery is None:
            self._recognition_failed("识别任务已取消。")
        else:
            self._recognition_finished(delivery)

    @Slot(str)
    def _recognition_failed(self, message: str) -> None:
        self._worker = None
        self.orb.set_busy(False)
        if self._try_launch_pending_installer():
            return
        if self._settings_visible:
            self._pending_error = message
            return
        self.panel.show_error(message, self.orb.geometry())

    @Slot(object, str)
    def _worker_recognition_failed(
        self,
        worker: RecognitionWorker,
        message: str,
    ) -> None:
        if worker is not self._worker:
            worker.release_resources()
            return
        worker.release_resources()
        self._recognition_failed(message)

    @Slot()
    def _result_consumed(self) -> None:
        self._pending_result = False
        self._last_image = None
        self._last_result = None
        self._last_result_draft = None
        self._last_result_source = None
        self.orb.set_result_available(False)

    @Slot(str)
    def _result_draft_changed(self, latex: str) -> None:
        if self._last_result is not None:
            self._last_result_draft = latex

    @Slot(str)
    def _result_source_changed(self, source: str) -> None:
        if self._last_result is not None:
            self._last_result_source = source


def _refresh_style(widget: QWidget) -> None:
    widgets = (widget, *widget.findChildren(QWidget))
    for item in widgets:
        item.style().unpolish(item)
        item.style().polish(item)
