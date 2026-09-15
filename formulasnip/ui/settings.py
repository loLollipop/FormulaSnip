from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QColor, QImage, QImageReader, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFileDialog,
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
MAX_LOGO_BYTES = 12 * 1024 * 1024
MAX_LOGO_SIDE = 4096
MAX_LOGO_PIXELS = 16_000_000
LOGO_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def normalize_hex_color(value: object, default: str = DEFAULT_RING_COLOR) -> str:
    """Return a canonical #RRGGBB color or the supplied safe default."""
    if isinstance(value, str):
        candidate = value.strip()
        color = QColor(candidate)
        if len(candidate) == 7 and candidate.startswith("#") and color.isValid():
            return color.name(QColor.NameFormat.HexRgb).upper()
    return default


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
class SettingsPanel(QWidget):
    start_requested = Signal()
    preferences_changed = Signal(object)

    _TUTORIAL_STEPS = (
        ("1  点击悬浮球", "左键点击，开始截图。"),
        ("2  框选公式", "拖动鼠标框住公式。"),
        ("3  核对结果", "确认电子公式是否正确。"),
        ("4  复制", "选择 LaTeX 或 MathML。"),
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
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.resize(1100, 700)
        self.setMinimumSize(960, 620)
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

        sidebar = self._build_sidebar()
        outer.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_header())

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
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(20, 24, 20, 24)
        layout.setSpacing(6)

        brand_row = QHBoxLayout()
        brand_mark = QLabel("fx")
        brand_mark.setObjectName("BrandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setFixedSize(38, 38)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        title = QLabel("FormulaSnip")
        title.setObjectName("BrandTitle")
        brand_text.addWidget(title)
        brand_row.addWidget(brand_mark)
        brand_row.addSpacing(8)
        brand_row.addLayout(brand_text)
        layout.addLayout(brand_row)
        layout.addSpacing(24)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self._nav_entries: list[tuple[QPushButton, str]] = []
        for label, title in (
            ("常规", "常规"),
            ("识别", "识别"),
            ("悬浮球", "悬浮球"),
            ("使用方法", "使用方法"),
        ):
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setMinimumHeight(44)
            self.nav_group.addButton(button)
            self._nav_entries.append((button, title))
            layout.addWidget(button)
        layout.addStretch(1)
        return sidebar

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("SettingsHeader")
        header.setFixedHeight(76)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(32, 14, 32, 14)
        self.page_title = QLabel()
        self.page_title.setObjectName("PageTitle")
        self.theme_toggle_button = QPushButton()
        self.theme_toggle_button.setMinimumSize(112, 40)
        self.theme_toggle_button.clicked.connect(self.toggle_theme)
        layout.addWidget(self.page_title)
        layout.addStretch(1)
        layout.addWidget(self.theme_toggle_button)
        return header

    def _page_shell(self) -> tuple[QWidget, QVBoxLayout]:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(32, 28, 32, 30)
        layout.setSpacing(16)
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
        general = _card("启动")
        general_layout = general.layout()
        assert general_layout is not None
        self.startup_checkbox = QPushButton()
        self.startup_checkbox.setObjectName("ToggleButton")
        self.startup_checkbox.setCheckable(True)
        self.startup_checkbox.setMinimumHeight(38)
        self.startup_checkbox.toggled.connect(self._startup_toggle_changed)
        general_layout.addWidget(self.startup_checkbox)
        layout.addWidget(general)

        self.start_button = QPushButton("进入悬浮模式")
        self.start_button.setObjectName("SettingsPrimary")
        self.start_button.setMinimumSize(156, 44)
        self.start_button.clicked.connect(self.start_requested.emit)
        layout.addWidget(self.start_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return page

    def _build_recognition_page(self) -> QWidget:
        page, layout = self._page_shell()
        card = _card("识别模式")
        card_layout = card.layout()
        assert card_layout is not None
        self.mode_combo = QComboBox()
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
        self.mode_combo.setMinimumHeight(42)
        self.mode_combo.currentIndexChanged.connect(self._controls_changed)
        card_layout.addWidget(self.mode_combo)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_appearance_page(self) -> QWidget:
        page, layout = self._page_shell()
        row = QHBoxLayout()
        row.setSpacing(18)
        preview_card = _card("预览")
        preview_layout = preview_card.layout()
        assert preview_layout is not None
        stage = QWidget()
        stage.setObjectName("OrbPreviewStage")
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(36, 26, 36, 26)
        self.orb_preview = OrbAppearancePreview()
        stage_layout.addWidget(self.orb_preview, 0, Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(stage)
        row.addWidget(preview_card, 4)

        controls = _card("外观")
        controls_layout = controls.layout()
        assert controls_layout is not None
        controls_layout.addWidget(_field_label("圆环颜色"))
        swatches = QHBoxLayout()
        swatches.setSpacing(8)
        self.color_group = QButtonGroup(self)
        self.color_group.setExclusive(True)
        self.color_buttons: dict[str, QPushButton] = {}
        for name, color in RING_PRESETS.items():
            button = QPushButton()
            button.setObjectName("SwatchButton")
            button.setCheckable(True)
            button.setFixedSize(42, 42)
            button.setProperty("ringColor", color)
            button.setToolTip(color)
            button.setStyleSheet(f"QPushButton {{ background: {color}; }}")
            self.color_group.addButton(button)
            self.color_buttons[name] = button
            swatches.addWidget(button)
        swatches.addStretch(1)
        controls_layout.addLayout(swatches)
        self.custom_color_button = QPushButton("选择颜色…")
        self.custom_color_button.clicked.connect(self.choose_ring_color)
        controls_layout.addWidget(self.custom_color_button)
        controls_layout.addSpacing(8)
        controls_layout.addWidget(_field_label("中心 Logo"))
        logo_row = QHBoxLayout()
        self.upload_logo_button = QPushButton("上传图片…")
        self.restore_logo_button = QPushButton("恢复默认")
        self.upload_logo_button.clicked.connect(self.choose_logo)
        self.restore_logo_button.clicked.connect(self.restore_default_logo)
        logo_row.addWidget(self.upload_logo_button)
        logo_row.addWidget(self.restore_logo_button)
        controls_layout.addLayout(logo_row)
        self.logo_status_label = QLabel("当前使用默认 fx 标记")
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
        self.tutorial_counter = QLabel()
        self.tutorial_counter.setObjectName("TutorialCounter")
        layout.addWidget(self.tutorial_counter)
        self.tutorial_stack = QStackedWidget()
        self.tutorial_stack.setObjectName("TutorialStack")
        self.tutorial_stack.setMinimumHeight(220)
        for heading, body in self._TUTORIAL_STEPS:
            step = QWidget()
            step_layout = QVBoxLayout(step)
            step_layout.setContentsMargins(28, 26, 28, 26)
            heading_label = QLabel(heading)
            heading_label.setObjectName("SectionTitle")
            body_label = QLabel(body)
            body_label.setObjectName("TutorialBody")
            body_label.setWordWrap(True)
            step_layout.addWidget(heading_label)
            step_layout.addSpacing(12)
            step_layout.addWidget(body_label)
            step_layout.addStretch(1)
            self.tutorial_stack.addWidget(step)
        layout.addWidget(self.tutorial_stack)
        nav = QHBoxLayout()
        self.tutorial_back_button = QPushButton("上一步")
        self.tutorial_next_button = QPushButton("下一步")
        self.tutorial_start_button = QPushButton("开始识别公式")
        self.tutorial_start_button.setObjectName("SettingsPrimary")
        for button in (
            self.tutorial_back_button,
            self.tutorial_next_button,
            self.tutorial_start_button,
        ):
            button.setMinimumHeight(42)
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
        self.startup_checkbox.setChecked(preferences.show_settings_on_startup)
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
        self.page_title.setText(title)

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
        self.startup_checkbox.setText(
            f"启动时显示设置中心：{'开' if checked else '关'}"
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
            self.theme_toggle_button.setText("浅色模式")
            self.theme_toggle_button.setToolTip("当前为深色主题")
        else:
            self.theme_toggle_button.setText("深色模式")
            self.theme_toggle_button.setToolTip("当前为浅色主题")

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
            self.logo_status_label.setText("图片无效、损坏或过大，已安全恢复默认 fx 标记")
        else:
            self._logo_path = str(Path(path).resolve())
            self.logo_status_label.setText(f"自定义 Logo · {Path(path).name}")
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
        if not self._logo_path:
            self.logo_status_label.setText("当前使用默认 fx 标记")

    @Slot()
    def show_tutorial(self) -> None:
        self.tutorial_stack.setCurrentIndex(0)
        self._select_page(3)
        self._update_tutorial_controls()

    @Slot()
    def next_tutorial_step(self) -> None:
        index = min(self.tutorial_stack.count() - 1, self.tutorial_stack.currentIndex() + 1)
        self.tutorial_stack.setCurrentIndex(index)
        self._update_tutorial_controls()

    @Slot()
    def previous_tutorial_step(self) -> None:
        if self.tutorial_stack.currentIndex() == 0:
            self._select_page(0)
            return
        self.tutorial_stack.setCurrentIndex(self.tutorial_stack.currentIndex() - 1)
        self._update_tutorial_controls()

    def show_settings_page(self) -> None:
        self._select_page(0)

    def show_appearance_page(self) -> None:
        self._select_page(2)

    def _update_tutorial_controls(self) -> None:
        index = self.tutorial_stack.currentIndex()
        last = index == self.tutorial_stack.count() - 1
        self.tutorial_counter.setText(f"{index + 1} / {self.tutorial_stack.count()}")
        self.tutorial_back_button.setText("返回" if index == 0 else "上一步")
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
    heading = QLabel(title)
    heading.setObjectName("CardTitle")
    layout.addWidget(heading)
    if description:
        detail = QLabel(description)
        detail.setObjectName("CardDescription")
        detail.setWordWrap(True)
        layout.addWidget(detail)
    return card


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SettingsFieldLabel")
    return label
