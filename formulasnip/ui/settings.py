from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QByteArray,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QIcon,
    QImage,
    QImageReader,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from formulasnip.recognition import backend_summaries
from formulasnip.ui.branding import (
    TUTORIAL_FORMULA_LATEX,
    application_icon,
    application_version,
    tutorial_formula_image,
)
from formulasnip.ui.styles import apply_application_theme

RECOGNITION_MODES = ("auto", "rapid", "paddle")
ORB_COLORS = ("blue", "green", "orange")
RESULT_THEMES = ("dark", "light")
DEFAULT_RING_COLOR = "#5D83F3"
RING_PRESETS = {
    "blue": DEFAULT_RING_COLOR,
    "green": "#35B98A",
    "orange": "#ED7A45",
    "rose": "#E65B7A",
    "cyan": "#28A9C7",
}
RING_PRESET_LABELS = {
    "blue": "靛蓝",
    "green": "翠绿",
    "orange": "橙色",
    "rose": "玫红",
    "cyan": "青色",
}
MAX_LOGO_BYTES = 12 * 1024 * 1024
MAX_LOGO_SIDE = 4096
MAX_LOGO_PIXELS = 16_000_000
LOGO_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
GITHUB_MARK_PATH = (
    "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59"
    ".4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94"
    "-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 "
    "1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64"
    "-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 "
    ".67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 "
    "2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 "
    "3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 "
    "2.2 0 .21.15.46.55.38A7.995 7.995 0 0016 8c0-4.42-3.58-8-8-8z"
)


def normalize_hex_color(value: object, default: str = DEFAULT_RING_COLOR) -> str:
    """Return a canonical #RRGGBB color or the supplied safe default."""
    if isinstance(value, str):
        candidate = value.strip()
        color = QColor(candidate)
        if len(candidate) == 7 and candidate.startswith("#") and color.isValid():
            return color.name(QColor.NameFormat.HexRgb).upper()
    return default


def github_mark_icon(color: str) -> QIcon:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        f'<path fill="{color}" d="{GITHUB_MARK_PATH}"/></svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, 32, 32))
    painter.end()
    return QIcon(pixmap)


def read_logo_image(path: object, target_size: int = 40) -> QImage | None:
    """Safely decode a small logo preview without expanding oversized input."""
    if not isinstance(path, str) or not path.strip():
        return None
    candidate = Path(path).expanduser()
    try:
        if (
            not candidate.is_file()
            or candidate.suffix.lower() not in LOGO_SUFFIXES
            or candidate.stat().st_size > MAX_LOGO_BYTES
        ):
            return None
    except OSError:
        return None

    reader = QImageReader(str(candidate))
    reader.setAutoTransform(True)
    reader.setDecideFormatFromContent(True)
    size = reader.size()
    if not size.isValid():
        return None
    if (
        size.width() > MAX_LOGO_SIDE
        or size.height() > MAX_LOGO_SIDE
        or size.width() * size.height() > MAX_LOGO_PIXELS
    ):
        return None
    scaled = size.scaled(target_size, target_size, Qt.AspectRatioMode.KeepAspectRatio)
    reader.setScaledSize(scaled)
    image = reader.read()
    return None if image.isNull() else image


@dataclass(frozen=True, slots=True)
class FloatingPreferences:
    # The first four fields intentionally retain the V3 positional API.
    recognition_mode: str = "auto"
    orb_color: str = "blue"
    result_theme: str = "dark"
    show_settings_on_startup: bool = True
    ring_color: str | None = None
    logo_path: str = ""

    @property
    def effective_ring_color(self) -> str:
        if self.ring_color is not None:
            return normalize_hex_color(self.ring_color)
        return RING_PRESETS.get(self.orb_color, DEFAULT_RING_COLOR)

    @property
    def effective_logo_path(self) -> str:
        if read_logo_image(self.logo_path) is None:
            return ""
        try:
            return str(Path(self.logo_path).expanduser().resolve())
        except OSError:
            return ""

    @classmethod
    def load(cls, settings: QSettings) -> FloatingPreferences:
        legacy_orb = _choice(settings.value("appearance/orb_color"), ORB_COLORS, "blue")
        legacy_theme = _choice(
            settings.value("appearance/result_theme"), RESULT_THEMES, "dark"
        )
        theme = _choice(settings.value("appearance/theme"), RESULT_THEMES, legacy_theme)
        stored_ring = settings.value("appearance/ring_color")
        ring = (
            normalize_hex_color(stored_ring)
            if isinstance(stored_ring, str)
            else RING_PRESETS[legacy_orb]
        )
        stored_logo = settings.value("appearance/logo_path")
        logo = ""
        if isinstance(stored_logo, str) and read_logo_image(stored_logo) is not None:
            try:
                logo = str(Path(stored_logo).expanduser().resolve())
            except OSError:
                logo = ""
        recognition_mode = _choice(
            settings.value("recognition/mode"), RECOGNITION_MODES, "auto"
        )
        if recognition_mode == "paddle" and not _backend_is_available("paddle"):
            recognition_mode = "auto"
        return cls(
            recognition_mode=recognition_mode,
            orb_color=_preset_name(ring),
            result_theme=theme,
            show_settings_on_startup=_boolean(
                settings.value("window/show_settings_on_startup"), True
            ),
            ring_color=ring,
            logo_path=logo,
        )

    def save(self, settings: QSettings) -> None:
        ring = self.effective_ring_color
        settings.setValue("recognition/mode", self.recognition_mode)
        settings.setValue("appearance/ring_color", ring)
        settings.setValue("appearance/theme", self.result_theme)
        settings.setValue("appearance/logo_path", self.effective_logo_path)
        settings.setValue("window/show_settings_on_startup", self.show_settings_on_startup)
        # Keep the V3 keys synchronized for downgrade and migration compatibility.
        settings.setValue("appearance/orb_color", _preset_name(ring))
        settings.setValue("appearance/result_theme", self.result_theme)
        settings.sync()


def _preset_name(color: str) -> str:
    normalized = normalize_hex_color(color)
    return next((name for name, value in RING_PRESETS.items() if value == normalized), "blue")


def _choice(value: object, choices: tuple[str, ...], default: str) -> str:
    candidate = value if isinstance(value, str) else ""
    return candidate if candidate in choices else default


def _boolean(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


def _backend_is_available(key: str) -> bool:
    return any(
        backend_key == key and available
        for backend_key, _name, available in backend_summaries()
    )


class OrbAppearancePreview(QWidget):
    """Live rendering of the floating orb appearance controls."""

    def __init__(self) -> None:
        super().__init__()
        self._ring_color = DEFAULT_RING_COLOR
        self._logo = QImage()
        self.setFixedSize(104, 104)

    def set_appearance(self, ring_color: str, logo_path: str) -> None:
        self._ring_color = normalize_hex_color(ring_color)
        image = read_logo_image(logo_path, 42)
        self._logo = image if image is not None else QImage()
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        circle = self.rect().adjusted(13, 13, -13, -13)
        painter.setPen(QPen(QColor(self._ring_color), 5))
        painter.setBrush(QColor("#1A2434"))
        painter.drawEllipse(circle)
        if not self._logo.isNull():
            target = self._logo.size().scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio)
            point = circle.center() - QPoint(target.width() // 2, target.height() // 2)
            painter.drawImage(point.x(), point.y(), self._logo)
        else:
            painter.setPen(QColor("#FFFFFF"))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(17)
            painter.setFont(font)
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, "fx")


class TutorialStepIllustration(QWidget):
    """Theme-aware vector diagram for one onboarding step."""

    def __init__(self, step_index: int) -> None:
        super().__init__()
        self.step_index = step_index
        self._formula_image = tutorial_formula_image()
        self.setObjectName("TutorialIllustration")
        self.setMinimumSize(220, 220)
        self.setMaximumWidth(320)
        self.setAccessibleName(f"使用方法第 {step_index + 1} 步图示")
        self.setAccessibleDescription(
            (
                "左键点击桌面悬浮球进入截图模式",
                "拖动十字光标框选单个公式",
                "在结果面板核对电子公式和 LaTeX",
                "选择复制 LaTeX 或 MathML 并粘贴到 Word",
            )[step_index]
        )

    def paintEvent(self, event: object) -> None:  # noqa: N802
        super().paintEvent(event)  # type: ignore[arg-type]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        dark = QApplication.instance() is not None and (
            QApplication.instance().property("theme") == "dark"
        )
        colors = {
            "surface": QColor("#161A21" if dark else "#FFFFFF"),
            "surface_alt": QColor("#1C212A" if dark else "#F4F6F9"),
            "border": QColor("#39414F" if dark else "#C8CFDA"),
            "text": QColor("#E8ECF3" if dark else "#151A21"),
            "muted": QColor("#98A8BF" if dark else "#5F6A79"),
            "accent": QColor("#6E8CF5"),
            "success": QColor("#72DFB5" if dark else "#19704F"),
        }
        area = QRectF(self.rect()).adjusted(18, 18, -18, -18)
        if self.step_index == 0:
            self._draw_click_orb(painter, area, colors)
        elif self.step_index == 1:
            self._draw_selection(painter, area, colors)
        elif self.step_index == 2:
            self._draw_result(painter, area, colors)
        else:
            self._draw_copy_to_word(painter, area, colors)

    @staticmethod
    def _set_font(
        painter: QPainter, size: int, *, bold: bool = False, family: str = ""
    ) -> None:
        font = painter.font()
        font.setPointSize(size)
        font.setBold(bold)
        if family:
            font.setFamily(family)
        painter.setFont(font)

    @classmethod
    def _draw_label(
        cls,
        painter: QPainter,
        rect: QRectF,
        text: str,
        color: QColor,
        *,
        size: int = 9,
        bold: bool = False,
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
        family: str = "",
    ) -> None:
        painter.setPen(color)
        cls._set_font(painter, size, bold=bold, family=family)
        painter.drawText(rect, alignment, text)

    @staticmethod
    def _draw_card(
        painter: QPainter, rect: QRectF, fill: QColor, border: QColor, radius: float = 8
    ) -> None:
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)

    def _draw_formula(self, painter: QPainter, rect: QRectF) -> None:
        if self._formula_image.isNull():
            self._draw_label(
                painter,
                rect,
                "Gaussian integral",
                QColor("#172033"),
                size=10,
                bold=True,
            )
            return
        source_size = self._formula_image.size()
        target_size = source_size.scaled(
            int(rect.width()),
            int(rect.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        target = QRectF(
            rect.center().x() - target_size.width() / 2,
            rect.center().y() - target_size.height() / 2,
            target_size.width(),
            target_size.height(),
        )
        painter.drawImage(target, self._formula_image)

    @classmethod
    def _draw_click_orb(
        cls, painter: QPainter, area: QRectF, colors: dict[str, QColor]
    ) -> None:
        desktop = area.adjusted(4, 7, -4, -7)
        cls._draw_card(painter, desktop, colors["surface"], colors["border"])
        title_bottom = desktop.top() + 26
        painter.setPen(QPen(colors["border"], 1))
        painter.drawLine(
            QPoint(int(desktop.left()), int(title_bottom)),
            QPoint(int(desktop.right()), int(title_bottom)),
        )
        icon = QRectF(desktop.left() + 8, desktop.top() + 6, 14, 14)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colors["accent"])
        painter.drawRoundedRect(icon, 4, 4)
        cls._draw_label(painter, icon, "fx", QColor("#FFFFFF"), size=5, bold=True)
        cls._draw_label(
            painter,
            QRectF(icon.right() + 6, desktop.top() + 4, desktop.width() - 94, 18),
            "论文公式.docx",
            colors["muted"],
            size=7,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        control_right = desktop.right() - 8
        painter.setPen(QPen(colors["muted"], 1))
        painter.drawLine(
            QPoint(int(control_right - 46), int(desktop.top() + 14)),
            QPoint(int(control_right - 38), int(desktop.top() + 14)),
        )
        painter.drawRect(
            QRectF(control_right - 27, desktop.top() + 10, 7, 7)
        )
        painter.drawLine(
            QPoint(int(control_right - 7), int(desktop.top() + 10)),
            QPoint(int(control_right), int(desktop.top() + 17)),
        )
        painter.drawLine(
            QPoint(int(control_right), int(desktop.top() + 10)),
            QPoint(int(control_right - 7), int(desktop.top() + 17)),
        )

        page = QRectF(
            desktop.left() + 14,
            title_bottom + 12,
            desktop.width() - 28,
            desktop.height() - 53,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#F7F9FC"))
        painter.drawRoundedRect(page, 5, 5)
        painter.setPen(QPen(QColor("#D7DFEB"), 2))
        for index, ratio in enumerate((0.74, 0.58, 0.68, 0.42)):
            y = page.top() + 18 + index * 18
            painter.drawLine(
                QPoint(int(page.left() + 12), int(y)),
                QPoint(int(page.left() + 12 + (page.width() - 24) * ratio), int(y)),
            )

        orb_size = 52.0
        orb = QRectF(
            page.right() - orb_size - 12,
            page.bottom() - orb_size - 12,
            orb_size,
            orb_size,
        )
        painter.setPen(QPen(colors["accent"], 4))
        painter.setBrush(QColor("#1A2434"))
        painter.drawEllipse(orb)
        cls._draw_label(painter, orb, "fx", QColor("#FFFFFF"), size=14, bold=True)
        cursor_x = orb.left() - 17
        cursor_y = orb.center().y()
        painter.setPen(QPen(colors["accent"], 2))
        painter.drawLine(
            QPoint(int(cursor_x - 9), int(cursor_y)),
            QPoint(int(cursor_x + 9), int(cursor_y)),
        )
        painter.drawLine(
            QPoint(int(cursor_x), int(cursor_y - 9)),
            QPoint(int(cursor_x), int(cursor_y + 9)),
        )
        label_rect = QRectF(page.left() + 10, page.bottom() - 45, page.width() - 88, 25)
        cls._draw_label(
            painter,
            label_rect,
            "左键点击悬浮球",
            colors["accent"],
            size=9,
            bold=True,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

    def _draw_selection(
        self, painter: QPainter, area: QRectF, colors: dict[str, QColor]
    ) -> None:
        page = area.adjusted(5, 4, -5, -4)
        self._draw_card(painter, page, QColor("#FFFFFF"), QColor("#D7DFEB"))
        painter.setPen(QPen(QColor("#D7DFEB"), 2))
        for index, ratio in enumerate((0.78, 0.61, 0.72, 0.51, 0.67)):
            y = page.top() + 20 + index * 31
            painter.drawLine(
                QPoint(int(page.left() + 14), int(y)),
                QPoint(int(page.left() + 14 + (page.width() - 28) * ratio), int(y)),
            )
        selection = QRectF(
            page.left() + 20,
            page.center().y() - 25,
            page.width() - 40,
            57,
        )
        painter.setPen(QPen(colors["accent"], 2, Qt.PenStyle.DashLine))
        accent_fill = QColor(colors["accent"])
        accent_fill.setAlpha(18)
        painter.setBrush(accent_fill)
        painter.drawRoundedRect(selection, 4, 4)
        self._draw_formula(painter, selection.adjusted(10, 8, -10, -8))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colors["accent"])
        for x, y in (
            (selection.left(), selection.top()),
            (selection.right(), selection.top()),
            (selection.left(), selection.bottom()),
            (selection.right(), selection.bottom()),
        ):
            painter.drawEllipse(QRectF(x - 3, y - 3, 6, 6))
        cursor = selection.bottomRight() + QPoint(13, 13)
        painter.setPen(QPen(colors["accent"], 2))
        painter.drawLine(cursor + QPoint(-10, 0), cursor + QPoint(10, 0))
        painter.drawLine(cursor + QPoint(0, -10), cursor + QPoint(0, 10))
        self._draw_label(
            painter,
            QRectF(page.left() + 12, page.bottom() - 31, page.width() - 24, 20),
            "松开鼠标后自动识别",
            colors["muted"],
            size=8,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

    def _draw_result(
        self, painter: QPainter, area: QRectF, colors: dict[str, QColor]
    ) -> None:
        panel = area.adjusted(3, 6, -3, -6)
        self._draw_card(painter, panel, QColor("#121B2B"), QColor("#34445E"))
        self._draw_label(
            painter,
            QRectF(panel.left() + 13, panel.top() + 7, panel.width() - 26, 22),
            "公式识别结果",
            QColor("#EDF3FB"),
            size=9,
            bold=True,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        preview = QRectF(panel.left() + 13, panel.top() + 35, panel.width() - 26, 70)
        self._draw_card(painter, preview, QColor("#FFFFFF"), QColor("#D7DFEB"), 5)
        self._draw_formula(painter, preview.adjusted(13, 13, -13, -13))
        status = QRectF(panel.left() + 13, preview.bottom() + 7, 72, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#173B36"))
        painter.drawRoundedRect(status, 5, 5)
        self._draw_label(
            painter, status, "✓ 电子公式", QColor("#72DFB5"), size=8, bold=True
        )
        latex = QRectF(panel.left() + 13, status.bottom() + 8, panel.width() - 26, 35)
        self._draw_card(painter, latex, QColor("#09101D"), QColor("#34445E"), 5)
        latex_lines = TUTORIAL_FORMULA_LATEX.replace(
            r"\,\mathrm{d}x = ",
            r"\,\mathrm{d}x" "\n" "= ",
        )
        self._draw_label(
            painter,
            latex.adjusted(9, 2, -7, -2),
            latex_lines,
            QColor("#C9D5E5"),
            size=6,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            family="Consolas",
        )

    def _draw_copy_to_word(
        self, painter: QPainter, area: QRectF, colors: dict[str, QColor]
    ) -> None:
        button_gap = 8.0
        button_width = (area.width() - button_gap) / 2
        for index, text in enumerate(("复制 LaTeX", "复制 MathML")):
            button = QRectF(
                area.left() + index * (button_width + button_gap),
                area.top() + 7,
                button_width,
                34,
            )
            fill = colors["accent"] if index == 0 else colors["surface"]
            text_color = QColor("#FFFFFF") if index == 0 else colors["text"]
            button_border = colors["accent"] if index == 0 else colors["border"]
            self._draw_card(painter, button, fill, button_border, 6)
            self._draw_label(painter, button, text, text_color, size=8, bold=True)

        center_x = area.center().x()
        arrow_top = area.top() + 51
        arrow_bottom = area.top() + 78
        painter.setPen(QPen(colors["accent"], 2))
        painter.drawLine(
            QPoint(int(center_x), int(arrow_top)),
            QPoint(int(center_x), int(arrow_bottom)),
        )
        painter.drawLine(
            QPoint(int(center_x), int(arrow_bottom)),
            QPoint(int(center_x - 5), int(arrow_bottom - 6)),
        )
        painter.drawLine(
            QPoint(int(center_x), int(arrow_bottom)),
            QPoint(int(center_x + 5), int(arrow_bottom - 6)),
        )

        word = QRectF(area.left() + 13, area.top() + 87, area.width() - 26, area.height() - 96)
        self._draw_card(painter, word, colors["surface"], colors["border"])
        icon = QRectF(word.left() + 12, word.top() + 13, 32, 32)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2B579A"))
        painter.drawRoundedRect(icon, 5, 5)
        self._draw_label(painter, icon, "W", QColor("#FFFFFF"), size=13, bold=True)
        self._draw_label(
            painter,
            QRectF(icon.right() + 9, word.top() + 10, word.width() - 62, 35),
            "Word 公式",
            colors["text"],
            size=9,
            bold=True,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        formula = QRectF(word.left() + 12, word.top() + 52, word.width() - 24, 36)
        painter.setPen(QPen(QColor("#D7DFEB"), 1))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(formula, 5, 5)
        self._draw_formula(painter, formula.adjusted(9, 8, -9, -8))
        self._draw_label(
            painter,
            QRectF(word.left() + 12, word.bottom() - 24, word.width() - 24, 17),
            "复制成功后面板自动收起",
            colors["success"],
            size=7,
            bold=True,
        )


class ToggleSwitch(QAbstractButton):
    """Compact, keyboard-accessible switch with an animated thumb."""

    def __init__(self) -> None:
        super().__init__()
        self._position = 0.0
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(44, 24)
        self.setAccessibleName("启动时显示设置中心")
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(44, 24)

    def get_position(self) -> float:
        return self._position

    def set_position(self, value: float) -> None:
        self._position = min(max(value, 0.0), 1.0)
        self.update()

    position = Property(float, get_position, set_position)

    @Slot(bool)
    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = QApplication.instance() is not None and (
            QApplication.instance().property("theme") == "dark"
        )
        accent = QColor("#6E8CF5")
        inactive = QColor("#39414F" if dark else "#C8CFDA")
        track = accent if self.isChecked() else inactive
        if not self.isEnabled():
            track.setAlpha(120)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(1, 1, 42, 22), 11, 11)
        x = 4.0 + self._position * 20.0
        thumb_color = "#FFFFFF" if self.isChecked() or not dark else "#161A21"
        painter.setBrush(QColor(thumb_color))
        painter.drawEllipse(QRectF(x, 4, 16, 16))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(accent, 2))
            painter.drawRoundedRect(QRectF(0.5, 0.5, 43, 23), 12, 12)


class NavigationButton(QPushButton):
    """Sidebar button with a geometric marker and optional trailing hint."""

    def __init__(self, text: str, hint: str = "") -> None:
        super().__init__(text)
        self.marker = QLabel(self)
        self.marker.setObjectName("NavMarker")
        self.marker.setProperty("selected", "false")
        self.marker.setFixedSize(3, 18)
        self.marker.move(0, 10)
        self.marker.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if hint:
            trailing = QLabel(hint, self)
            trailing.setObjectName("NavHint")
            trailing.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            trailing.setGeometry(136, 0, 42, 38)
            trailing.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class ModeCard(QPushButton):
    """A whole-card radio choice that remains accessible from the keyboard."""

    selected = Signal(str)

    def __init__(self, key: str, title: str, tag: str, body: str, meta: str) -> None:
        super().__init__()
        self.mode_key = key
        self.setObjectName("ModeCard")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"{title}识别模式")
        self.setMinimumHeight(84)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(14)
        self.indicator = QLabel()
        self.indicator.setObjectName("ModeIndicator")
        self.indicator.setFixedSize(18, 18)
        self.indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.indicator, 0, Qt.AlignmentFlag.AlignTop)
        copy = QVBoxLayout()
        copy.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(9)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("ModeTitle")
        tag_label = QLabel(tag)
        tag_label.setObjectName("ModeTag")
        title_row.addWidget(self.title_label)
        title_row.addWidget(tag_label)
        title_row.addStretch(1)
        body_label = QLabel(body)
        body_label.setObjectName("ModeBody")
        body_label.setWordWrap(True)
        meta_label = QLabel(meta)
        meta_label.setObjectName("ModeMeta")
        for label in (
            self.indicator,
            self.title_label,
            tag_label,
            body_label,
            meta_label,
        ):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        copy.addLayout(title_row)
        copy.addWidget(body_label)
        layout.addLayout(copy, 1)
        layout.addWidget(meta_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.toggled.connect(self._sync_visual)
        self.clicked.connect(lambda: self.selected.emit(self.mode_key))
        self._sync_visual(False)

    @Slot(bool)
    def _sync_visual(self, checked: bool) -> None:
        value = "true" if checked else "false"
        self.setProperty("selected", value)
        self.indicator.setProperty("selected", value)
        self.indicator.setText("●" if checked else "")
        for widget in (self, self.indicator):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

class SettingsPanel(QWidget):
    start_requested = Signal()
    preferences_changed = Signal(object)
    update_check_requested = Signal()

    _TUTORIAL_STEPS = (
        (
            "点击悬浮球",
            "点击悬浮球开始截图",
            "左键点击桌面上的 fx 悬浮球，屏幕进入框选状态，遮罩下使用高对比十字光标。",
            "截图只覆盖鼠标所在的那块屏幕；按 Esc 可随时取消。",
        ),
        (
            "框选公式",
            "拖动鼠标框住一个公式",
            "拖出矩形框住单个公式即可，不需要贴边精确。松开鼠标后自动开始识别。",
            "一次只识别一个公式，不做正文 OCR、表格或整页版面识别。",
        ),
        (
            "核对结果",
            "核对排版后的电子公式",
            "结果面板紧贴悬浮球展开，用 SVG 矢量排版，放大仍然清晰。"
            "质量规则会提示括号不配对、裸 frac / sqrt 等可疑结果。",
            "语法正确但数学含义错误的结果无法自动发现，仍需人工校对。",
        ),
        (
            "复制",
            "复制 LaTeX 或 MathML",
            "选择 LaTeX 或带 MathML MIME 的 MathML，复制成功后结果面板自动收起。",
            "直接粘贴到 Word、MathType 或其他支持 LaTeX / MathML 的编辑器。",
        ),
    )
    def __init__(self, settings: QSettings, preferences: FloatingPreferences) -> None:
        super().__init__()
        self._settings = settings
        self._preferences = preferences
        self._building = True
        self._ring_color = preferences.effective_ring_color
        self._logo_path = preferences.effective_logo_path
        self.setObjectName("SettingsPanel")
        self.setWindowTitle("FormulaSnip 设置中心")
        self.setWindowIcon(application_icon())
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.resize(1180, 760)
        self.setMinimumSize(1040, 680)
        apply_application_theme(preferences.result_theme)
        self._build_ui()
        self._load_controls(preferences)
        self._building = False

    @property
    def preferences(self) -> FloatingPreferences:
        return self._preferences

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = self._build_sidebar()
        outer.addWidget(self.sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.header = self._build_header()
        content_layout.addWidget(self.header)

        self.pages = QStackedWidget()
        self.pages.setObjectName("SettingsPages")
        self.settings_page = self._build_overview_page()
        self.recognition_page = self._build_recognition_page()
        self.appearance_page = self._build_appearance_page()
        self.tutorial_page = self._build_tutorial_page()
        for page in (
            self.settings_page,
            self.recognition_page,
            self.appearance_page,
            self.tutorial_page,
        ):
            self.pages.addWidget(page)
        content_layout.addWidget(self.pages, 1)
        outer.addWidget(content, 1)

        for index, (button, _title) in enumerate(self._nav_entries):
            button.clicked.connect(lambda _checked=False, target=index: self._select_page(target))
        self._select_page(0)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("SettingsSidebar")
        sidebar.setFixedWidth(216)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 20, 12, 12)
        layout.setSpacing(2)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(8, 0, 8, 20)
        brand_row.setSpacing(10)
        self.brand_logo = QLabel()
        self.brand_logo.setObjectName("BrandLogo")
        self.brand_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_logo.setFixedSize(30, 30)
        self.brand_logo.setPixmap(application_icon().pixmap(QSize(30, 30)))
        self.brand_logo.setAccessibleName("FormulaSnip 应用图标")
        title = QLabel("FormulaSnip")
        title.setObjectName("BrandTitle")
        self.brand_edition = QLabel(f"v{application_version()}", sidebar)
        self.brand_edition.setObjectName("BrandEdition")
        self.brand_edition.hide()
        brand_row.addWidget(self.brand_logo)
        brand_row.addWidget(title)
        brand_row.addStretch(1)
        layout.addLayout(brand_row)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self._nav_entries: list[tuple[NavigationButton, str]] = []
        for label, title, hint in (
            ("常规", "常规", ""),
            ("识别", "识别", ""),
            ("悬浮球", "悬浮球", ""),
            ("使用方法", "使用方法", "4 步"),
        ):
            button = NavigationButton(label, hint)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setFixedHeight(38)
            self.nav_group.addButton(button)
            self._nav_entries.append((button, title))
            layout.addWidget(button)
        layout.addStretch(1)
        self.github_button = QPushButton("loLollipop/FormulaSnip")
        self.github_button.setObjectName("GitHubLink")
        self.github_button.setFixedHeight(36)
        self.github_button.setIcon(
            github_mark_icon(
                "#98A8BF" if self._preferences.result_theme == "dark" else "#5F6A79"
            )
        )
        self.github_button.setIconSize(QSize(16, 16))
        self.github_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.github_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.github_button.setToolTip("打开 FormulaSnip GitHub 仓库")
        self.github_button.setAccessibleName("打开 FormulaSnip GitHub 仓库")
        self.github_button.clicked.connect(self._open_github_repository)
        layout.addWidget(self.github_button)
        return sidebar

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("SettingsHeader")
        header.setFixedHeight(64)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(10)
        self.page_title = QLabel()
        self.page_title.setObjectName("PageTitle")
        self.page_subtitle = QLabel(header)
        self.page_subtitle.setObjectName("PageSubtitle")
        self.page_subtitle.hide()
        self.theme_toggle_button = QPushButton()
        self.theme_toggle_button.setObjectName("ThemeToggleButton")
        self.theme_toggle_button.setFixedSize(34, 34)
        self.theme_toggle_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.theme_toggle_button.setAccessibleName("切换明暗主题")
        self.theme_toggle_button.clicked.connect(self.toggle_theme)
        self.start_button = QPushButton("开始识别")
        self.start_button.setObjectName("SettingsPrimary")
        self.start_button.setFixedHeight(34)
        self.start_button.setMinimumWidth(104)
        self.start_button.clicked.connect(self.start_requested.emit)
        layout.addWidget(self.page_title)
        layout.addStretch(1)
        layout.addWidget(self.theme_toggle_button)
        layout.addWidget(self.start_button)
        return header

    def _page_shell(self) -> tuple[QWidget, QVBoxLayout]:
        body = QWidget()
        body.setObjectName("SettingsPageBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.addWidget(scroll)
        return shell, layout

    def _build_overview_page(self) -> QWidget:
        page, layout = self._page_shell()
        mode_card = _card("")
        mode_card.setObjectName("OverviewModeCard")
        mode_layout = mode_card.layout()
        assert mode_layout is not None
        mode_row = QHBoxLayout()
        mode_copy = QVBoxLayout()
        mode_copy.setSpacing(5)
        mode_copy.addWidget(_muted_text("当前识别模式"))
        mode_title_row = QHBoxLayout()
        mode_title_row.setSpacing(9)
        self.overview_mode_name = QLabel()
        self.overview_mode_name.setObjectName("OverviewModeName")
        self.overview_mode_tag = QLabel()
        self.overview_mode_tag.setObjectName("ModeTag")
        mode_title_row.addWidget(self.overview_mode_name)
        mode_title_row.addWidget(self.overview_mode_tag)
        mode_title_row.addStretch(1)
        mode_copy.addLayout(mode_title_row)
        self.mode_summary_label = _muted_text("")
        self.mode_summary_label.hide()
        change_button = QPushButton("更改")
        change_button.setObjectName("CompactButton")
        change_button.setFixedSize(72, 36)
        change_button.clicked.connect(lambda: self._select_page(1))
        mode_row.addLayout(mode_copy, 1)
        mode_row.addWidget(change_button, 0, Qt.AlignmentFlag.AlignVCenter)
        mode_layout.addLayout(mode_row)
        layout.addWidget(mode_card)

        general = _card("应用与引擎")
        general_layout = general.layout()
        assert general_layout is not None
        startup_row = QWidget()
        startup_row.setObjectName("SettingsRow")
        startup_layout = QHBoxLayout(startup_row)
        startup_layout.setContentsMargins(0, 6, 0, 6)
        startup_copy = QVBoxLayout()
        startup_copy.setSpacing(0)
        startup_copy.addWidget(_row_title("启动时显示设置中心"))
        self.startup_checkbox = ToggleSwitch()
        self.startup_checkbox.toggled.connect(self._startup_toggle_changed)
        startup_layout.addLayout(startup_copy, 1)
        startup_layout.addWidget(self.startup_checkbox)
        general_layout.addWidget(startup_row)
        general_layout.addWidget(_divider())

        update_row = QWidget()
        update_row.setObjectName("SettingsRow")
        update_layout = QHBoxLayout(update_row)
        update_layout.setContentsMargins(0, 6, 0, 6)
        update_copy = QVBoxLayout()
        update_copy.setSpacing(3)
        self.update_version_label = _row_title(
            f"当前版本 v{application_version()}"
        )
        update_copy.addWidget(self.update_version_label)
        self.update_status_label = _muted_text("稳定通道")
        update_copy.addWidget(self.update_status_label)
        self.check_update_button = QPushButton("检查更新")
        self.update_button = self.check_update_button
        self.check_update_button.setObjectName("CompactButton")
        self.check_update_button.setFixedSize(96, 36)
        self.check_update_button.clicked.connect(self.update_check_requested.emit)
        update_layout.addLayout(update_copy, 1)
        update_layout.addWidget(self.check_update_button)
        general_layout.addWidget(update_row)
        general_layout.addWidget(_divider())

        summaries = backend_summaries()
        for index, (key, name, available) in enumerate(summaries):
            row = QWidget()
            row.setObjectName("EngineRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 5, 0, 5)
            row_layout.setSpacing(12)
            badge = QLabel("R" if key == "rapid" else "PP")
            badge.setObjectName("EngineBadge")
            badge.setFixedSize(30, 30)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot = QLabel()
            dot.setObjectName("EngineDot")
            dot.setProperty("available", "true" if available else "false")
            dot.setFixedSize(6, 6)
            copy = QVBoxLayout()
            copy.setSpacing(0)
            copy.addWidget(_row_title(name))
            if key == "rapid":
                detail = "170.7 MiB · 1–2 s"
            elif available:
                detail = "227.4 MiB · 0.7 s"
            else:
                detail = "安装缺失 · 请重新运行 uv sync"
            row.setToolTip(detail)
            status = QLabel("已就绪" if available else "安装缺失")
            status.setObjectName("EngineStatus")
            status.setProperty("available", "true" if available else "false")
            row_layout.addWidget(badge)
            row_layout.addLayout(copy, 1)
            row_layout.addWidget(status)
            row_layout.addWidget(dot)
            general_layout.addWidget(row)
            if index < len(summaries) - 1:
                general_layout.addWidget(_divider())
        layout.addWidget(general)
        layout.addStretch(1)
        return page

    def _build_recognition_page(self) -> QWidget:
        page, layout = self._page_shell()
        self.mode_combo = QComboBox()
        self.mode_combo.setVisible(False)
        paddle_available = _backend_is_available("paddle")
        self.mode_combo.addItem("智能（推荐）", "auto")
        self.mode_combo.addItem("快速", "rapid")
        paddle_label = "精确"
        if not paddle_available:
            paddle_label += "（未安装）"
        self.mode_combo.addItem(paddle_label, "paddle")
        if not paddle_available:
            paddle_item = self.mode_combo.model().item(self.mode_combo.count() - 1)
            if paddle_item is not None:
                paddle_item.setEnabled(False)
        self.mode_combo.currentIndexChanged.connect(self._mode_combo_changed)
        layout.addWidget(self.mode_combo)

        modes = (
            (
                "auto",
                "智能",
                "推荐",
                "双引擎自动复核",
                "1–2 s",
            ),
            (
                "rapid",
                "快速",
                "轻量",
                "RapidLaTeXOCR",
                "1–2 s",
            ),
            (
                "paddle",
                "精确",
                "已内置" if paddle_available else "安装缺失",
                "PP-FormulaNet-S",
                (
                    "0.7 s"
                    if paddle_available
                    else "未安装"
                ),
            ),
        )
        self.mode_card_group = QButtonGroup(self)
        self.mode_card_group.setExclusive(True)
        self.mode_cards: dict[str, ModeCard] = {}
        for key, title, tag, body, meta in modes:
            mode_card = ModeCard(key, title, tag, body, meta)
            mode_card.setEnabled(key != "paddle" or paddle_available)
            mode_card.selected.connect(self._select_recognition_mode)
            self.mode_card_group.addButton(mode_card)
            self.mode_cards[key] = mode_card
            layout.addWidget(mode_card)

        layout.addStretch(1)
        return page

    def _build_appearance_page(self) -> QWidget:
        page, layout = self._page_shell()
        row = QHBoxLayout()
        row.setSpacing(12)
        preview_card = _card("")
        preview_layout = preview_card.layout()
        assert preview_layout is not None
        stage = QWidget()
        stage.setObjectName("OrbPreviewStage")
        stage.setFixedHeight(258)
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(20, 20, 20, 12)
        self.orb_preview = OrbAppearancePreview()
        stage_layout.addWidget(self.orb_preview, 0, Qt.AlignmentFlag.AlignCenter)
        self.ring_hex_label = QLabel(self._ring_color)
        self.ring_hex_label.setObjectName("RingHexLabel")
        stage_layout.addWidget(
            self.ring_hex_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
        )
        preview_layout.addWidget(stage)
        row.addWidget(preview_card, 5)

        controls = _card("外观")
        controls_layout = controls.layout()
        assert controls_layout is not None
        controls_layout.addWidget(_field_label("圆环颜色"))
        swatches = QHBoxLayout()
        swatches.setSpacing(10)
        self.color_group = QButtonGroup(self)
        self.color_group.setExclusive(True)
        self.color_buttons: dict[str, QPushButton] = {}
        for name, color in RING_PRESETS.items():
            button = QPushButton()
            button.setObjectName("SwatchButton")
            button.setCheckable(True)
            button.setFixedSize(34, 34)
            button.setProperty("ringColor", color)
            button.setToolTip(color)
            button.setAccessibleName(f"圆环颜色：{RING_PRESET_LABELS[name]}（{color}）")
            button.setStyleSheet(f"QPushButton {{ background: {color}; }}")
            self.color_group.addButton(button)
            self.color_buttons[name] = button
            swatches.addWidget(button)
        self.custom_color_button = QPushButton("+")
        self.custom_color_button.setObjectName("CustomColorButton")
        self.custom_color_button.setFixedSize(34, 34)
        self.custom_color_button.setToolTip("从系统颜色盘选择")
        self.custom_color_button.setAccessibleName("从系统颜色盘选择圆环颜色")
        self.custom_color_button.clicked.connect(self.choose_ring_color)
        swatches.addWidget(self.custom_color_button)
        swatches.addStretch(1)
        controls_layout.addLayout(swatches)
        controls_layout.addWidget(_divider())
        controls_layout.addWidget(_field_label("中心 Logo"))
        logo_row = QHBoxLayout()
        self.upload_logo_button = QPushButton("上传图片…")
        self.restore_logo_button = QPushButton("恢复默认")
        self.upload_logo_button.setFixedHeight(36)
        self.restore_logo_button.setFixedHeight(36)
        self.upload_logo_button.clicked.connect(self.choose_logo)
        self.upload_logo_button.setToolTip(
            "PNG / JPG / WebP / BMP，最大 12 MB"
        )
        self.restore_logo_button.clicked.connect(self.restore_default_logo)
        logo_row.addWidget(self.upload_logo_button)
        logo_row.addWidget(self.restore_logo_button)
        controls_layout.addLayout(logo_row)
        self.logo_status_label = QLabel("默认 Logo")
        self.logo_status_label.setObjectName("MutedText")
        self.logo_status_label.setWordWrap(True)
        controls_layout.addWidget(self.logo_status_label)
        row.addWidget(controls, 6)
        layout.addLayout(row)
        layout.addStretch(1)
        self.color_group.buttonClicked.connect(self._preset_color_selected)
        return page

    def _build_tutorial_page(self) -> QWidget:
        page, layout = self._page_shell()
        progress = QHBoxLayout()
        progress.setSpacing(8)
        self.tutorial_step_buttons: list[QPushButton] = []
        for step_index, step_data in enumerate(self._TUTORIAL_STEPS):
            step_button = QPushButton(f"{step_index + 1:02d}  {step_data[0]}")
            step_button.setObjectName("TutorialStepButton")
            step_button.setFixedHeight(38)
            step_button.clicked.connect(
                lambda _checked=False, target=step_index: self._set_tutorial_step(target)
            )
            self.tutorial_step_buttons.append(step_button)
            progress.addWidget(step_button, 1)
        layout.addLayout(progress)

        self.tutorial_stack = QStackedWidget()
        self.tutorial_stack.setObjectName("TutorialStack")
        self.tutorial_stack.setMinimumHeight(300)
        self.tutorial_counters: list[QLabel] = []
        self.tutorial_illustrations: list[TutorialStepIllustration] = []
        for step_index, (_label, heading, body, tip) in enumerate(
            self._TUTORIAL_STEPS
        ):
            step = QWidget()
            step_layout = QHBoxLayout(step)
            step_layout.setContentsMargins(28, 22, 28, 22)
            step_layout.setSpacing(24)
            copy = QVBoxLayout()
            copy.setSpacing(0)
            counter = QLabel(f"步骤 {step_index + 1} / 4")
            counter.setObjectName("TutorialCounter")
            self.tutorial_counters.append(counter)
            heading_label = QLabel(heading)
            heading_label.setObjectName("TutorialHeading")
            body_label = QLabel(body)
            body_label.setObjectName("TutorialBody")
            body_label.setWordWrap(True)
            tip_label = QLabel(tip)
            tip_label.setObjectName("TutorialTip")
            tip_label.setWordWrap(True)
            counter.hide()
            copy.addWidget(heading_label)
            copy.addSpacing(12)
            copy.addWidget(body_label)
            copy.addSpacing(12)
            copy.addWidget(tip_label)
            copy.addStretch(1)
            illustration = TutorialStepIllustration(step_index)
            self.tutorial_illustrations.append(illustration)
            step_layout.addLayout(copy, 3)
            step_layout.addWidget(illustration, 2)
            self.tutorial_stack.addWidget(step)
        self.tutorial_counter = self.tutorial_counters[0]
        layout.addWidget(self.tutorial_stack)
        nav = QHBoxLayout()
        self.tutorial_back_button = QPushButton("上一步")
        self.tutorial_next_button = QPushButton("下一步")
        self.tutorial_next_button.setObjectName("SettingsPrimary")
        self.tutorial_start_button = QPushButton("开始识别公式")
        self.tutorial_start_button.setObjectName("SettingsPrimary")
        for button in (
            self.tutorial_back_button,
            self.tutorial_next_button,
            self.tutorial_start_button,
        ):
            button.setFixedHeight(36)
        nav.addWidget(self.tutorial_back_button)
        nav.addStretch(1)
        nav.addWidget(self.tutorial_next_button)
        nav.addWidget(self.tutorial_start_button)
        layout.addLayout(nav)
        layout.addStretch(1)
        self.tutorial_back_button.clicked.connect(self.previous_tutorial_step)
        self.tutorial_next_button.clicked.connect(self.next_tutorial_step)
        self.tutorial_start_button.clicked.connect(self.start_requested.emit)
        self._update_tutorial_controls()
        return page

    def _load_controls(self, preferences: FloatingPreferences) -> None:
        mode_index = self.mode_combo.findData(preferences.recognition_mode)
        self.mode_combo.setCurrentIndex(max(0, mode_index))
        self._sync_mode_cards()
        self.startup_checkbox.setChecked(preferences.show_settings_on_startup)
        self.startup_checkbox.set_position(
            1.0 if preferences.show_settings_on_startup else 0.0
        )
        self._startup_toggle_changed(self.startup_checkbox.isChecked())
        self._ring_color = preferences.effective_ring_color
        selected = _preset_name(self._ring_color)
        if RING_PRESETS.get(selected) == self._ring_color:
            self.color_buttons[selected].setChecked(True)
        self._logo_path = preferences.effective_logo_path
        self._update_appearance_preview()
        self._update_theme_button()

    def _select_page(self, index: int) -> None:
        bounded = min(max(index, 0), self.pages.count() - 1)
        self.pages.setCurrentIndex(bounded)
        button, title = self._nav_entries[bounded]
        button.setChecked(True)
        for nav_button, _nav_title in self._nav_entries:
            nav_button.marker.setProperty(
                "selected", "true" if nav_button is button else "false"
            )
            nav_button.marker.style().unpolish(nav_button.marker)
            nav_button.marker.style().polish(nav_button.marker)
        self.page_title.setText(title)
        self.page_subtitle.clear()

    @Slot()
    def _open_github_repository(self) -> None:
        QDesktopServices.openUrl(QUrl("https://github.com/loLollipop/FormulaSnip"))

    @Slot(str)
    def _select_recognition_mode(self, mode: str) -> None:
        index = self.mode_combo.findData(mode)
        item = self.mode_combo.model().item(index) if index >= 0 else None
        if index < 0 or (item is not None and not item.isEnabled()):
            self._sync_mode_cards()
            return
        self.mode_combo.setCurrentIndex(index)

    @Slot()
    def _mode_combo_changed(self) -> None:
        self._sync_mode_cards()
        self._controls_changed()

    def _sync_mode_cards(self) -> None:
        selected = str(self.mode_combo.currentData())
        for key, card in self.mode_cards.items():
            card.setChecked(key == selected)
        summaries = {
            "auto": ("智能", "推荐", "Rapid 优先 · 必要时复核"),
            "rapid": ("快速", "轻量", "只运行 RapidLaTeXOCR"),
            "paddle": ("精确", "已内置", "只运行 PP-FormulaNet-S"),
        }
        name, tag, meta = summaries.get(selected, summaries["auto"])
        self.overview_mode_name.setText(name)
        self.overview_mode_tag.setText(tag)
        self.mode_summary_label.setText(meta)

    @Slot()
    def _controls_changed(self) -> None:
        if self._building:
            return
        self._preferences = FloatingPreferences(
            recognition_mode=str(self.mode_combo.currentData()),
            orb_color=_preset_name(self._ring_color),
            result_theme=self._preferences.result_theme,
            show_settings_on_startup=self.startup_checkbox.isChecked(),
            ring_color=self._ring_color,
            logo_path=self._logo_path,
        )
        self._preferences.save(self._settings)
        self.preferences_changed.emit(self._preferences)

    @Slot(bool)
    def _startup_toggle_changed(self, checked: bool) -> None:
        self.startup_checkbox.setAccessibleDescription(
            "已开启" if checked else "已关闭"
        )
        self._controls_changed()

    @Slot()
    def toggle_theme(self) -> None:
        next_theme = "light" if self._preferences.result_theme == "dark" else "dark"
        self._preferences = FloatingPreferences(
            recognition_mode=self._preferences.recognition_mode,
            orb_color=self._preferences.orb_color,
            result_theme=next_theme,
            show_settings_on_startup=self._preferences.show_settings_on_startup,
            ring_color=self._ring_color,
            logo_path=self._logo_path,
        )
        apply_application_theme(next_theme)
        self._update_theme_button()
        if not self._building:
            self._preferences.save(self._settings)
            self.preferences_changed.emit(self._preferences)

    def _update_theme_button(self) -> None:
        if self._preferences.result_theme == "dark":
            self.theme_toggle_button.setText("☀")
            self.theme_toggle_button.setToolTip("切换到浅色主题")
            self.theme_toggle_button.setAccessibleDescription(
                "当前为深色主题，按下切换到浅色主题"
            )
        else:
            self.theme_toggle_button.setText("☾")
            self.theme_toggle_button.setToolTip("切换到深色主题")
            self.theme_toggle_button.setAccessibleDescription(
                "当前为浅色主题，按下切换到深色主题"
            )
        self.github_button.setIcon(
            github_mark_icon(
                "#98A8BF" if self._preferences.result_theme == "dark" else "#5F6A79"
            )
        )

    @Slot()
    def _preset_color_selected(self) -> None:
        checked = self.color_group.checkedButton()
        if checked is None:
            return
        self._ring_color = normalize_hex_color(checked.property("ringColor"))
        self._update_appearance_preview()
        self._controls_changed()

    @Slot()
    def choose_ring_color(self) -> None:
        selected = QColorDialog.getColor(QColor(self._ring_color), self, "选择悬浮球圆环颜色")
        if not selected.isValid():
            return
        self._ring_color = normalize_hex_color(selected.name(QColor.NameFormat.HexRgb))
        matching = _preset_name(self._ring_color)
        if RING_PRESETS.get(matching) == self._ring_color:
            self.color_buttons[matching].setChecked(True)
        else:
            self.color_group.setExclusive(False)
            checked = self.color_group.checkedButton()
            if checked is not None:
                checked.setChecked(False)
            self.color_group.setExclusive(True)
        self._update_appearance_preview()
        self._controls_changed()

    @Slot()
    def choose_logo(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择悬浮球 Logo",
            str(Path(self._logo_path).parent) if self._logo_path else "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not path:
            return
        image = read_logo_image(path)
        if image is None:
            self._logo_path = ""
            self.logo_status_label.setText("已恢复默认 Logo")
        else:
            self._logo_path = str(Path(path).resolve())
            self.logo_status_label.setText(Path(path).name)
        self._update_appearance_preview()
        self._controls_changed()

    @Slot()
    def restore_default_logo(self) -> None:
        if not self._logo_path:
            return
        self._logo_path = ""
        self._update_appearance_preview()
        self._controls_changed()

    def _update_appearance_preview(self) -> None:
        self.orb_preview.set_appearance(self._ring_color, self._logo_path)
        self.ring_hex_label.setText(self._ring_color)
        if not self._logo_path:
            self.logo_status_label.setText("默认 Logo")

    @Slot()
    def show_tutorial(self) -> None:
        self.tutorial_stack.setCurrentIndex(0)
        self._select_page(3)
        self._update_tutorial_controls()

    @Slot()
    def next_tutorial_step(self) -> None:
        index = min(self.tutorial_stack.count() - 1, self.tutorial_stack.currentIndex() + 1)
        self._set_tutorial_step(index)

    @Slot()
    def previous_tutorial_step(self) -> None:
        if self.tutorial_stack.currentIndex() == 0:
            self._select_page(0)
            return
        self._set_tutorial_step(self.tutorial_stack.currentIndex() - 1)

    def _set_tutorial_step(self, index: int) -> None:
        bounded = min(max(index, 0), self.tutorial_stack.count() - 1)
        self.tutorial_stack.setCurrentIndex(bounded)
        self._update_tutorial_controls()

    def show_settings_page(self) -> None:
        self._select_page(0)

    def show_appearance_page(self) -> None:
        self._select_page(2)

    def show_recognition_page(self) -> None:
        self._select_page(1)

    def set_update_status(self, message: str, *, checking: bool = False) -> None:
        self.update_status_label.setText(message)
        self.check_update_button.setEnabled(not checking)

    def _update_tutorial_controls(self) -> None:
        index = self.tutorial_stack.currentIndex()
        last = index == self.tutorial_stack.count() - 1
        self.tutorial_counter = self.tutorial_counters[index]
        for step_index, button in enumerate(self.tutorial_step_buttons):
            state = "current" if step_index == index else (
                "complete" if step_index < index else "pending"
            )
            button.setProperty("stepState", state)
            button.style().unpolish(button)
            button.style().polish(button)
        self.tutorial_back_button.setText("返回常规" if index == 0 else "上一步")
        self.tutorial_next_button.setVisible(not last)
        self.tutorial_start_button.setVisible(last)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.start_requested.emit()
        event.accept()


def _card(title: str, description: str = "") -> QWidget:
    card = QWidget()
    card.setObjectName("SettingsCard")
    card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(10)
    if title:
        heading = QLabel(title)
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
    if description:
        detail = QLabel(description)
        detail.setObjectName("CardDescription")
        detail.setWordWrap(True)
        layout.addWidget(detail)
    return card


def _divider() -> QFrame:
    divider = QFrame()
    divider.setObjectName("CardDivider")
    divider.setFrameShape(QFrame.Shape.HLine)
    return divider


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SettingsFieldLabel")
    return label


def _row_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("RowTitle")
    return label


def _muted_text(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("MutedText")
    return label
