from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRect, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from formulasnip.domain import RecognitionResult
from formulasnip.exceptions import FormulaSnipError
from formulasnip.ui import floating
from formulasnip.ui import settings as settings_ui
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
    for _ in range(3):
        panel.next_tutorial_step()
    assert panel.tutorial_stack.currentIndex() == 3
    assert panel.tutorial_start_button.isVisible()
    panel.tutorial_start_button.click()
    assert starts == [True]
    panel.hide()


def test_v4_settings_center_has_minimal_navigation_and_desktop_sizing(tmp_path: Path) -> None:
    _application()
    panel = SettingsPanel(_settings(tmp_path), FloatingPreferences())

    assert panel.size().width() == 1100
    assert panel.size().height() == 700
    assert panel.minimumWidth() == 960
    assert panel.minimumHeight() == 620
    assert panel.pages.count() == 4
    assert [button.text().strip() for button, _title in panel._nav_entries] == [
        "常规",
        "识别",
        "悬浮球",
        "使用方法",
    ]
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
    assert "#f3f6fb" in application.styleSheet()
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
