from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRect, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from formulasnip.domain import RecognitionResult
from formulasnip.exceptions import FormulaSnipError
from formulasnip.ui import floating
from formulasnip.ui import settings as settings_ui
from formulasnip.ui.branding import application_icon, tutorial_formula_image
from formulasnip.ui.floating import (
    FloatingFormulaAssistant,
    FloatingOrb,
    FloatingResultPanel,
)
from formulasnip.ui.settings import (
    DEFAULT_RING_COLOR,
    RING_PRESETS,
    FloatingPreferences,
    SettingsPanel,
    normalize_hex_color,
    read_logo_image,
)
from formulasnip.ui.snip_overlay import OVERLAY_ALPHA, SnipOverlay
from formulasnip.ui.styles import apply_application_theme
from formulasnip.ui.worker import ModelWarmupWorker
from formulasnip.update import ReleaseInfo, UpdateAsset


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _settings(tmp_path: Path) -> QSettings:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)
    settings.clear()
    return settings


class MouseRelease:
    @staticmethod
    def button() -> Qt.MouseButton:
        return Qt.MouseButton.LeftButton

    @staticmethod
    def position() -> QPointF:
        return QPointF(40, 40)


def test_overlay_is_lighter_uses_visible_cursor_and_preserves_cancel_semantics() -> None:
    application = _application()
    screen = application.primaryScreen()
    assert screen is not None
    assert OVERLAY_ALPHA < 100

    screenshot = QPixmap(screen.geometry().size())
    screenshot.fill(Qt.GlobalColor.white)
    closed_overlay = SnipOverlay(screen, screenshot)
    assert closed_overlay.cursor().shape() == Qt.CursorShape.BitmapCursor
    cancellations: list[bool] = []
    closed_overlay.cancelled.connect(lambda: cancellations.append(True))
    closed_overlay.show()
    closed_overlay.close()
    assert cancellations == [True]

    captured_overlay = SnipOverlay(screen, screenshot)
    captured_cancellations: list[bool] = []
    captures: list[QPixmap] = []
    captured_overlay.cancelled.connect(lambda: captured_cancellations.append(True))
    captured_overlay.captured.connect(captures.append)
    captured_overlay.show()
    captured_overlay._start = QPoint(10, 10)
    captured_overlay._end = QPoint(40, 40)
    captured_overlay.mouseReleaseEvent(MouseRelease())  # type: ignore[arg-type]

    assert len(captures) == 1
    assert not captured_cancellations


def test_floating_orb_click_menu_and_busy_state() -> None:
    application = _application()
    orb = FloatingOrb()
    requests: list[bool] = []
    orb.capture_requested.connect(lambda: requests.append(True))
    orb.show()
    application.processEvents()

    assert orb.menu_action_texts() == ["打开设置", "退出软件"]
    popup_position = orb._context_menu_position_below()
    assert popup_position.y() > orb.geometry().bottom()
    screen = application.primaryScreen()
    assert screen is not None
    area = screen.availableGeometry()
    orb.move(area.center().x(), area.bottom() - orb.height() + 1)
    bottom_popup_position = orb._context_menu_position_below()
    assert bottom_popup_position.y() > orb.geometry().bottom()
    assert bottom_popup_position.y() + orb._menu.sizeHint().height() <= area.bottom() + 1
    QTest.mouseClick(orb, Qt.MouseButton.LeftButton, pos=orb.rect().center())
    assert requests == [True]

    orb.set_busy(True)
    QTest.mouseClick(orb, Qt.MouseButton.LeftButton, pos=orb.rect().center())
    assert requests == [True]
    orb.close()


def test_result_panel_has_compact_padded_preview_and_copy_hides_panel() -> None:
    application = _application()
    panel = FloatingResultPanel()
    result = RecognitionResult(r"\frac{x}{y}", "Rapid", 0.25)
    consumed: list[bool] = []
    panel.result_consumed.connect(lambda: consumed.append(True))

    margins = panel.preview_frame.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
        30,
        22,
        30,
        22,
    )
    assert panel.preview_stack.height() == 126
    assert panel.svg_preview.maximumHeight() == 78

    panel.show_result(result, QRect(20, 20, 68, 68))
    assert panel.svg_preview.renderer().isValid()
    panel.copy_latex_button.click()
    assert QApplication.clipboard().text() == result.latex
    assert panel.isHidden()
    assert consumed == [True]

    panel.show_result(result, QRect(20, 20, 68, 68))
    panel.copy_mathml_button.click()
    mime_data = QApplication.clipboard().mimeData()
    assert mime_data.hasFormat("application/mathml+xml")
    assert "<math" in mime_data.text()
    assert panel.isHidden()
    assert consumed == [True, True]
    QApplication.clipboard().clear()
    panel.close()
    application.processEvents()


def test_mathml_conversion_failure_keeps_result_visible(monkeypatch: Any) -> None:
    application = _application()
    panel = FloatingResultPanel()
    panel.show_result(RecognitionResult("x", "Rapid", 0.1), QRect(20, 20, 68, 68))

    def fail(_latex: str) -> str:
        raise FormulaSnipError("无法转换")

    monkeypatch.setattr(floating, "latex_to_mathml", fail)
    panel.copy_mathml_button.click()

    assert panel.isVisible()
    assert "无法转换" in panel.status_label.text()
    panel.close()
    application.processEvents()


def test_result_panel_surfaces_derivative_review_warning() -> None:
    application = _application()
    panel = FloatingResultPanel()
    result = RecognitionResult(
        r"\frac{\partial u}{\partial t}",
        "Paddle",
        0.2,
        strategy="auto-reviewed",
        warnings=(
            "智能模式已用 PP-FormulaNet-S 复核。",
            "Rapid 候选疑似偏导符号与重音字符混淆，请对照原图重点校对。",
        ),
    )

    panel.show_result(result, QRect(20, 20, 68, 68))

    assert "疑似偏导" in panel.quality_label.text()
    assert panel.quality_label.property("warning") is True
    panel.close()
    application.processEvents()


def test_result_panel_rerenders_and_copies_edited_latex(monkeypatch: Any) -> None:
    application = _application()
    panel = FloatingResultPanel()

    original_render = floating.render_formula_svg
    monkeypatch.setattr(
        floating,
        "render_formula_svg",
        lambda latex: (
            (_ for _ in ()).throw(ValueError("bad preview"))
            if latex == "bad"
            else original_render(r"\frac{x}{y}")
        ),
    )
    panel.show_result(RecognitionResult("bad", "Rapid", 0.1), QRect(20, 20, 68, 68))
    assert panel.preview_stack.currentWidget() is panel.preview_message

    panel.latex_view.setPlainText("edited")
    panel._refresh_edited_preview()
    assert panel.preview_stack.currentWidget() is panel.preview_frame
    assert panel.status_label.text() == "预览已更新"
    panel.copy_latex_button.click()
    assert QApplication.clipboard().text() == "edited"
    QApplication.clipboard().clear()
    panel.close()
    application.processEvents()


def test_result_panel_converts_edited_latex_to_mathml(monkeypatch: Any) -> None:
    _application()
    converted: list[str] = []
    monkeypatch.setattr(
        floating,
        "latex_to_mathml",
        lambda latex: converted.append(latex) or "<math><mi>y</mi></math>",
    )
    panel = FloatingResultPanel()
    panel.show_result(RecognitionResult("x", "Rapid", 0.1), QRect(20, 20, 68, 68))
    panel.latex_view.setPlainText("y")

    panel.copy_mathml_button.click()

    assert converted == ["y"]
    assert QApplication.clipboard().text() == "<math><mi>y</mi></math>"
    assert panel.isHidden()
    QApplication.clipboard().clear()


def test_empty_edited_latex_disables_copy_buttons() -> None:
    panel = FloatingResultPanel()
    panel.show_result(RecognitionResult("x", "Rapid", 0.1), QRect(20, 20, 68, 68))

    panel.latex_view.clear()

    assert not panel.copy_latex_button.isEnabled()
    assert not panel.copy_mathml_button.isEnabled()
    panel.close()


def test_model_warmup_worker_continues_after_failure() -> None:
    _application()
    events: list[tuple[str, ...]] = []

    class Manager:
        def warmup(self, key: str) -> None:
            if key == "rapid":
                raise RuntimeError("boom")

    worker = ModelWarmupWorker(Manager(), ("rapid", "paddle"))  # type: ignore[arg-type]
    worker.signals.started.connect(lambda key: events.append(("started", key)))
    worker.signals.succeeded.connect(lambda key: events.append(("succeeded", key)))
    worker.signals.failed.connect(
        lambda key, message: events.append(("failed", key, message))
    )
    worker.signals.finished.connect(lambda: events.append(("finished",)))

    worker.run()

    assert events == [
        ("started", "rapid"),
        ("failed", "rapid", "boom"),
        ("started", "paddle"),
        ("succeeded", "paddle"),
        ("finished",),
    ]


def test_start_model_warmup_is_ordered_idempotent_and_updates_status(
    tmp_path: Path,
) -> None:
    _application()

    class Pool:
        def __init__(self) -> None:
            self.started: list[Any] = []

        def start(self, worker: Any) -> None:
            self.started.append(worker)

    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant.preferences = FloatingPreferences("paddle", "blue", "dark", True)
    pool = Pool()
    assistant._thread_pool = pool  # type: ignore[assignment]

    assistant.start_model_warmup()
    assistant.start_model_warmup()

    assert len(pool.started) == 1
    worker = pool.started[0]
    assert worker.backend_keys == ("paddle",)
    assert assistant._warmup_worker is worker
    worker.signals.started.emit("paddle")
    assert assistant.settings_panel.engine_status_labels["paddle"].text() == "正在初始化"
    worker.signals.succeeded.emit("paddle")
    assert assistant.settings_panel.engine_status_labels["paddle"].text() == "已初始化"
    worker.signals.failed.emit("rapid", "offline")
    assert "初始化失败" in assistant.settings_panel.engine_status_labels["rapid"].text()
    worker.signals.finished.emit()
    assert assistant._warmup_worker is None
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_settings_tutorial_has_four_steps_and_final_start(tmp_path: Path) -> None:
    application = _application()
    panel = SettingsPanel(_settings(tmp_path), FloatingPreferences())
    starts: list[bool] = []
    panel.start_requested.connect(lambda: starts.append(True))
    panel.show()
    panel.show_tutorial()
    application.processEvents()

    assert panel.tutorial_stack.count() == 4
    assert panel.tutorial_stack.currentIndex() == 0
    assert [item.step_index for item in panel.tutorial_illustrations] == [0, 1, 2, 3]
    assert all(item.accessibleDescription() for item in panel.tutorial_illustrations)
    panel.resize(panel.minimumSize())
    for theme in ("dark", "light"):
        apply_application_theme(theme)
        for step_index, illustration in enumerate(panel.tutorial_illustrations):
            panel._set_tutorial_step(step_index)
            application.processEvents()
            preview = illustration.grab()
            assert not preview.isNull()
            assert preview.width() >= 220
            assert preview.height() >= 220
    assert panel.tutorial_stack.currentIndex() == 3
    assert panel.tutorial_start_button.isVisible()
    panel.tutorial_start_button.click()
    assert starts == [True]
    panel.hide()
    apply_application_theme("dark")


def test_auto_startup_only_warms_rapid_and_shutdown_closes_manager(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    started: list[Any] = []
    closed: list[bool] = []
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    monkeypatch.setattr(assistant._thread_pool, "start", started.append)
    monkeypatch.setattr(assistant.manager, "close", lambda: closed.append(True))
    assistant.start_model_warmup()
    assert started[0].backend_keys == ("rapid",)
    assistant.shutdown()
    assert closed == [True]


def test_v2_settings_center_matches_reference_layout_and_navigation(tmp_path: Path) -> None:
    _application()
    panel = SettingsPanel(_settings(tmp_path), FloatingPreferences())

    assert panel.size().width() == 1180
    assert panel.size().height() == 760
    assert panel.minimumWidth() == 1040
    assert panel.minimumHeight() == 680
    assert panel.pages.count() == 4
    assert [button.text().strip() for button, _title in panel._nav_entries] == [
        "常规",
        "识别",
        "悬浮球",
        "使用方法",
    ]
    assert panel.sidebar.width() == 216
    assert panel.header.height() == 64
    assert panel.brand_logo.size().width() == 30
    assert all(button.height() == 38 for button, _title in panel._nav_entries)
    assert panel.theme_toggle_button.size().width() == 34
    assert panel.theme_toggle_button.size().height() == 34
    assert panel.theme_toggle_button.toolTip()
    assert panel.theme_toggle_button.accessibleName() == "切换明暗主题"
    scroll = panel.settings_page.findChild(QScrollArea)
    assert scroll is not None
    body_layout = scroll.widget().layout()
    assert body_layout is not None
    margins = body_layout.contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
        24,
        20,
        24,
        24,
    )
    assert body_layout.spacing() == 12
    assert panel.startup_checkbox.isCheckable()
    assert not application_icon().isNull()
    assert not tutorial_formula_image().isNull()
    assert not panel.windowIcon().isNull()
    assert panel.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
    assert panel.brand_logo.pixmap() is not None
    assert not panel.brand_logo.pixmap().isNull()
    assert panel.brand_edition.isHidden()
    assert panel.update_button is panel.check_update_button
    assert "v0.2.3" in panel.update_version_label.text()
    assert all(
        dot.property("available") == "false"
        for dot in panel.engine_status_dots.values()
    )
    assert all(button.accessibleName() for button in panel.color_buttons.values())
    assert panel.findChild(settings_ui.QWidget, "SettingsCTA") is None
    panel.hide()


def test_header_start_and_github_buttons_emit_and_open_target(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    panel = SettingsPanel(_settings(tmp_path), FloatingPreferences())
    starts: list[bool] = []
    opened: list[str] = []
    panel.start_requested.connect(lambda: starts.append(True))
    monkeypatch.setattr(
        settings_ui.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()) or True,
    )

    assert panel.github_button.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert panel.github_button.text() == "loLollipop/FormulaSnip"
    assert not panel.github_button.icon().isNull()
    assert panel.github_button.iconSize().width() == 16
    assert panel.github_button.toolTip()
    assert panel.github_button.accessibleName()
    panel.start_button.click()
    panel.github_button.click()

    assert starts == [True]
    assert opened == ["https://github.com/loLollipop/FormulaSnip"]
    panel.hide()


def test_appearance_page_uses_reference_stage_and_swatch_sizes(tmp_path: Path) -> None:
    _application()
    panel = SettingsPanel(_settings(tmp_path), FloatingPreferences())

    stage = panel.appearance_page.findChild(settings_ui.QWidget, "OrbPreviewStage")
    assert stage is not None
    assert stage.height() == 258
    assert all(button.size().width() == 34 for button in panel.color_buttons.values())
    assert all(button.size().height() == 34 for button in panel.color_buttons.values())
    assert panel.custom_color_button.size().width() == 34
    assert panel.ring_hex_label.text() == DEFAULT_RING_COLOR
    assert panel.logo_status_label.text() == "默认 Logo"
    assert "12 MB" in panel.upload_logo_button.toolTip()
    panel.hide()


def test_mode_cards_replace_visible_combo_and_persist_selection(tmp_path: Path) -> None:
    _application()
    settings = _settings(tmp_path)
    panel = SettingsPanel(settings, FloatingPreferences())
    changed: list[FloatingPreferences] = []
    panel.preferences_changed.connect(changed.append)

    assert panel.mode_combo.isHidden()
    assert set(panel.mode_cards) == {"auto", "rapid", "paddle"}
    panel.mode_cards["rapid"].click()

    assert panel.mode_combo.currentData() == "rapid"
    assert panel.mode_cards["rapid"].isChecked()
    assert settings.value("recognition/mode") == "rapid"
    assert changed[-1].recognition_mode == "rapid"
    assert panel.overview_mode_name.text() == "快速"
    assert panel.overview_mode_tag.text() == "轻量"
    assert panel.mode_summary_label.text() == "只运行 RapidLaTeXOCR"
    assert panel.mode_summary_label.isHidden()
    assert panel.recognition_page.findChild(
        settings_ui.QWidget, "RecognitionTriggerCard"
    ) is None
    panel.hide()


def test_tutorial_progress_items_jump_between_steps(tmp_path: Path) -> None:
    _application()
    panel = SettingsPanel(_settings(tmp_path), FloatingPreferences())

    panel.show_tutorial()
    panel.tutorial_step_buttons[2].click()

    assert panel.tutorial_stack.currentIndex() == 2
    assert panel.tutorial_step_buttons[0].property("stepState") == "complete"
    assert panel.tutorial_step_buttons[2].property("stepState") == "current"
    assert panel.tutorial_back_button.text() == "上一步"
    panel.hide()


def test_legacy_preferences_migrate_to_ring_and_global_theme(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.setValue("appearance/orb_color", "green")
    settings.setValue("appearance/result_theme", "light")

    preferences = FloatingPreferences.load(settings)

    assert preferences.effective_ring_color == RING_PRESETS["green"]
    assert preferences.result_theme == "light"
    preferences.save(settings)
    assert settings.value("appearance/ring_color") == RING_PRESETS["green"]
    assert settings.value("appearance/theme") == "light"


def test_unavailable_paddle_mode_falls_back_and_cannot_be_selected(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(
        settings_ui,
        "backend_summaries",
        lambda: (("rapid", "Rapid", True), ("paddle", "Paddle", False)),
    )
    settings = _settings(tmp_path)
    settings.setValue("recognition/mode", "paddle")

    preferences = FloatingPreferences.load(settings)
    panel = SettingsPanel(settings, preferences)
    paddle_index = panel.mode_combo.findData("paddle")
    paddle_item = panel.mode_combo.model().item(paddle_index)

    assert preferences.recognition_mode == "auto"
    assert panel.mode_combo.currentData() == "auto"
    assert paddle_item is not None
    assert not paddle_item.isEnabled()
    assert not panel.mode_cards["paddle"].isEnabled()
    panel.close()


def test_ring_color_validation_is_strict_and_canonical() -> None:
    assert normalize_hex_color("#a1b2c3") == "#A1B2C3"
    assert normalize_hex_color("red") == DEFAULT_RING_COLOR
    assert normalize_hex_color("#abcd") == DEFAULT_RING_COLOR
    assert normalize_hex_color(None) == DEFAULT_RING_COLOR


def test_logo_decode_fallback_and_floating_orb_application(tmp_path: Path) -> None:
    _application()
    valid_path = tmp_path / "mark.png"
    image = QImage(64, 48, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ea580c"))
    assert image.save(str(valid_path), "PNG")
    corrupt_path = tmp_path / "broken.png"
    corrupt_path.write_bytes(b"not an image")
    oversized_path = tmp_path / "wide.png"
    oversized = QImage(4097, 2, QImage.Format.Format_RGB32)
    oversized.fill(QColor("white"))
    assert oversized.save(str(oversized_path), "PNG")

    assert read_logo_image(str(valid_path)) is not None
    assert read_logo_image(str(corrupt_path)) is None
    assert read_logo_image(str(oversized_path)) is None

    orb = FloatingOrb("#12ABEF", str(valid_path))
    assert orb.ring_color == "#12ABEF"
    assert orb.logo_path == str(valid_path)
    orb.set_logo_path(str(corrupt_path))
    assert orb.logo_path == ""
    orb.close()


def test_logo_picker_cancel_preserves_existing_value(tmp_path: Path, monkeypatch: Any) -> None:
    _application()
    valid_path = tmp_path / "mark.png"
    image = QImage(32, 32, QImage.Format.Format_ARGB32)
    image.fill(QColor("#2563eb"))
    assert image.save(str(valid_path), "PNG")
    preferences = FloatingPreferences(logo_path=str(valid_path))
    panel = SettingsPanel(_settings(tmp_path), preferences)
    monkeypatch.setattr(
        settings_ui.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: ("", ""),
    )

    panel.choose_logo()

    assert panel.preferences.logo_path == str(valid_path)
    panel.hide()


def test_theme_toggle_updates_application_result_panel_and_storage(tmp_path: Path) -> None:
    application = _application()
    settings = _settings(tmp_path)
    assistant = FloatingFormulaAssistant(settings=settings)
    assert assistant.preferences.result_theme == "dark"

    assistant.settings_panel.theme_toggle_button.click()

    assert assistant.preferences.result_theme == "light"
    assert assistant.panel.theme_name == "light"
    assert application.property("theme") == "light"
    assert settings.value("appearance/theme") == "light"
    assert "#f6f7f9" in application.styleSheet()
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_settings_close_returns_to_floating_mode(tmp_path: Path) -> None:
    application = _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant.show()
    application.processEvents()
    assert assistant.settings_panel.isVisible()
    assert assistant.orb.isHidden()

    assistant.settings_panel.close()
    application.processEvents()
    assert assistant.settings_panel.isHidden()
    assert assistant.orb.isVisible()
    assistant.orb.close()
    assistant.panel.close()


def test_settings_check_update_button_emits_request(tmp_path: Path) -> None:
    _application()
    panel = SettingsPanel(_settings(tmp_path), FloatingPreferences())
    requests: list[bool] = []
    panel.update_check_requested.connect(lambda: requests.append(True))

    panel.check_update_button.click()

    assert requests == [True]
    assert panel.update_status_label.text() == "稳定通道"
    panel.hide()


def test_manual_request_during_automatic_check_restores_update_button(
    tmp_path: Path,
) -> None:
    _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant._update_check_worker = object()  # type: ignore[assignment]

    assistant.check_for_updates(manual=True)
    assert not assistant.settings_panel.check_update_button.isEnabled()

    assistant._update_not_available(False)
    assert assistant.settings_panel.check_update_button.isEnabled()
    assert assistant.settings_panel.update_status_label.text() == "已是最新版本"


def test_update_waits_for_active_recognition_before_starting_installer(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    installer = tmp_path / "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    installer.write_bytes(b"setup")
    asset = UpdateAsset(
        installer.name,
        "https://example.invalid",
        installer.stat().st_size,
        "0" * 64,
    )
    release = ReleaseInfo("0.3.0", "v0.3.0", "", asset)
    events: list[str] = []
    monkeypatch.setattr(assistant.manager, "close", lambda: events.append("close"))
    monkeypatch.setattr(
        floating,
        "launch_verified_installer",
        lambda *args, **kwargs: events.append("installer") or True,
    )
    monkeypatch.setattr(
        floating.QApplication,
        "quit",
        lambda: events.append("quit"),
    )
    assistant._worker = object()  # type: ignore[assignment]
    assistant._warmup_worker = object()  # type: ignore[assignment]

    assistant._update_downloaded(installer, release)
    assert events == []
    assert assistant._pending_update_install == (installer, release)

    assistant.start_capture()
    assert not assistant._capture_pending

    assistant._worker = None
    assert not assistant._try_launch_pending_installer()
    assert events == []
    assistant._warmup_worker = None
    assert assistant._try_launch_pending_installer()
    assert events == ["close", "installer", "quit"]


def test_startup_settings_and_preferences_are_applied(tmp_path: Path) -> None:
    application = _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant.show()
    application.processEvents()

    assert assistant.settings_panel.isVisible()
    assert assistant.orb.isHidden()
    preferences = FloatingPreferences("rapid", "green", "light", False)
    assistant._apply_preferences(preferences)
    assistant.enter_floating_mode()
    application.processEvents()

    assert assistant.settings_panel.isHidden()
    assert assistant.orb.isVisible()
    assert assistant.orb.color_name == "green"
    assert assistant.panel.theme_name == "light"
    assistant.orb.close()
    assistant.panel.close()


def test_selected_recognition_mode_is_passed_to_worker(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    created: list[tuple[Any, Any, str]] = []

    class Hook:
        def connect(self, _callback: Any) -> None:
            pass

    class Signals:
        finished = Hook()
        failed = Hook()

    class FakeWorker:
        signals = Signals()

        def __init__(self, manager: Any, image: Any, mode: str) -> None:
            created.append((manager, image, mode))

    class Pool:
        started: Any = None

        def start(self, worker: Any) -> None:
            self.started = worker

    monkeypatch.setattr(floating, "RecognitionWorker", FakeWorker)
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant.preferences = FloatingPreferences("paddle", "blue", "dark", True)
    assistant._thread_pool = Pool()  # type: ignore[assignment]
    pixmap = QPixmap(80, 40)
    pixmap.fill(Qt.GlobalColor.white)

    assistant._captured(pixmap)

    assert created[0][2] == "paddle"
    assistant._worker = None
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_result_waits_while_settings_are_visible(tmp_path: Path) -> None:
    application = _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant.open_settings()
    result = RecognitionResult("x+y", "Rapid", 0.1)

    assistant._recognition_finished(result)
    assert assistant._pending_result is True
    assert assistant.panel.isHidden()

    assistant.enter_floating_mode()
    application.processEvents()
    assert assistant.panel.isVisible()
    assistant.panel.close()
    assistant.orb.close()
    assistant.settings_panel.hide()


def test_floating_controller_blocks_duplicate_capture_requests(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    scheduled: list[Any] = []

    class Timer:
        @staticmethod
        def singleShot(_milliseconds: int, callback: Any) -> None:  # noqa: N802
            scheduled.append(callback)

    monkeypatch.setattr(floating, "QTimer", Timer)
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))

    assistant.start_capture()
    assistant.start_capture()
    assert assistant._capture_pending is True
    assert len(scheduled) == 1

    assistant._capture_cancelled()
    assert assistant._capture_pending is False
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_cancelled_recapture_restores_unconsumed_result(tmp_path: Path) -> None:
    application = _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    result = RecognitionResult("x+y", "Rapid", 0.1)
    assistant._last_result = result
    assistant.orb.set_result_available(True)
    assistant.panel.show_result(result, assistant.orb.geometry())
    assistant.panel.hide()

    assistant._capture_cancelled()
    application.processEvents()

    assert assistant.panel.isVisible()
    assert assistant._last_result is result
    assert assistant.orb.has_result is True
    assistant.panel.close()
    assistant.orb.close()
    assistant.settings_panel.hide()


def test_settings_round_trip_preserves_edited_result(tmp_path: Path) -> None:
    application = _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant._recognition_finished(RecognitionResult("x", "Rapid", 0.1))
    assistant.panel.latex_view.setPlainText("edited-y")

    assistant.open_settings()
    assistant.enter_floating_mode()
    application.processEvents()

    assert assistant.panel.latex_view.toPlainText() == "edited-y"
    assistant.panel.copy_latex_button.click()
    assert QApplication.clipboard().text() == "edited-y"
    QApplication.clipboard().clear()
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_cancelled_recapture_preserves_edited_result_and_mathml(
    tmp_path: Path, monkeypatch: Any
) -> None:
    application = _application()
    scheduled: list[Any] = []
    monkeypatch.setattr(
        floating.QTimer,
        "singleShot",
        lambda _milliseconds, callback: scheduled.append(callback),
    )
    converted: list[str] = []
    monkeypatch.setattr(
        floating,
        "latex_to_mathml",
        lambda latex: converted.append(latex) or "<math><mi>z</mi></math>",
    )
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant._recognition_finished(RecognitionResult("x", "Rapid", 0.1))
    assistant.panel.latex_view.setPlainText("edited-z")

    assistant.start_capture()
    assert len(scheduled) == 1
    assistant._capture_cancelled()
    application.processEvents()

    assert assistant.panel.latex_view.toPlainText() == "edited-z"
    assistant.panel.copy_mathml_button.click()
    assert converted == ["edited-z"]
    assert QApplication.clipboard().text() == "<math><mi>z</mi></math>"
    QApplication.clipboard().clear()
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_copied_result_never_returns_after_later_capture_cancel(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    scheduled: list[Any] = []

    class Timer:
        @staticmethod
        def singleShot(_milliseconds: int, callback: Any) -> None:  # noqa: N802
            scheduled.append(callback)

    monkeypatch.setattr(floating, "QTimer", Timer)
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    result = RecognitionResult("x+y", "Rapid", 0.1)
    assistant._last_result = result
    assistant.orb.set_result_available(True)
    assistant.panel.show_result(result, assistant.orb.geometry())

    assistant.panel.copy_latex_button.click()
    assert assistant._last_result is None
    assert assistant.orb.has_result is False
    assert assistant.panel.isHidden()

    assistant.start_capture()
    assert len(scheduled) == 1
    assistant._capture_cancelled()
    assert assistant.panel.isHidden()
    assistant.orb.close()
    assistant.settings_panel.hide()


def test_closed_result_never_returns_after_later_capture_cancel(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    monkeypatch.setattr(floating.QTimer, "singleShot", lambda *_args: None)
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    result = RecognitionResult("x+y", "Rapid", 0.1)
    assistant._last_result = result
    assistant.orb.set_result_available(True)
    assistant.panel.show_result(result, assistant.orb.geometry())

    assistant.panel.close()
    assert assistant._last_result is None
    assert assistant.orb.has_result is False

    assistant.start_capture()
    assistant._capture_cancelled()
    assert assistant.panel.isHidden()
    assistant.orb.close()
    assistant.settings_panel.hide()
