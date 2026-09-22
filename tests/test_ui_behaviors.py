from __future__ import annotations

import gc
import json
import os
import re
import time
import weakref
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRect, QRunnable, QSettings, Qt, QThreadPool
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QSystemTrayIcon

from formulasnip.domain import RecognitionCandidate, RecognitionResult
from formulasnip.exceptions import FormulaSnipError
from formulasnip.ui import floating
from formulasnip.ui import settings as settings_ui
from formulasnip.ui import worker as worker_module
from formulasnip.ui.branding import (
    application_icon,
    application_version,
    tutorial_formula_image,
)
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
from formulasnip.ui.snip_overlay import OVERLAY_ALPHA, OVERLAY_COLOR, SnipOverlay
from formulasnip.ui.styles import application_stylesheet, apply_application_theme
from formulasnip.ui.update_dialog import UpdateDialog
from formulasnip.ui.widgets import FormulaPreviewWidget
from formulasnip.ui.worker import ModelWarmupWorker
from formulasnip.update import MAX_RELEASE_NOTES_LENGTH, ReleaseInfo, UpdateAsset


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _settings(tmp_path: Path) -> QSettings:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)
    settings.clear()
    return settings


def test_latex_editor_rejects_paste_ime_and_programmatic_overflow() -> None:
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QInputMethodEvent

    from formulasnip.core.limits import MAX_LATEX_CHARS
    from formulasnip.ui.latex_editor import LatexEditor

    _application()
    editor = LatexEditor()
    editor.setPlainText("x")
    enormous = "x" * 5_000_000
    editor.setPlainText(enormous)
    mime = QMimeData()
    mime.setText(enormous)
    editor.insertFromMimeData(mime)
    event = QInputMethodEvent()
    event.setCommitString(enormous)
    editor.inputMethodEvent(event)
    editor.insertPlainText(enormous)
    assert editor.toPlainText() == "x"
    editor.setPlainText("x" * MAX_LATEX_CHARS)
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    QTest.keyClicks(editor, "y")
    assert len(editor.toPlainText()) == MAX_LATEX_CHARS
    QTest.keyClick(editor, Qt.Key.Key_Backspace)
    assert len(editor.toPlainText()) == MAX_LATEX_CHARS - 1
    editor.selectAll()
    editor.insertPlainText("z")
    assert editor.toPlainText() == "z"
    editor.close()


def test_multimegabyte_candidates_never_reach_preview_or_mathml(monkeypatch: Any) -> None:
    _application()
    panel = FloatingResultPanel()
    huge = "x" * 5_000_000
    monkeypatch.setattr(panel.formula_preview, "set_formula",
                        lambda *_: pytest.fail("preview called"))
    monkeypatch.setattr(floating, "latex_to_mathml",
                        lambda *_: pytest.fail("MathML called"))
    monkeypatch.setattr(floating, "assess_latex",
                        lambda *_: pytest.fail("quality called"))
    panel.show_result(RecognitionResult(huge, "test", 0), QRect(0, 0, 70, 70))
    assert panel.latex_view.toPlainText() == ""
    panel._render_preview(huge, edited=True)
    panel._result = RecognitionResult("x", "test", 0)
    monkeypatch.setattr(panel.latex_view, "toPlainText", lambda: huge)
    panel._latex_edited()
    panel._copy_mathml()
    assert not panel._preview_timer.isActive()
    panel.close()


@pytest.mark.parametrize("error", [QSettings.Status.AccessError, QSettings.Status.FormatError])
def test_preferences_save_failure_is_visible_without_persisted_signal(
    tmp_path: Path, error: Any
) -> None:
    _application()

    class BrokenSettings(QSettings):
        def status(self):
            return error

    settings = BrokenSettings(str(tmp_path / "broken.ini"), QSettings.Format.IniFormat)
    panel = SettingsPanel(settings, FloatingPreferences())
    spy = QSignalSpy(panel.preferences_changed)
    panel.startup_checkbox.toggle()
    panel.toggle_theme()
    assert spy.count() == 0
    assert "无法保存" in panel.settings_error_label.text()
    with pytest.raises(settings_ui.PreferencesSaveError):
        FloatingPreferences().save(settings)
    panel.close()


def test_corrupt_ini_loads_defaults_without_overwriting(tmp_path: Path) -> None:
    path = tmp_path / "broken.ini"
    original = b"[broken\nrecognition/ai_correction_enabled=true\n"
    path.write_bytes(original)
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    assert FloatingPreferences.load(settings) == FloatingPreferences()
    assert path.read_bytes() == original


def test_corrupt_ini_user_changes_never_overwrite_original(tmp_path: Path) -> None:
    _application()
    path = tmp_path / "broken.ini"
    original = b"[broken\nrecognition/ai_correction_enabled=true\n"
    path.write_bytes(original)
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    preferences = FloatingPreferences.load(settings)
    panel = SettingsPanel(settings, preferences)
    panel.startup_checkbox.toggle()
    panel.toggle_theme()
    assert path.read_bytes() == original
    assert "无法保存" in panel.settings_error_label.text()
    panel.close()


def test_update_throttle_never_overwrites_corrupt_settings(tmp_path: Path) -> None:
    _application()
    path = tmp_path / "broken.ini"
    original = b"[broken\nupdates/last_check_utc=123\n"
    path.write_bytes(original)
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    assistant = FloatingFormulaAssistant(settings=settings)
    assert settings.status() == QSettings.Status.FormatError
    original_backend = assistant.settings_store
    replacements = QSignalSpy(assistant.settings_panel.settings_backend_changed)

    assistant.settings_panel.startup_checkbox.toggle()
    assistant._update_not_available(manual=True)
    assistant._reset_update_throttle_for_retry()

    assert path.read_bytes() == original
    assert settings.status() == QSettings.Status.FormatError
    assert assistant.settings_store is original_backend
    assert assistant.settings_panel._settings is original_backend
    assert replacements.count() == 0
    assistant.shutdown()


def test_runtime_settings_corruption_is_detected_before_any_write(tmp_path: Path) -> None:
    _application()
    path = tmp_path / "preferences.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    FloatingPreferences().save(settings)
    assistant = FloatingFormulaAssistant(settings=settings)
    original = b"[broken\nupdates/last_check_utc=123\n"
    path.write_bytes(original)

    assert not assistant._persist_update_check_time(456)
    assistant.settings_panel.startup_checkbox.toggle()

    assert path.read_bytes() == original
    assert "无法保存" in assistant.settings_panel.settings_error_label.text()
    assert assistant.settings_panel._settings is settings
    assistant.shutdown()


def test_lazy_ini_parse_error_is_never_overwritten(tmp_path: Path) -> None:
    _application()
    path = tmp_path / "preferences.ini"
    original = b"[unused-section]\nINVALID-LINE-WITHOUT-EQUALS\n"
    path.write_bytes(original)
    settings = QSettings(str(path), QSettings.Format.IniFormat)

    assert FloatingPreferences.load(settings) == FloatingPreferences()
    assistant = FloatingFormulaAssistant(settings=settings)
    assert not assistant._persist_update_check_time(123)
    assistant.settings_panel.startup_checkbox.toggle()

    assert path.read_bytes() == original
    assert "无法保存" in assistant.settings_panel.settings_error_label.text()
    assistant.shutdown()


@pytest.mark.parametrize(
    "custom_value",
    (
        "value=first\\\nsecond",
        'value="first\nsecond"',
        "value=left\u0085middle\u2028right\u2029end",
    ),
)
def test_valid_qt_ini_multiline_and_unicode_values_remain_supported(
    tmp_path: Path,
    custom_value: str,
) -> None:
    path = tmp_path / "preferences.ini"
    path.write_text(
        "[updates]\nautomatic=false\n"
        "[appearance] ; comment\ntheme=light\n"
        f"[custom]\n{custom_value}\n",
        encoding="utf-8",
    )
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    preferences = FloatingPreferences.load(settings)

    assert settings.status() == QSettings.Status.NoError
    assert not preferences.auto_check_updates
    assert preferences.result_theme == "light"
    preferences.save(settings)


def test_qt_serialized_escaped_quote_remains_valid_ini(tmp_path: Path) -> None:
    path = tmp_path / "preferences.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    settings.setValue("custom/value", 'double " quote')
    settings.setValue("appearance/theme", "light")
    settings.setValue("updates/automatic", False)
    settings.sync()

    preferences = FloatingPreferences.load(settings)

    assert settings.status() == QSettings.Status.NoError
    assert preferences.result_theme == "light"
    assert not preferences.auto_check_updates
    preferences.save(settings)


def test_qt_format_error_comment_never_flushes_pending_cache(tmp_path: Path) -> None:
    application = _application()
    path = tmp_path / "preferences.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    settings.setValue("appearance/theme", "light")
    settings.sync()
    settings.setValue("pending", "value")
    original = b"[appearance]\ntheme=light\n#not-a-qt-comment\n"
    path.write_bytes(original)

    assert FloatingPreferences.load(settings) == FloatingPreferences()
    assert path.read_bytes() == original
    application.processEvents()
    assert path.read_bytes() == original
    del settings
    gc.collect()
    application.processEvents()
    assert path.read_bytes() == original


def test_healthy_alias_clears_shared_failed_ai_opt_in(tmp_path: Path) -> None:
    _application()
    directory = tmp_path / "settings"
    directory.mkdir()
    path = directory / "preferences.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    original = FloatingPreferences(
        ai_correction_enabled=False,
        ai_base_url="https://gateway.example/v1",
        ai_model="vision-model",
    )
    original.save(settings)
    panel = SettingsPanel(settings, original)
    stale_alias = QSettings(str(path), QSettings.Format.IniFormat)

    backup = tmp_path / "settings-backup"
    directory.rename(backup)
    directory.write_text("temporarily blocked", encoding="utf-8")
    stale_alias.setValue("recognition/ai_correction_enabled", True)
    stale_alias.sync()
    assert stale_alias.status() != QSettings.Status.NoError

    directory.unlink()
    backup.rename(directory)
    assert settings.status() == QSettings.Status.NoError
    panel.toggle_theme()
    stale_alias.sync()

    assert not panel._save_failed
    assert b"ai_correction_enabled=false" in path.read_bytes()
    assert not FloatingPreferences.load(
        QSettings(str(path), QSettings.Format.IniFormat)
    ).ai_correction_enabled
    panel.close()


def test_atomic_commit_has_no_failing_post_commit_sync(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    path = tmp_path / "preferences.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    original = FloatingPreferences(
        ai_correction_enabled=False,
        ai_base_url="https://gateway.example/v1",
        ai_model="vision-model",
    )
    settings = original.save(settings)
    real_replace = settings_ui.os.replace
    committed = False

    def commit_then_block(source: object, target: object) -> None:
        nonlocal committed
        real_replace(source, target)
        if Path(target) == path:
            committed = True

    monkeypatch.setattr(settings_ui.os, "replace", commit_then_block)
    enabled = replace(original, ai_correction_enabled=True)

    saved = enabled.save(settings)

    assert committed
    assert saved.status() == QSettings.Status.NoError
    assert FloatingPreferences.load(saved).ai_correction_enabled


def test_dirty_access_error_backend_is_refused_without_flushing_cache(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "settings"
    directory.mkdir()
    path = directory / "preferences.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    FloatingPreferences(ai_correction_enabled=False).save(settings)

    path.unlink()
    directory.rmdir()
    directory.write_text("temporarily blocked", encoding="utf-8")
    settings.setValue("recognition/ai_correction_enabled", True)
    settings.sync()
    assert settings.status() == QSettings.Status.AccessError

    directory.unlink()
    directory.mkdir()
    safe = b"[recognition]\nai_correction_enabled=false\n"
    path.write_bytes(safe)
    with pytest.raises(settings_ui.PreferencesSaveError):
        settings_ui.write_settings_values(
            settings,
            {"updates/last_check_utc": 123},
        )
    assert path.read_bytes() == safe
    _application().processEvents()
    settings.sync()
    assert path.read_bytes() == safe
    assert not FloatingPreferences.load(
        QSettings(str(path), QSettings.Format.IniFormat)
    ).ai_correction_enabled


def test_read_known_format_error_drains_pending_cache(tmp_path: Path) -> None:
    application = _application()
    path = tmp_path / "preferences.ini"
    original = b"[appearance]\ntheme=light\n#not-a-qt-comment\n"
    path.write_bytes(original)
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    settings.allKeys()
    assert settings.status() == QSettings.Status.FormatError
    settings.setValue("pending", "queued-before-read")

    assert settings_ui.read_settings_value(settings, "updates/last_check_utc") is None
    application.processEvents()
    assert path.read_bytes() == original
    del settings
    gc.collect()
    application.processEvents()
    assert path.read_bytes() == original


def test_failed_protected_move_never_replaces_original(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    path = tmp_path / "preferences.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    FloatingPreferences(result_theme="light").save(settings)
    original = path.read_bytes()
    real_replace = settings_ui.os.replace
    failed = False

    def fail_protected_move(
        source: object,
        target: object,
    ) -> None:
        nonlocal failed
        if not failed and Path(target).suffix == ".protected":
            failed = True
            raise PermissionError("injected protected move failure")
        real_replace(source, target)

    monkeypatch.setattr(settings_ui.os, "replace", fail_protected_move)

    with pytest.raises(settings_ui.PreferencesSaveError):
        FloatingPreferences(result_theme="dark").save(settings)

    assert failed
    assert path.read_bytes() == original
    _application().processEvents()
    assert not FloatingPreferences.load(
        QSettings(str(path), QSettings.Format.IniFormat)
    ).ai_correction_enabled


def test_access_error_load_and_protection_failure_cannot_enable_ai(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    application = _application()
    directory = tmp_path / "settings"
    directory.mkdir()
    path = directory / "preferences.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    original = FloatingPreferences(
        ai_correction_enabled=False,
        ai_base_url="https://gateway.example/v1",
        ai_model="vision-model",
    )
    original.save(settings)

    backup = tmp_path / "settings-backup"
    directory.rename(backup)
    directory.write_text("temporarily blocked", encoding="utf-8")
    settings.setValue("recognition/ai_correction_enabled", True)
    settings.sync()
    assert settings.status() == QSettings.Status.AccessError
    directory.unlink()
    backup.rename(directory)

    real_replace = settings_ui.os.replace
    failed = False

    def fail_protected_move(source: object, target: object) -> None:
        nonlocal failed
        if not failed and Path(target).suffix == ".protected":
            failed = True
            raise PermissionError("injected protected move failure")
        real_replace(source, target)

    monkeypatch.setattr(settings_ui.os, "replace", fail_protected_move)

    assert FloatingPreferences.load(settings) == FloatingPreferences()
    application.processEvents()
    settings.sync()
    del settings
    gc.collect()
    application.processEvents()

    assert failed
    assert not FloatingPreferences.load(
        QSettings(str(path), QSettings.Format.IniFormat)
    ).ai_correction_enabled


def test_healthy_alias_transaction_failure_cannot_flush_stale_ai_opt_in(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    application = _application()
    directory = tmp_path / "settings"
    directory.mkdir()
    path = directory / "preferences.ini"
    healthy = QSettings(str(path), QSettings.Format.IniFormat)
    original_preferences = FloatingPreferences(
        ai_correction_enabled=False,
        ai_base_url="https://gateway.example/v1",
        ai_model="vision-model",
    )
    healthy = original_preferences.save(healthy)
    original = path.read_bytes()
    stale = QSettings(str(path), QSettings.Format.IniFormat)

    backup = tmp_path / "settings-backup"
    directory.rename(backup)
    directory.write_text("temporarily blocked", encoding="utf-8")
    stale.setValue("recognition/ai_correction_enabled", True)
    stale.sync()
    assert stale.status() == QSettings.Status.AccessError
    directory.unlink()
    backup.rename(directory)
    assert healthy.status() == QSettings.Status.NoError

    monkeypatch.setattr(
        settings_ui.tempfile,
        "mkstemp",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError("injected transaction failure")
        ),
    )

    with pytest.raises(settings_ui.PreferencesSaveError):
        FloatingPreferences(result_theme="light").save(healthy)

    application.processEvents()
    stale.sync()
    del stale
    gc.collect()
    application.processEvents()

    recovery_files = list(directory.glob("preferences.ini.recovery*"))
    assert any(candidate.read_bytes() == original for candidate in recovery_files)
    monkeypatch.undo()
    assert not FloatingPreferences.load(
        QSettings(str(path), QSettings.Format.IniFormat)
    ).ai_correction_enabled


def test_access_failure_then_corrupt_recovery_never_flushes_pending_values(
    tmp_path: Path,
) -> None:
    _application()
    directory = tmp_path / "settings"
    directory.mkdir()
    path = directory / "preferences.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    FloatingPreferences().save(settings)
    panel = SettingsPanel(settings, FloatingPreferences())

    path.unlink()
    directory.rmdir()
    directory.write_text("temporarily blocked", encoding="utf-8")
    panel.startup_checkbox.toggle()
    assert "无法保存" in panel.settings_error_label.text()

    directory.unlink()
    directory.mkdir()
    original = b"[unused-section]\nINVALID-LINE-WITHOUT-EQUALS\n"
    path.write_bytes(original)
    panel.toggle_theme()

    assert path.read_bytes() == original
    assert "无法保存" in panel.settings_error_label.text()
    panel.close()


def test_update_throttle_writes_and_clears_healthy_settings(tmp_path: Path) -> None:
    _application()
    settings = _settings(tmp_path)
    assistant = FloatingFormulaAssistant(settings=settings)

    assistant._update_not_available(manual=False)
    assert int(settings.value("updates/last_check_utc")) > 0
    assistant._reset_update_throttle_for_retry()
    assert settings.value("updates/last_check_utc") is None
    assistant.shutdown()


@pytest.mark.parametrize("fmt", ["GIF", "SVG", "PDF"])
def test_disguised_logo_rejected_before_read(tmp_path: Path, monkeypatch: Any, fmt: str) -> None:
    _application()
    path = tmp_path / "伪装.png"
    if fmt == "GIF":
        Image.new("RGB", (4, 4)).save(path, format="GIF")
    else:
        path.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>'
                         if fmt == "SVG" else b"%PDF-1.4\n%%EOF")
    monkeypatch.setattr(settings_ui.QImageReader, "read",
                        lambda *_: pytest.fail("disallowed decoder invoked"))
    assert read_logo_image(str(path)) is None


def test_invalid_logo_import_preserves_previous_selection(tmp_path: Path, monkeypatch: Any) -> None:
    _application()
    valid = tmp_path / "valid.png"
    invalid = tmp_path / "invalid.png"
    Image.new("RGB", (4, 4)).save(valid)
    invalid.write_bytes(b"broken")
    panel = SettingsPanel(_settings(tmp_path), FloatingPreferences(logo_path=str(valid)))
    monkeypatch.setattr(settings_ui.QFileDialog, "getOpenFileName",
                        lambda *_: (str(invalid), ""))
    panel.choose_logo()
    assert panel._logo_path == str(valid.resolve())
    assert panel.preferences.logo_path == str(valid)
    panel.restore_default_logo()
    assert panel.preferences.logo_path == ""
    panel.close()


@pytest.mark.parametrize("error", [OSError, MemoryError, RuntimeError])
def test_capture_conversion_error_cleans_state_and_redacts(
    tmp_path: Path, monkeypatch: Any, caplog: Any, error: Any
) -> None:
    _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    def fail(*_args):
        raise error("SECRET_MARKER C:/private/image.png")
    monkeypatch.setattr(floating, "qimage_to_pil", fail)
    assistant._captured(QPixmap(2, 2))
    assert assistant._worker is None
    assert assistant._pending_recognition_image is None
    assert assistant._last_image is None
    assert not assistant.orb._busy
    assert "SECRET_MARKER" not in caplog.text
    assert "无法处理截图" in (assistant._pending_error or assistant.panel.preview_message.text())
    assistant.shutdown()


def test_preview_warmup_log_redacts_exception(
    tmp_path: Path, monkeypatch: Any, caplog: Any
) -> None:
    _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    def fail():
        raise RuntimeError("SECRET_MARKER C:/private/user")
    monkeypatch.setattr(assistant.panel.formula_preview, "warmup", fail)
    assistant.start_preview_warmup()
    assert "SECRET_MARKER" not in caplog.text
    assert "C:/private" not in caplog.text
    assistant.shutdown()


def test_installer_exception_redacts_log_and_dialog(
    tmp_path: Path, monkeypatch: Any, caplog: Any
) -> None:
    _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    release = _update_release()
    assistant._pending_update_install = (tmp_path / "setup.exe", release)
    dialog = UpdateDialog("0.2.11", release)
    assistant._update_dialog = dialog
    def fail(*_args, **_kwargs):
        raise OSError("SECRET_MARKER C:/private/user")
    monkeypatch.setattr(floating, "launch_verified_installer", fail)
    assert not assistant._try_launch_pending_installer(force=True)
    assert "update-installer-launch-failed" in caplog.text
    assert "SECRET_MARKER" not in caplog.text
    assert "SECRET_MARKER" not in dialog.status_label.text()
    assistant.shutdown()
    dialog.close()


@pytest.mark.parametrize("suffix,format_name", [(".png", "PNG"), (".jpg", "JPEG"),
                                                (".jpeg", "JPEG"), (".webp", "WEBP"),
                                                (".bmp", "BMP")])
def test_allowed_logo_formats_remain_supported(tmp_path: Path, suffix, format_name) -> None:
    _application()
    path = tmp_path / ("公式 logo" + suffix)
    Image.new("RGB", (4, 4)).save(path, format=format_name)
    assert read_logo_image(str(path)) is not None


def test_real_settings_access_error_does_not_raise_on_load(tmp_path: Path) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("keep", encoding="utf-8")
    settings = QSettings(str(parent_file / "settings.ini"), QSettings.Format.IniFormat)
    preferences = FloatingPreferences.load(settings)
    with pytest.raises(settings_ui.PreferencesSaveError):
        preferences.save(settings)
    assert parent_file.read_text(encoding="utf-8") == "keep"


def test_failed_ai_enable_stays_disabled_when_settings_storage_recovers(
    tmp_path: Path,
) -> None:
    _application()
    directory = tmp_path / "settings"
    directory.mkdir()
    path = directory / "preferences.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    original = FloatingPreferences(
        ai_correction_enabled=False,
        ai_base_url="https://gateway.example/v1",
        ai_model="vision-model",
    )
    original.save(settings)
    panel = SettingsPanel(
        settings,
        original,
        api_key_store=FakeApiKeyStore("unit-test-token"),
    )

    path.unlink()
    directory.rmdir()
    directory.write_text("temporarily blocked", encoding="utf-8")
    panel.ai_correction_toggle.setChecked(True)
    panel._save_ai_configuration()

    assert not panel.preferences.ai_correction_enabled
    assert "无法保存" in panel.settings_error_label.text()

    directory.unlink()
    directory.mkdir()
    settings.sync()
    panel.close()
    del panel
    del settings
    gc.collect()
    reloaded = FloatingPreferences.load(
        QSettings(str(path), QSettings.Format.IniFormat)
    )
    assert not reloaded.ai_correction_enabled


def test_lazy_corrupt_ini_cannot_persist_failed_ai_opt_in(tmp_path: Path) -> None:
    _application()
    path = tmp_path / "preferences.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    original_preferences = FloatingPreferences(
        ai_correction_enabled=False,
        ai_base_url="https://gateway.example/v1",
        ai_model="vision-model",
    )
    original_preferences.save(settings)
    panel = SettingsPanel(
        settings,
        original_preferences,
        api_key_store=FakeApiKeyStore("unit-test-token"),
    )
    original = path.read_bytes() + b"\n[unused-section]\nINVALID-LINE-WITHOUT-EQUALS\n"
    path.write_bytes(original)

    panel.ai_correction_toggle.setChecked(True)
    panel._save_ai_configuration()

    assert not panel.preferences.ai_correction_enabled
    assert path.read_bytes() == original
    reloaded = FloatingPreferences.load(
        QSettings(str(path), QSettings.Format.IniFormat)
    )
    assert not reloaded.ai_correction_enabled
    panel.close()


def test_assistant_adopts_recovered_backend_for_update_throttle(tmp_path: Path) -> None:
    _application()
    directory = tmp_path / "settings"
    directory.mkdir()
    path = directory / "preferences.ini"
    original_backend = QSettings(str(path), QSettings.Format.IniFormat)
    FloatingPreferences().save(original_backend)
    assistant = FloatingFormulaAssistant(settings=original_backend)

    path.unlink()
    directory.rmdir()
    directory.write_text("temporarily blocked", encoding="utf-8")
    assistant.settings_panel.startup_checkbox.toggle()
    assert assistant.settings_store is original_backend

    directory.unlink()
    directory.mkdir()
    assistant.settings_panel.auto_update_toggle.toggle()

    recovered_backend = assistant.settings_panel._settings
    assert recovered_backend.status() == QSettings.Status.NoError
    assert recovered_backend is assistant.settings_store
    assert recovered_backend is not original_backend
    assert assistant._persist_update_check_time(123)
    assert int(recovered_backend.value("updates/last_check_utc")) == 123
    assert assistant._persist_update_check_time(None)
    assert recovered_backend.value("updates/last_check_utc") is None
    assistant.shutdown()


def test_panel_recovers_shared_throttle_access_error_on_first_change(
    tmp_path: Path,
) -> None:
    _application()
    directory = tmp_path / "settings"
    directory.mkdir()
    path = directory / "preferences.ini"
    original_backend = QSettings(str(path), QSettings.Format.IniFormat)
    FloatingPreferences().save(original_backend)
    assistant = FloatingFormulaAssistant(settings=original_backend)
    replacements = QSignalSpy(assistant.settings_panel.settings_backend_changed)
    changes = QSignalSpy(assistant.settings_panel.preferences_changed)

    path.unlink()
    directory.rmdir()
    directory.write_text("temporarily blocked", encoding="utf-8")
    assert not assistant._persist_update_check_time(123)
    assert not assistant.settings_panel._save_failed

    directory.unlink()
    directory.mkdir()
    assistant.settings_panel.startup_checkbox.toggle()

    assert replacements.count() == 1
    assert changes.count() == 1
    assert assistant.settings_store is assistant.settings_panel._settings
    assert assistant.settings_store is not original_backend
    assert assistant.settings_store.status() == QSettings.Status.NoError
    assistant.shutdown()


def test_ai_configuration_save_error_does_not_claim_success(tmp_path: Path) -> None:
    _application()
    class BrokenSettings(QSettings):
        def status(self):
            return QSettings.Status.AccessError

    settings = BrokenSettings(str(tmp_path / "failure.ini"), QSettings.Format.IniFormat)
    panel = SettingsPanel(settings, FloatingPreferences(),
                          api_key_store=FakeApiKeyStore("unit-test-token"))
    panel.ai_correction_toggle.setChecked(True)
    panel.ai_base_url_input.setText("https://gateway.example/v1")
    panel.ai_model_combo.addItem("vision-model")
    panel.ai_model_combo.setCurrentIndex(0)
    changes = QSignalSpy(panel.preferences_changed)
    panel._save_ai_configuration()
    assert changes.count() == 0
    assert "无法保存" in panel.ai_connection_status_label.text()
    assert not panel.preferences.ai_correction_enabled
    assert not panel.ai_correction_toggle.isChecked()
    assert not panel.ai_configuration_widget.isVisible()
    panel.close()


def test_mathml_and_mathjax_reject_large_input_before_conversion(monkeypatch: Any) -> None:
    from latex2mathml import converter

    from formulasnip.core.latex import latex_to_mathml
    from formulasnip.core.preview import build_mathjax_html, build_mathjax_update_script

    monkeypatch.setattr(converter, "convert", lambda *_: pytest.fail("conversion reached"))
    huge = "x" * 5_000_000
    with pytest.raises(FormulaSnipError):
        latex_to_mathml(huge)
    for builder in (build_mathjax_html, build_mathjax_update_script):
        with pytest.raises(ValueError):
            builder(huge, 1)


def test_auto_update_toggle_stops_and_restarts_checks(tmp_path: Path, monkeypatch: Any) -> None:
    _application()
    settings = _settings(tmp_path)
    FloatingPreferences(auto_check_updates=False).save(settings)
    assistant = FloatingFormulaAssistant(settings=settings)
    scheduled, started = [], []
    monkeypatch.setattr(floating.QTimer, "singleShot", lambda _ms, fn: scheduled.append(fn))
    monkeypatch.setattr(assistant._thread_pool, "start", started.append)
    assistant.start_update_checks()
    assistant.check_for_updates()
    assert not scheduled and not started
    assistant.settings_panel.auto_update_toggle.setChecked(True)
    assert assistant._update_timer.isActive() and len(scheduled) == 1
    assistant.settings_panel.auto_update_toggle.setChecked(False)
    scheduled[0]()
    assert not assistant._update_timer.isActive() and not started
    assistant.check_for_updates(manual=True)
    assert len(started) == 1
    assistant.shutdown()


def _update_release(notes: str = "") -> ReleaseInfo:
    asset = UpdateAsset(
        "FormulaSnip-v0.3.0-windows-x64-setup.exe",
        "https://example.invalid/setup.exe",
        96 * 1024 * 1024,
        "0" * 64,
    )
    return ReleaseInfo("0.3.0", "v0.3.0", notes, asset)


def test_update_release_notes_are_formatted_and_escaped() -> None:
    application = _application()
    notes = """# 主要更新
- 提升 **复杂公式** 识别精度
- 优化 `MathML` 复制

详情请查看 [发布页](https://example.invalid)。
<script>alert('unsafe')</script>
"""
    dialog = UpdateDialog("0.2.8", _update_release(notes))

    plain_text = dialog.notes.toPlainText()
    rendered_html = dialog.notes.toHtml().casefold()
    assert "主要更新" in plain_text
    assert "提升 复杂公式 识别精度" in plain_text
    assert "发布页" in plain_text
    assert "https://example.invalid" not in plain_text
    assert "<script>" not in rendered_html
    assert dialog.current_version_label.text() == "v0.2.8"
    assert dialog.latest_version_label.text() == "v0.3.0"
    assert dialog.minimumHeight() == 0
    assert dialog.notes.accessibleName() == "更新内容"
    dialog.close()
    application.processEvents()


def test_update_release_notes_are_bounded_and_have_empty_fallback() -> None:
    application = _application()
    long_notes = "A" * MAX_RELEASE_NOTES_LENGTH + "SHOULD_NOT_RENDER"
    dialog = UpdateDialog("0.2.8", _update_release(long_notes))
    assert "SHOULD_NOT_RENDER" not in dialog.notes.toPlainText()
    dialog.close()

    empty_dialog = UpdateDialog("0.2.8", _update_release("   \n"))
    assert empty_dialog.notes.toPlainText().strip() == "本次更新未提供更新说明。"
    empty_dialog.close()
    application.processEvents()


def test_update_dialog_presents_download_waiting_and_error_states() -> None:
    application = _application()
    dialog = UpdateDialog("0.2.8", _update_release("- 修复问题"))

    assert dialog.status_panel.isHidden()
    dialog.show_downloading()
    assert not dialog.status_panel.isHidden()
    assert not dialog.progress_bar.isHidden()
    assert dialog.update_button.text() == "正在更新…"
    assert not dialog.update_button.isEnabled()
    dialog.set_download_progress(3, 4)
    assert dialog.progress_bar.value() == 75
    assert dialog.progress_detail_label.text() == "75%"

    dialog.show_waiting_for_recognition()
    assert dialog.progress_bar.isHidden()
    assert dialog.update_button.text() == "等待安装"
    assert "识别完成后" in dialog.status_label.text()

    dialog.show_error("更新失败：网络不可用")
    assert dialog.status_panel.property("state") == "error"
    assert dialog.update_button.text() == "重试更新"
    assert dialog.update_button.isEnabled()
    assert dialog.later_button.text() == "关闭"
    assert dialog.later_button.isEnabled()
    dialog.close()
    application.processEvents()


@pytest.mark.parametrize("state", ("downloading", "waiting"))
@pytest.mark.parametrize("action", ("button", "escape", "close"))
def test_update_dialog_busy_cancellation_is_idempotent(
    state: str,
    action: str,
) -> None:
    application = _application()
    dialog = UpdateDialog("0.2.8", _update_release("- 修复问题"))
    cancelled = QSignalSpy(dialog.cancel_requested)
    reminded = QSignalSpy(dialog.remind_later_requested)
    if state == "downloading":
        dialog.show_downloading()
        assert dialog.later_button.text() == "取消下载"
    else:
        dialog.show_waiting_for_recognition()
        assert dialog.later_button.text() == "取消安装"
    dialog.show()
    application.processEvents()

    if action == "button":
        dialog.later_button.click()
    elif action == "escape":
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
    else:
        dialog.close()
    application.processEvents()
    dialog.reject()
    dialog.close()

    assert cancelled.count() == 1
    assert reminded.count() == 0
    assert dialog.later_button.text() == "正在取消…"
    assert not dialog.later_button.isEnabled()


def test_update_dialog_keeps_footer_visible_at_constrained_height() -> None:
    application = _application()
    dialog = UpdateDialog("0.2.8", _update_release("- 修复问题\n" * 20))
    dialog.resize(620, 430)
    dialog.show()
    application.processEvents()

    assert dialog.height() <= 430
    button_bottom = dialog.update_button.mapTo(
        dialog, dialog.update_button.rect().bottomRight()
    ).y()
    assert button_bottom < dialog.height()

    dialog.show_downloading()
    application.processEvents()

    assert dialog.height() <= 430
    button_bottom = dialog.update_button.mapTo(
        dialog, dialog.update_button.rect().bottomRight()
    ).y()
    assert button_bottom < dialog.height()
    dialog.close()
    application.processEvents()


def test_update_dialog_style_contract_exists_in_both_themes() -> None:
    for theme in ("light", "dark"):
        stylesheet = application_stylesheet(theme)
        assert "QFrame#UpdateHeader" in stylesheet
        assert "QTextBrowser#UpdateNotes" in stylesheet
        assert 'QFrame#UpdateStatusPanel[state="error"]' in stylesheet
        assert "QProgressBar#UpdateProgress" in stylesheet


def test_update_dialog_source_build_state_keeps_release_action_available() -> None:
    application = _application()
    dialog = UpdateDialog("0.2.8", _update_release("- 修复问题"))
    requested = QSignalSpy(dialog.update_requested)

    dialog.show_source_build_message()
    assert dialog.status_panel.property("state") == "info"
    assert "GitHub 发布页" in dialog.status_label.text()
    assert dialog.progress_bar.isHidden()
    assert dialog.update_button.text() == "再次打开发布页"
    assert dialog.update_button.isEnabled()
    dialog.update_button.click()
    assert requested.count() == 1
    dialog.close()
    application.processEvents()


class FakeApiKeyStore:
    def __init__(self, key: str | None = None, base_url: str | None = None) -> None:
        self.key = key
        self.base_url = base_url

    def load(self) -> str | None:
        return self.key

    def has_key(self) -> bool:
        return self.key is not None

    def load_for_base_url(self, base_url: str) -> str | None:
        if self.key is None:
            return None
        if self.base_url is not None and base_url != self.base_url:
            return None
        return self.key

    def has_key_for_base_url(self, base_url: str) -> bool:
        return self.load_for_base_url(base_url) is not None

    def save(self, value: str, base_url: str) -> None:
        self.key = value
        self.base_url = base_url

    def delete(self) -> None:
        self.key = None
        self.base_url = None


class MouseRelease:
    @staticmethod
    def button() -> Qt.MouseButton:
        return Qt.MouseButton.LeftButton

    @staticmethod
    def position() -> QPointF:
        return QPointF(40, 40)


class FakeCloseEvent:
    def __init__(self, *, spontaneous: bool) -> None:
        self._spontaneous = spontaneous
        self.accepted = False
        self.ignored = False

    def spontaneous(self) -> bool:
        return self._spontaneous

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


def test_overlay_is_white_uses_arrow_cursor_and_preserves_cancel_semantics() -> None:
    application = _application()
    screen = application.primaryScreen()
    assert screen is not None
    assert OVERLAY_ALPHA < 100
    assert OVERLAY_COLOR == "#FFFFFF"

    screenshot = QPixmap(screen.geometry().size())
    screenshot.fill(Qt.GlobalColor.black)
    closed_overlay = SnipOverlay(screen, screenshot)
    assert closed_overlay.cursor().shape() == Qt.CursorShape.ArrowCursor
    cancellations: list[bool] = []
    closed_overlay.cancelled.connect(lambda: cancellations.append(True))
    closed_overlay.show()
    application.processEvents()
    overlay_image = closed_overlay.grab().toImage()
    corner = overlay_image.pixelColor(5, 5)
    center = overlay_image.pixelColor(overlay_image.rect().center())
    assert corner == center
    assert corner.red() > 0 and corner.red() == corner.green() == corner.blue()
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


def test_overlay_right_click_and_source_pixel_small_selection_feedback() -> None:
    application = _application()
    screen = application.primaryScreen()
    assert screen is not None
    screenshot = QPixmap(200, 200)
    screenshot.fill(Qt.GlobalColor.white)
    too_small = SnipOverlay(screen, screenshot)
    too_small.resize(100, 100)
    too_small.show()
    application.processEvents()

    too_small._start = QPoint(5, 5)
    too_small._end = QPoint(9, 9)
    too_small_release = type(
        "TooSmallRelease",
        (),
        {
            "button": staticmethod(lambda: Qt.MouseButton.LeftButton),
            "position": staticmethod(lambda: QPointF(9, 9)),
        },
    )()
    too_small.mouseReleaseEvent(too_small_release)  # type: ignore[arg-type]
    source = too_small._map_to_source(too_small._selection_rect())
    assert (source.width(), source.height()) == (10, 10)
    assert "选区过小" in too_small._selection_error

    click = SnipOverlay(screen, screenshot)
    click.resize(100, 100)
    click.show()
    click._start = QPoint(5, 5)
    click.mouseReleaseEvent(
        type(
            "ClickRelease",
            (),
            {
                "button": staticmethod(lambda: Qt.MouseButton.LeftButton),
                "position": staticmethod(lambda: QPointF(5, 5)),
            },
        )()
    )  # type: ignore[arg-type]
    assert click._selection_rect().size().toTuple() == (1, 1)
    assert "选区过小" in click._selection_error
    application.processEvents()
    assert not click.grab().isNull()

    accepted = SnipOverlay(screen, screenshot)
    accepted.resize(100, 100)
    captures = QSignalSpy(accepted.captured)
    accepted._start = QPoint(5, 5)
    accepted._end = QPoint(10, 10)
    accepted.mouseReleaseEvent(
        type(
            "AcceptedRelease",
            (),
            {
                "button": staticmethod(lambda: Qt.MouseButton.LeftButton),
                "position": staticmethod(lambda: QPointF(10, 10)),
            },
        )()
    )  # type: ignore[arg-type]
    assert captures.count() == 1
    captured = captures.at(0)[0]
    assert (captured.width(), captured.height()) == (12, 12)

    cancellable = SnipOverlay(screen, screenshot)
    cancelled = QSignalSpy(cancellable.cancelled)
    cancellable.show()
    QTest.mouseClick(cancellable, Qt.MouseButton.RightButton)
    assert cancelled.count() == 1
    too_small.close()
    click.close()


def test_floating_orb_click_menu_and_busy_state() -> None:
    application = _application()
    orb = FloatingOrb()
    requests: list[bool] = []
    orb.capture_requested.connect(lambda: requests.append(True))
    orb.show()
    application.processEvents()

    assert orb.menu_action_texts() == ["打开设置", "退出软件"]
    assert "左键截取公式" in orb.accessibleDescription()
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

    orb.set_initializing(True)
    assert "仍可点击截图" in orb.toolTip()
    QTest.mouseClick(orb, Qt.MouseButton.LeftButton, pos=orb.rect().center())
    assert requests == [True, True]

    orb.set_busy(True)
    application.processEvents()
    initial_angle = orb._busy_angle
    assert orb.busy_message == "正在识别中…"
    assert orb.busy_indicator_visible
    assert orb._busy_timer.isActive()
    assert orb._busy_label.text() == "正在识别中…"
    QTest.qWait(90)
    assert orb._busy_angle != initial_angle
    QTest.mouseClick(orb, Qt.MouseButton.LeftButton, pos=orb.rect().center())
    assert requests == [True, True]

    orb.set_busy(True, "模型初始化中，完成后自动识别…")
    application.processEvents()
    assert orb._busy_label.text() == "模型初始化中，完成后自动识别…"
    orb.hide()
    application.processEvents()
    assert not orb.busy_indicator_visible
    assert not orb._busy_timer.isActive()
    orb.show()
    application.processEvents()
    assert orb.busy_indicator_visible
    assert orb._busy_timer.isActive()

    orb.set_busy(False)
    application.processEvents()
    assert not orb.busy_indicator_visible
    assert not orb._busy_timer.isActive()
    assert orb.cursor().shape() == Qt.CursorShape.PointingHandCursor
    orb.close()


def test_floating_orb_keyboard_and_busy_cancel_action() -> None:
    _application()
    orb = FloatingOrb()
    captures = QSignalSpy(orb.capture_requested)
    cancellations = QSignalSpy(orb.cancel_requested)
    assert orb.focusPolicy() == Qt.FocusPolicy.StrongFocus
    QTest.keyClick(orb, Qt.Key.Key_Return)
    QTest.keyClick(orb, Qt.Key.Key_Space)
    assert captures.count() == 2
    orb.set_busy(True)
    assert orb.menu_action_texts()[0] == "取消当前识别"
    orb._cancel_action.trigger()
    assert cancellations.count() == 1
    QTest.keyClick(orb, Qt.Key.Key_Return)
    assert captures.count() == 2
    orb.close()


def test_result_panel_has_compact_padded_preview_and_copy_hides_panel() -> None:
    application = _application()
    panel = FloatingResultPanel()
    result = RecognitionResult(r"\frac{x}{y}", "Rapid", 0.25)
    consumed: list[bool] = []
    panel.result_consumed.connect(lambda: consumed.append(True))

    close_button = panel.findChild(QPushButton, "FloatingCloseButton")
    assert close_button is not None
    assert close_button.text() == "×"
    assert close_button.accessibleName() == "放弃本次结果"

    margins = panel.preview_frame.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
        12,
        12,
        12,
        12,
    )
    assert panel.preview_stack.height() == 180

    panel.show_result(result, QRect(20, 20, 68, 68))
    assert panel.formula_preview.current_backend == "mathjax"
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


def test_mathjax_preview_reports_missing_webengine_without_svg_fallback() -> None:
    _application()
    preview = FormulaPreviewWidget(webengine_enabled=False)
    failures = QSignalSpy(preview.failed)

    stale_request = preview.set_formula("x")
    current_request = preview.set_formula("y")
    QTest.qWait(10)

    assert current_request == stale_request + 1
    assert failures.count() == 1
    assert failures.at(0)[0] == current_request
    assert preview.current_backend == "unavailable"
    assert "WebEngine" in preview.error_text
    assert not hasattr(preview, "svg_preview")
    preview.close()


def test_mathjax_preview_ignores_stale_async_completion() -> None:
    _application()
    preview = FormulaPreviewWidget(webengine_enabled=False)
    rendered = QSignalSpy(preview.rendered)
    preview._request_id = 2
    preview._current_backend = "mathjax"

    preview._handle_render_state(
        1, '{"requestId":1,"state":"ready","error":""}'
    )
    assert rendered.count() == 0

    preview._handle_render_state(
        2, '{"requestId":2,"state":"ready","error":""}'
    )
    assert rendered.count() == 1
    assert rendered.at(0) == [2, "mathjax"]
    preview.close()


def test_mathjax_warmup_loads_one_persistent_page_and_reuses_it() -> None:
    _application()
    preview = FormulaPreviewWidget(webengine_enabled=False)
    rendered = QSignalSpy(preview.rendered)

    class Page:
        def __init__(self) -> None:
            self.documents: list[str] = []
            self.updates: list[str] = []
            self.request_id = 0

        def set_preview_html(self, document: str, _base_url: Any) -> None:
            self.documents.append(document)

        def runJavaScript(self, script: str, callback: Any) -> None:  # noqa: N802
            if "__setFormulaPreview" in script:
                self.updates.append(script)
                match = re.search(r",\s*(\d+)\);", script)
                assert match is not None
                self.request_id = int(match.group(1))
                callback(True)
            else:
                callback(
                    json.dumps(
                        {
                            "requestId": self.request_id,
                            "state": "ready",
                            "error": "",
                        }
                    )
                )

    page = Page()
    preview._web_page = page
    preview._web_view = preview._error_label

    preview.warmup()
    preview.warmup()
    assert preview.request_id == 0
    assert len(page.documents) == 1
    assert rendered.count() == 0

    preview._web_load_finished(True)
    first_request = preview.set_formula("x+y")
    second_request = preview.set_formula(r"\frac{x}{y}")

    assert (first_request, second_request) == (1, 2)
    assert len(page.documents) == 1
    assert len(page.updates) == 2
    assert rendered.count() == 2
    preview.close()


def test_mathjax_preview_watchdog_fails_without_browser_callback() -> None:
    _application()
    preview = FormulaPreviewWidget(webengine_enabled=False)
    failures = QSignalSpy(preview.failed)
    preview._request_id = 3
    preview._current_backend = "mathjax"
    preview._timeout_timer.start()

    preview._render_timeout()
    QTest.qWait(10)

    assert failures.count() == 1
    assert failures.at(0)[0] == 3
    assert "超时" in failures.at(0)[1]
    assert not preview._timeout_timer.isActive()
    preview.close()


def test_mathjax_preview_rejects_unknown_command() -> None:
    application = _application()
    preview = FormulaPreviewWidget()
    if not preview.webengine_available:
        pytest.skip("Qt WebEngine is unavailable")
    rendered = QSignalSpy(preview.rendered)
    failures = QSignalSpy(preview.failed)

    preview.warmup()
    deadline = time.monotonic() + 15
    while not preview._document_loaded and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(10)
    assert preview._document_loaded
    assert preview.request_id == 0
    assert rendered.count() == 0
    assert failures.count() == 0

    preview.resize(480, 168)
    preview.show()
    valid_request = preview.set_formula(r"\frac{x}{y}")
    assert rendered.count() or rendered.wait(15_000)
    assert rendered.at(0) == [valid_request, "mathjax"]

    request_id = preview.set_formula(r"\notacommand{x}")

    assert failures.count() or failures.wait(15_000)
    assert failures.at(0)[0] == request_id
    assert rendered.count() == 1
    preview.close()
    application.processEvents()


def test_mathjax_preview_does_not_leak_user_macros_between_requests() -> None:
    application = _application()
    preview = FormulaPreviewWidget()
    if not preview.webengine_available:
        pytest.skip("Qt WebEngine is unavailable")
    rendered = QSignalSpy(preview.rendered)
    failures = QSignalSpy(preview.failed)

    preview.warmup()
    deadline = time.monotonic() + 15
    while not preview._document_loaded and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(10)
    assert preview._document_loaded

    defining_request = preview.set_formula(
        r"\renewcommand{\formulaLeak}{x}\formulaLeak"
    )
    assert rendered.count() or rendered.wait(15_000)
    assert rendered.at(0) == [defining_request, "mathjax"]
    assert failures.count() == 0

    isolated_request = preview.set_formula(r"\formulaLeak")
    assert failures.count() or failures.wait(15_000)
    assert failures.at(0)[0] == isolated_request
    assert rendered.count() == 1
    preview.close()
    application.processEvents()


def test_mathjax_preview_does_not_leak_labels_between_requests() -> None:
    application = _application()
    preview = FormulaPreviewWidget()
    if not preview.webengine_available:
        pytest.skip("Qt WebEngine is unavailable")
    rendered = QSignalSpy(preview.rendered)
    failures = QSignalSpy(preview.failed)

    preview.warmup()
    deadline = time.monotonic() + 15
    while not preview._document_loaded and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(10)
    assert preview._document_loaded

    first_request = preview.set_formula(
        r"\begin{equation}x\label{formula-repeat}\end{equation}"
    )
    assert rendered.count() or rendered.wait(15_000)
    assert rendered.at(0) == [first_request, "mathjax"]
    assert failures.count() == 0

    second_request = preview.set_formula(
        r"\begin{equation}y\label{formula-repeat}\end{equation}"
    )
    assert rendered.count() >= 2 or rendered.wait(15_000)
    assert rendered.at(1) == [second_request, "mathjax"]
    assert failures.count() == 0
    preview.close()
    application.processEvents()


def test_result_panel_only_reports_success_for_current_render_request(
    monkeypatch: Any,
) -> None:
    application = _application()
    panel = FloatingResultPanel()
    requests: list[int] = []

    def defer_render(_latex: str) -> int:
        panel.formula_preview._request_id += 1
        request_id = panel.formula_preview._request_id
        requests.append(request_id)
        return request_id

    monkeypatch.setattr(panel.formula_preview, "set_formula", defer_render)
    panel.show_result(
        RecognitionResult("x", "MathCraft", 0.1),
        QRect(20, 20, 68, 68),
    )
    first_request = requests[-1]
    assert panel.status_label.text() == "正在生成预览…"
    assert "电子公式已生成" not in panel.quality_label.text()

    panel.latex_view.setPlainText("y")
    panel.formula_preview.rendered.emit(first_request, "mathjax")
    panel.formula_preview.failed.emit(first_request, "stale failure")
    assert panel.status_label.text() == "正在更新预览…"
    assert "电子公式已生成" not in panel.quality_label.text()

    panel._refresh_edited_preview()
    current_request = requests[-1]
    assert current_request != first_request
    panel.formula_preview.rendered.emit(first_request, "mathjax")
    panel.formula_preview.failed.emit(first_request, "stale failure")
    assert panel.status_label.text() == "正在生成预览…"
    assert panel.preview_stack.currentWidget() is panel.preview_frame

    panel.formula_preview.rendered.emit(current_request, "mathjax")
    assert panel.status_label.text() == ""
    panel.formula_preview.failed.emit(first_request, "late stale failure")
    assert panel.status_label.text() == ""
    panel.close()
    application.processEvents()


def test_persistent_preview_page_load_failure_fails_current_request() -> None:
    _application()
    preview = FormulaPreviewWidget(webengine_enabled=False)
    failures = QSignalSpy(preview.failed)
    preview._request_id = 2
    preview._current_backend = "mathjax"

    preview._web_load_finished(False)
    QTest.qWait(10)

    assert preview.current_backend == "unavailable"
    assert failures.count() == 1
    assert failures.at(0)[0] == 2
    assert "加载失败" in failures.at(0)[1]
    preview.close()


def test_result_panel_switches_disagreeing_local_and_ai_candidates(
    monkeypatch: Any,
) -> None:
    application = _application()
    panel = FloatingResultPanel()
    local = RecognitionCandidate("x", "MathCraft", 0.2, source="local")
    ai = RecognitionCandidate("y", "AI · vision-model", 0.3, source="ai")
    result = RecognitionResult(
        "x",
        local.backend,
        0.35,
        "ai-parallel",
        ("本地与 AI 结果不一致，可切换对照后复制。",),
        (local, ai),
        "different",
    )
    drafts: list[str] = []
    sources: list[str] = []
    panel.draft_changed.connect(drafts.append)
    panel.source_changed.connect(sources.append)
    converted: list[str] = []
    monkeypatch.setattr(
        floating,
        "latex_to_mathml",
        lambda latex: converted.append(latex) or f"<math><mi>{latex}</mi></math>",
    )

    panel.show_result(result, QRect(20, 20, 68, 68))
    assert panel.source_switch.isVisible()
    assert not panel.local_result_button.isChecked()
    assert not panel.ai_result_button.isChecked()
    assert panel.latex_view.toPlainText() == "x"
    assert "MathCraft" in panel.backend_label.text()
    assert not panel.copy_latex_button.isEnabled()
    assert not panel.copy_mathml_button.isEnabled()

    panel.local_result_button.click()
    assert panel.copy_latex_button.isEnabled()
    assert panel.latex_view.toPlainText() == "x"
    assert "MathCraft" in panel.backend_label.text()
    assert sources == ["local"]
    assert panel.formula_preview.current_backend == "mathjax"
    panel.latex_view.setPlainText("edited")
    assert panel.source_switch.isVisible()
    panel.local_result_button.click()
    assert panel.latex_view.toPlainText() == "x"
    assert drafts[-1] == "x"

    panel.ai_result_button.click()
    assert sources == ["local", "ai"]
    panel.copy_mathml_button.click()
    assert converted == ["y"]
    assert QApplication.clipboard().text() == "<math><mi>y</mi></math>"
    QApplication.clipboard().clear()
    panel.close()
    application.processEvents()


def test_result_panel_restores_explicit_local_source_for_edited_draft() -> None:
    panel = FloatingResultPanel()
    local = RecognitionCandidate("local-x", "MathCraft", 0.2, source="local")
    ai = RecognitionCandidate("ai-y", "AI · vision-model", 0.3, source="ai")
    result = RecognitionResult(
        ai.latex,
        ai.backend,
        0.35,
        "ai-parallel",
        ("本地与 AI 结果不一致，可切换对照后复制。",),
        (local, ai),
        "different",
    )

    panel.show_result(
        result,
        QRect(20, 20, 68, 68),
        draft="local-edited",
        source="local",
    )

    assert panel.local_result_button.isChecked()
    assert not panel.ai_result_button.isChecked()
    assert panel.latex_view.toPlainText() == "local-edited"
    assert "MathCraft" in panel.backend_label.text()
    panel.close()


def test_result_error_clears_status_from_previous_result() -> None:
    panel = FloatingResultPanel()
    anchor = QRect(20, 20, 68, 68)
    panel.show_result(RecognitionResult("x", "Rapid", 0.1), anchor)
    panel.latex_view.setPlainText("edited")
    panel._refresh_edited_preview()
    panel._preview_rendered(panel.formula_preview.request_id, "mathjax")
    assert panel.status_label.text() == ""

    panel.show_error("识别失败", anchor)

    assert panel.status_label.text() == ""
    assert panel.status_label.isHidden()
    panel.close()


def test_result_panel_error_state_generic_help_and_escape_consumes() -> None:
    application = _application()
    panel = FloatingResultPanel()
    consumed = QSignalSpy(panel.result_consumed)
    panel.show_error("识别失败", QRect(20, 20, 68, 68))
    application.processEvents()
    panel._set_status("预览失败", "error")
    assert panel.status_label.wordWrap()
    assert panel.status_label.property("state") == "error"
    assert "设置中检查识别引擎" in panel.quality_label.text()
    assert application.focusWidget() is panel.recapture_button
    QTest.keyClick(panel.recapture_button, Qt.Key.Key_Escape)
    assert panel.isHidden()
    assert consumed.count() == 1


def test_result_panel_escape_bubbles_from_focused_latex_editor() -> None:
    application = _application()
    panel = FloatingResultPanel()
    consumed = QSignalSpy(panel.result_consumed)
    panel.show_result(
        RecognitionResult("x", "MathCraft", 0.1),
        QRect(20, 20, 68, 68),
    )
    application.processEvents()

    assert application.focusWidget() is panel.latex_view
    QTest.keyClick(panel.latex_view, Qt.Key.Key_Escape)

    assert panel.isHidden()
    assert consumed.count() == 1


@pytest.mark.parametrize("comparison", ("equivalent", "not_compared"))
def test_result_panel_hides_source_switch_without_a_real_disagreement(
    comparison: str,
) -> None:
    panel = FloatingResultPanel()
    alternatives = (
        RecognitionCandidate("x", "MathCraft", 0.1, source="local"),
        RecognitionCandidate("x", "AI", 0.1, source="ai"),
    )
    panel.show_result(
        RecognitionResult("x", "AI", 0.1, alternatives=alternatives, comparison=comparison),
        QRect(20, 20, 68, 68),
    )

    assert panel.source_switch.isHidden()
    panel.close()


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
        "MathCraft",
        0.2,
        warnings=("识别结果疑似偏导符号混淆，请对照原图重点校对。",),
    )

    panel.show_result(result, QRect(20, 20, 68, 68))

    assert "疑似偏导" in panel.quality_label.text()
    assert panel.quality_label.property("warning") is True
    panel.close()
    application.processEvents()


def test_result_panel_surfaces_all_manager_risk_and_disagreement_warnings() -> None:
    application = _application()
    panel = FloatingResultPanel()
    result = RecognitionResult(
        "x+y",
        "MathCraft",
        0.2,
        strategy="auto-reviewed",
        warnings=(
            "公式前景可能触边",
            "两个引擎结果不一致；复杂公式请重点校对。",
        ),
    )

    panel.show_result(result, QRect(20, 20, 68, 68))

    assert "触边" in panel.quality_label.text()
    assert "两个引擎结果不一致" in panel.quality_label.text()
    assert panel.quality_label.property("warning") is True
    panel.close()
    application.processEvents()


def test_editing_only_spacing_preserves_image_and_disagreement_warnings() -> None:
    application = _application()
    panel = FloatingResultPanel()
    result = RecognitionResult(
        "x+y",
        "MathCraft",
        0.2,
        strategy="auto-reviewed",
        warnings=("公式前景可能触边", "两个引擎结果不一致，请重点校对。"),
    )
    panel.show_result(result, QRect(20, 20, 68, 68))

    panel.latex_view.setPlainText(" x + y ")
    panel._refresh_edited_preview()

    assert "触边" in panel.quality_label.text()
    assert "两个引擎结果不一致" in panel.quality_label.text()
    panel.close()
    application.processEvents()


def test_result_panel_rerenders_and_copies_edited_latex(monkeypatch: Any) -> None:
    application = _application()
    panel = FloatingResultPanel()

    original_render = panel.formula_preview.set_formula
    monkeypatch.setattr(
        panel.formula_preview,
        "set_formula",
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
    assert panel.status_label.text() == "正在生成预览…"
    panel._preview_rendered(panel.formula_preview.request_id, "mathjax")
    assert panel.status_label.text() == ""
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
            if key == "broken":
                raise RuntimeError("boom")

    worker = ModelWarmupWorker(Manager(), ("broken", "mathcraft"))  # type: ignore[arg-type]
    worker.signals.started.connect(lambda key: events.append(("started", key)))
    worker.signals.succeeded.connect(lambda key: events.append(("succeeded", key)))
    worker.signals.failed.connect(
        lambda key, message: events.append(("failed", key, message))
    )
    worker.signals.finished.connect(lambda: events.append(("finished",)))

    worker.run()

    assert events == [
        ("started", "broken"),
        ("failed", "broken", "boom"),
        ("started", "mathcraft"),
        ("succeeded", "mathcraft"),
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
    assistant.preferences = FloatingPreferences("mathcraft", "blue", "dark", True)
    pool = Pool()
    assistant._thread_pool = pool  # type: ignore[assignment]

    assistant.start_model_warmup()
    assistant.start_model_warmup()

    assert len(pool.started) == 1
    worker = pool.started[0]
    assert worker.backend_keys == ("mathcraft",)
    assert assistant._warmup_worker is worker
    assert assistant._model_warmup_state == "warming"
    assert "初始化中" in assistant.orb.toolTip()
    worker.signals.started.emit("mathcraft")
    assert assistant.settings_panel.engine_status_labels["mathcraft"].text() == "正在初始化"
    worker.signals.succeeded.emit("mathcraft")
    assert assistant.settings_panel.engine_status_labels["mathcraft"].text() == "已初始化"
    assert assistant._model_warmup_state == "ready"
    worker.signals.failed.emit("mathcraft", "offline")
    assert "初始化失败" in assistant.settings_panel.engine_status_labels["mathcraft"].text()
    worker.signals.finished.emit()
    assert assistant._warmup_worker is None
    assert "初始化中" not in assistant.orb.toolTip()
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


def test_startup_warms_mathcraft_and_shutdown_closes_manager(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    started: list[Any] = []
    closed: list[bool] = []
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    monkeypatch.setattr(assistant._thread_pool, "start", started.append)
    monkeypatch.setattr(assistant.manager, "close", lambda: closed.append(True))
    assistant.start_model_warmup()
    assert started[0].backend_keys == ("mathcraft",)
    assistant.shutdown()
    assert closed == [True]


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        ("auto", ("mathcraft",)),
        ("rapid", ("mathcraft",)),
        ("mathcraft", ("mathcraft",)),
    ),
)
def test_startup_warmup_keys_match_mode(
    tmp_path: Path, monkeypatch: Any, mode: str, expected: tuple[str, ...]
) -> None:
    _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant.preferences = FloatingPreferences(mode, "blue", "dark", True)
    started: list[Any] = []
    monkeypatch.setattr(assistant._thread_pool, "start", started.append)

    assistant.start_model_warmup()

    assert started[0].backend_keys == expected
    assistant._warmup_worker = None
    assistant.shutdown()


def test_v2_settings_center_matches_reference_layout_and_navigation(tmp_path: Path) -> None:
    _application()
    panel = SettingsPanel(_settings(tmp_path), FloatingPreferences())

    assert panel.size().width() == 1080
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
    assert panel.sidebar.width() == 220
    assert panel.header.height() == 78
    assert panel.brand_logo.size().width() == 30
    assert all(button.height() == 44 for button, _title in panel._nav_entries)
    assert all(not button.icon().isNull() for button, _title in panel._nav_entries)
    assert panel.theme_toggle_button.size().width() == 34
    assert panel.theme_toggle_button.size().height() == 34
    assert not panel.theme_toggle_button.icon().isNull()
    assert panel.theme_toggle_button.toolTip()
    assert panel.theme_toggle_button.accessibleName() == "切换明暗主题"
    scroll = panel.settings_page.findChild(QScrollArea)
    assert scroll is not None
    body_layout = scroll.widget().layout()
    assert body_layout is not None
    margins = body_layout.contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
        28,
        24,
        28,
        28,
    )
    assert body_layout.spacing() == 16
    assert panel.startup_checkbox.isCheckable()
    assert not application_icon().isNull()
    assert not tutorial_formula_image().isNull()
    assert not panel.windowIcon().isNull()
    assert panel.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
    assert panel.brand_logo.pixmap() is not None
    assert not panel.brand_logo.pixmap().isNull()
    assert panel.brand_edition.isHidden()
    assert panel.update_button is panel.check_update_button
    assert f"v{application_version()}" in panel.update_version_label.text()
    assert all(
        dot.property("available") == "false"
        for dot in panel.engine_status_dots.values()
    )
    assert all(button.accessibleName() for button in panel.color_buttons.values())
    assert panel.findChild(settings_ui.QWidget, "SettingsCTA") is None
    panel.hide()


def test_settings_header_subtitles_and_error_banner(tmp_path: Path) -> None:
    panel = SettingsPanel(_settings(tmp_path), FloatingPreferences())
    assert panel.settings_error_label.objectName() == "SettingsErrorBanner"
    assert panel.settings_error_label.isHidden()
    expected = (
        "启动、更新与引擎状态",
        "本地识别与可选 AI 增强",
        "调整圆环与中心 Logo",
        "4 步完成截图、校对与复制",
    )
    for index, subtitle in enumerate(expected):
        panel._select_page(index)
        assert panel.page_subtitle.text() == subtitle
        assert panel.page_subtitle.isVisibleTo(panel)
    panel._set_settings_error("无法保存")
    assert not panel.settings_error_label.isHidden()
    panel._set_settings_error("")
    assert panel.settings_error_label.isHidden()
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


def test_recognition_page_only_shows_mathcraft(tmp_path: Path) -> None:
    _application()
    settings = _settings(tmp_path)
    panel = SettingsPanel(settings, FloatingPreferences())
    assert panel.mode_combo.isHidden()
    assert set(panel.mode_cards) == {"mathcraft"}
    assert panel.mode_combo.currentData() == "mathcraft"
    assert panel.mode_cards["mathcraft"].isChecked()
    assert panel.overview_mode_name.text() == "MathCraft OCR"
    assert panel.overview_mode_tag.text() == "CPU"
    assert panel.mode_summary_label.text() == "本地单引擎公式识别"
    assert panel.mode_summary_label.isHidden()
    assert "Rapid" not in "".join(
        widget.text() for widget in panel.findChildren(settings_ui.QLabel)
    )
    assert panel.recognition_page.findChild(
        settings_ui.QWidget, "RecognitionTriggerCard"
    ) is None
    panel.hide()


def test_ai_correction_is_off_by_default_and_key_stays_out_of_qsettings(
    tmp_path: Path,
) -> None:
    _application()
    settings = _settings(tmp_path)
    key_store = FakeApiKeyStore()
    panel = SettingsPanel(
        settings,
        FloatingPreferences(),
        api_key_store=key_store,  # type: ignore[arg-type]
    )
    preference_changes = QSignalSpy(panel.preferences_changed)

    assert panel.ai_correction_toggle.isChecked() is False
    assert panel.ai_correction_toggle.isEnabled() is True
    assert panel.ai_configuration_widget.isHidden()
    assert panel.ai_base_url_input.text() == ""
    assert panel.ai_model_combo.count() == 0
    assert panel.ai_model_combo.currentIndex() == -1
    assert not panel.ai_save_config_button.isEnabled()

    panel.ai_correction_toggle.click()
    assert not panel.ai_configuration_widget.isHidden()
    assert panel.preferences.ai_correction_enabled is False
    assert preference_changes.count() == 0
    panel.ai_base_url_input.setText("https://gateway.example/v1")
    panel.ai_api_key_input.setText("unit-test-token")
    panel.ai_save_key_button.click()
    assert key_store.key == "unit-test-token"
    assert panel.ai_api_key_input.text() == ""
    assert "Windows 凭据管理器" in panel.ai_key_status_label.text()
    assert panel.preferences.ai_base_url == ""
    assert settings.value("recognition/ai_base_url") is None
    assert preference_changes.count() == 0
    assert panel.ai_refresh_models_button.isEnabled()
    assert not panel.ai_test_connection_button.isEnabled()

    class ListedModels:
        action = "list"
        base_url = "https://gateway.example/v1"

    list_worker = ListedModels()
    panel._ai_model_worker = list_worker  # type: ignore[assignment]
    panel._ai_active_context = (
        "list",
        "https://gateway.example/v1",
        "",
        panel._ai_credential_generation,
    )
    panel._ai_model_request_succeeded(  # type: ignore[arg-type]
        list_worker, ("vision-a", "vision-b")
    )
    panel._ai_model_request_finished(list_worker)  # type: ignore[arg-type]
    assert panel.ai_model_combo.currentIndex() == -1
    assert not panel.ai_test_connection_button.isEnabled()

    panel.ai_model_combo.setCurrentIndex(1)
    assert panel.ai_save_config_button.isEnabled()
    assert panel.preferences.ai_correction_enabled is False
    assert settings.value("recognition/ai_correction_enabled") is None
    assert preference_changes.count() == 0

    panel.ai_save_config_button.click()
    assert panel.preferences.ai_correction_enabled is True
    assert settings_ui._boolean(
        settings.value("recognition/ai_correction_enabled"), False
    ) is True
    assert settings.value("recognition/ai_base_url") == "https://gateway.example/v1"
    assert settings.value("recognition/ai_model") == "vision-b"
    assert panel.ai_connection_status_label.text() == "配置已保存并生效"
    assert not panel.ai_save_config_button.isEnabled()
    assert panel.ai_test_connection_button.isEnabled()
    assert preference_changes.count() == 1
    assert all(
        "unit-test-token" not in str(settings.value(key))
        for key in settings.allKeys()
    )

    panel.ai_delete_key_button.click()
    assert key_store.key is None
    assert panel.ai_correction_toggle.isChecked() is False
    assert panel.ai_configuration_widget.isHidden()
    assert panel.preferences.ai_correction_enabled is False
    assert settings_ui._boolean(
        settings.value("recognition/ai_correction_enabled"), True
    ) is False
    assert preference_changes.count() == 2
    panel.hide()


def test_invalid_ai_draft_does_not_replace_saved_configuration(
    tmp_path: Path,
) -> None:
    _application()
    settings = _settings(tmp_path)
    saved = FloatingPreferences(
        ai_correction_enabled=True,
        ai_base_url="https://saved.example/v1",
        ai_model="saved-model",
    )
    saved.save(settings)
    panel = SettingsPanel(
        settings,
        saved,
        api_key_store=FakeApiKeyStore("unit-test-token"),  # type: ignore[arg-type]
    )

    assert not panel.ai_save_config_button.isEnabled()
    panel.ai_model_combo.addItem("invalid model")
    panel.ai_model_combo.setCurrentIndex(1)
    assert panel.ai_save_config_button.isEnabled()

    panel.ai_save_config_button.click()

    assert panel.ai_model_combo.currentText() == "invalid model"
    assert panel.preferences == saved
    assert settings.value("recognition/ai_base_url") == "https://saved.example/v1"
    assert settings.value("recognition/ai_model") == "saved-model"
    assert settings_ui._boolean(
        settings.value("recognition/ai_correction_enabled"), False
    ) is True
    assert panel.ai_connection_status_label.property("error") is True
    panel.hide()


def test_ai_configuration_save_is_disabled_while_request_is_active(
    tmp_path: Path,
) -> None:
    _application()
    panel = SettingsPanel(
        _settings(tmp_path),
        FloatingPreferences(),
        api_key_store=FakeApiKeyStore("unit-test-token"),  # type: ignore[arg-type]
    )
    panel.ai_correction_toggle.setChecked(True)
    panel.ai_base_url_input.setText("https://gateway.example/v1")
    panel.ai_model_combo.addItem("vision-model")
    panel.ai_model_combo.setCurrentIndex(0)
    assert panel.ai_save_config_button.isEnabled()

    class PendingWorker:
        action = "test"

        def cancel(self) -> None:
            pass

    panel._ai_model_worker = PendingWorker()  # type: ignore[assignment]
    panel._update_ai_action_state()

    assert not panel.ai_save_config_button.isEnabled()
    panel.cancel_ai_request()
    assert panel.ai_save_config_button.isEnabled()
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


@pytest.mark.parametrize("stored_mode", ("auto", "rapid", "paddle", "unknown"))
def test_legacy_mode_migrates_to_mathcraft_and_persists(
    tmp_path: Path, monkeypatch: Any, stored_mode: str
) -> None:
    monkeypatch.setattr(
        settings_ui,
        "backend_summaries",
        lambda: (("mathcraft", "MathCraft", False),),
    )
    settings = _settings(tmp_path)
    settings.setValue("recognition/mode", stored_mode)

    preferences = FloatingPreferences.load(settings)
    panel = SettingsPanel(settings, preferences)
    mathcraft_index = panel.mode_combo.findData("mathcraft")
    mathcraft_item = panel.mode_combo.model().item(mathcraft_index)

    assert settings.value("recognition/mode") == "mathcraft"
    assert panel.mode_combo.currentData() == "mathcraft"
    assert mathcraft_item is not None
    assert not mathcraft_item.isEnabled()
    assert not panel.mode_cards["mathcraft"].isEnabled()
    panel.close()


def test_preferences_save_always_writes_mathcraft(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    preferences = FloatingPreferences("rapid")
    preferences.save(settings)

    assert settings.value("recognition/mode") == "mathcraft"


def test_ai_provider_preferences_round_trip_without_api_key(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    preferences = FloatingPreferences(
        ai_correction_enabled=True,
        ai_base_url="https://gateway.example/v1/",
        ai_model="vision-model",
    )

    preferences.save(settings)
    loaded = FloatingPreferences.load(settings)

    assert loaded.ai_correction_enabled is True
    assert loaded.ai_base_url == "https://gateway.example/v1"
    assert loaded.ai_model == "vision-model"
    assert all("key" not in key.casefold() for key in settings.allKeys())


def test_unsafe_ai_provider_url_is_not_persisted(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    FloatingPreferences(
        ai_correction_enabled=True,
        ai_base_url="https://gateway.example/v1?api_key=secret"
    ).save(settings)

    assert settings.value("recognition/ai_base_url") == ""
    assert settings_ui._boolean(
        settings.value("recognition/ai_correction_enabled"), True
    ) is False


def test_invalid_stored_provider_disables_ai_before_falling_back(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.setValue("recognition/ai_correction_enabled", True)
    settings.setValue("recognition/ai_base_url", "http://remote.example/v1")
    settings.setValue("recognition/ai_model", "vision-model")

    loaded = FloatingPreferences.load(settings)

    assert loaded.ai_correction_enabled is False
    assert loaded.ai_base_url == ""
    assert settings_ui._boolean(
        settings.value("recognition/ai_correction_enabled"), True
    ) is False


def test_stale_model_list_does_not_overwrite_new_provider_config(
    tmp_path: Path,
) -> None:
    _application()
    panel = SettingsPanel(
        _settings(tmp_path),
        FloatingPreferences(),
        api_key_store=FakeApiKeyStore("unit-test-token"),  # type: ignore[arg-type]
    )
    panel.ai_correction_toggle.setChecked(True)
    panel.ai_base_url_input.setText("https://first.example/v1")
    panel.ai_model_combo.addItems(("vision-a", "vision-b"))
    panel.ai_model_combo.setCurrentIndex(0)
    panel._ai_models_base_url = "https://first.example/v1"

    class PendingWorker:
        action = "list"
        cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    worker = PendingWorker()
    panel._ai_model_worker = worker  # type: ignore[assignment]
    panel._ai_active_context = (
        "list",
        "https://first.example/v1",
        "",
        0,
    )
    panel.ai_refresh_models_button.setEnabled(False)
    panel.ai_test_connection_button.setEnabled(False)
    panel.ai_base_url_input.setText("https://second.example/v1")

    assert worker.cancelled is True
    assert panel._ai_model_worker is None
    assert panel.ai_refresh_models_button.isEnabled()
    assert not panel.ai_test_connection_button.isEnabled()
    assert panel.ai_model_combo.count() == 0
    assert panel.ai_model_combo.currentIndex() == -1
    assert "已取消" in panel.ai_connection_status_label.text()

    replacement_worker = PendingWorker()
    panel._ai_model_worker = replacement_worker  # type: ignore[assignment]
    panel._ai_active_context = (
        "list",
        "https://second.example/v1",
        "",
        0,
    )
    panel.ai_refresh_models_button.setEnabled(False)
    panel.ai_test_connection_button.setEnabled(False)
    panel._set_ai_connection_status("正在执行新请求")

    panel._ai_model_request_succeeded(  # type: ignore[arg-type]
        worker, ("first-only-model",)
    )
    panel._ai_model_request_finished(worker)  # type: ignore[arg-type]

    assert panel.ai_model_combo.findText("first-only-model") == -1
    assert panel._ai_model_worker is replacement_worker
    assert not panel.ai_refresh_models_button.isEnabled()
    assert not panel.ai_test_connection_button.isEnabled()
    assert panel.ai_connection_status_label.text() == "正在执行新请求"
    panel.cancel_ai_request()
    panel.hide()


@pytest.mark.parametrize("terminal", ("success", "failure", "cancel"))
def test_ai_model_request_terminal_releases_workers(
    terminal: str,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    application = _application()
    panel = SettingsPanel(
        _settings(tmp_path),
        FloatingPreferences(),
        api_key_store=FakeApiKeyStore("unit-test-token"),  # type: ignore[arg-type]
    )
    panel.ai_correction_toggle.setChecked(True)
    panel.ai_base_url_input.setText("https://gateway.example/v1")

    def request_models(*_args: Any, **kwargs: Any) -> tuple[str, ...]:
        if terminal == "cancel":
            assert kwargs["cancel_event"].is_set()
            raise settings_ui.AICorrectionError("request cancelled")
        if terminal == "failure":
            raise settings_ui.AICorrectionError("request failed")
        return ("vision-model",)

    monkeypatch.setattr(worker_module, "list_compatible_models", request_models)

    class Pool:
        worker: Any = None

        def start(self, worker: Any) -> None:
            self.worker = worker
            if terminal != "cancel":
                worker.run()

    pool = Pool()

    class ThreadPool:
        globalInstance = staticmethod(lambda: pool)  # noqa: N815

    monkeypatch.setattr(settings_ui, "QThreadPool", ThreadPool)
    worker_refs: list[weakref.ReferenceType[Any]] = []

    for _ in range(20):
        panel._start_ai_model_request("list")
        worker = pool.worker
        assert worker is not None
        assert worker.model == ""
        worker_refs.append(weakref.ref(worker))
        if terminal == "cancel":
            panel.cancel_ai_request()
            worker.run()
        pool.worker = None
        del worker

    application.processEvents()
    gc.collect()

    assert sum(worker_ref() is not None for worker_ref in worker_refs) == 0
    panel.hide()


def test_replacing_ai_key_cancels_active_recognition_without_preference_change(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _application()
    key_store = FakeApiKeyStore("initial-placeholder")
    monkeypatch.setattr(floating, "OpenAIApiKeyStore", lambda: key_store)
    settings = _settings(tmp_path)
    settings.setValue("recognition/ai_correction_enabled", True)
    settings.setValue("recognition/ai_base_url", "https://gateway.example/v1")
    settings.setValue("recognition/ai_model", "vision-model")
    assistant = FloatingFormulaAssistant(settings=settings)
    initial_preferences = assistant.preferences

    class ActiveWorker:
        cancel_count = 0
        ai_enabled = True

        def cancel_ai(self) -> None:
            self.cancel_count += 1

    worker = ActiveWorker()
    assistant._worker = worker  # type: ignore[assignment]
    assistant.settings_panel.ai_api_key_input.setText("replacement-placeholder")
    assistant.settings_panel.ai_save_key_button.click()

    assert worker.cancel_count == 1
    assert assistant._worker is worker
    assert assistant.preferences == initial_preferences
    assert all(
        "placeholder" not in str(settings.value(key)) for key in settings.allKeys()
    )
    assistant._worker = None
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_appearance_change_does_not_cancel_local_recognition(tmp_path: Path) -> None:
    _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    worker = worker_module.RecognitionWorker(
        assistant.manager,
        Image.new("RGB", (20, 10), "white"),
        "mathcraft",
    )
    assistant._worker = worker

    assistant._apply_preferences(FloatingPreferences(result_theme="light"))

    assert not worker._cancel_event.is_set()
    assert not worker._local_cancel_event.is_set()
    worker.release_resources()
    assistant._worker = None
    assistant.shutdown()
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


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
    assert "#F7F8FA" in application.styleSheet()
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


def test_system_tray_uses_branding_and_expected_menu(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    monkeypatch.setattr(
        floating.QSystemTrayIcon,
        "isSystemTrayAvailable",
        staticmethod(lambda: True),
    )

    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))

    tray = assistant._tray_icon
    menu = assistant._tray_menu
    assert tray is not None
    assert menu is not None
    assert tray.isVisible()
    assert tray.icon().cacheKey() == application_icon().cacheKey()
    assert tray.toolTip() == "FormulaSnip 公式识别"
    assert [action.text() for action in menu.actions()] == [
        "开始识别",
        "显示悬浮球",
        "打开设置",
        "检查更新",
        "",
        "退出软件",
    ]
    assert menu.actions()[4].isSeparator()
    assistant.shutdown()
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_system_tray_actions_route_to_existing_workflows(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    monkeypatch.setattr(
        floating.QSystemTrayIcon,
        "isSystemTrayAvailable",
        staticmethod(lambda: True),
    )
    scheduled: list[Any] = []
    monkeypatch.setattr(
        floating.QTimer,
        "singleShot",
        lambda _milliseconds, callback: scheduled.append(callback),
    )
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assert assistant._tray_menu is not None
    actions = {
        action.text(): action
        for action in assistant._tray_menu.actions()
        if not action.isSeparator()
    }

    assistant.open_settings()
    actions["开始识别"].trigger()
    assert assistant.settings_panel.isHidden()
    assert assistant._capture_pending is True
    assert scheduled == [assistant._show_screen_overlay]
    assistant._capture_cancelled()

    assistant.open_settings()
    actions["显示悬浮球"].trigger()
    assert assistant.settings_panel.isHidden()
    assert assistant.orb.isVisible()

    actions["打开设置"].trigger()
    assert assistant.settings_panel.isVisible()
    assert assistant.orb.isHidden()

    update_requests: list[bool] = []
    monkeypatch.setattr(
        assistant,
        "check_for_updates",
        lambda *, manual=False: update_requests.append(manual),
    )
    assistant.enter_floating_mode()
    actions["检查更新"].trigger()
    assert assistant.settings_panel.isVisible()
    assert update_requests == [True]

    quit_requests: list[bool] = []
    monkeypatch.setattr(
        floating.QApplication,
        "quit",
        lambda: quit_requests.append(True),
    )
    actions["退出软件"].trigger()
    assert quit_requests == [True]
    assistant.shutdown()
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_system_tray_activation_routes_and_protects_active_capture(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    monkeypatch.setattr(
        floating.QSystemTrayIcon,
        "isSystemTrayAvailable",
        staticmethod(lambda: True),
    )
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    tray = assistant._tray_icon
    assert tray is not None
    activations: list[str] = []
    monkeypatch.setattr(
        assistant,
        "_show_floating_from_tray",
        lambda: activations.append("trigger"),
    )
    monkeypatch.setattr(
        assistant,
        "_start_capture_from_tray",
        lambda: activations.append("double-click"),
    )

    tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    tray.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)
    tray.activated.emit(QSystemTrayIcon.ActivationReason.Context)
    assert activations == ["double-click"]

    trigger_timeout = QSignalSpy(assistant._tray_trigger_timer.timeout)
    tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    assert trigger_timeout.wait(QApplication.doubleClickInterval() + 1000)
    assert activations == ["double-click", "trigger"]

    monkeypatch.undo()
    assistant.open_settings()
    assistant._worker = object()  # type: ignore[assignment]
    assistant._tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
    assistant._tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
    assert not assistant._tray_trigger_timer.isActive()
    assert assistant.settings_panel.isVisible()
    assert assistant._capture_pending is False
    assistant._worker = None

    assistant._capture_pending = True
    assistant._tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert assistant.settings_panel.isVisible()
    assert assistant.orb.isHidden()
    assistant._capture_pending = False
    assistant.shutdown()
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_system_tray_unavailable_falls_back_without_error(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    monkeypatch.setattr(
        floating.QSystemTrayIcon,
        "isSystemTrayAvailable",
        staticmethod(lambda: False),
    )

    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant.show()

    assert assistant._tray_icon is None
    assert assistant._tray_menu is None
    assert assistant.settings_panel.isVisible()

    assistant.enter_floating_mode()
    quit_requests: list[bool] = []
    monkeypatch.setattr(
        floating.QApplication,
        "quit",
        lambda: quit_requests.append(True),
    )
    event = FakeCloseEvent(spontaneous=True)
    assistant.orb.closeEvent(event)  # type: ignore[arg-type]

    assert event.ignored is True
    assert event.accepted is False
    assert quit_requests == [True]
    assistant.shutdown()
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_spontaneous_orb_close_hides_to_available_system_tray(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    monkeypatch.setattr(
        floating.QSystemTrayIcon,
        "isSystemTrayAvailable",
        staticmethod(lambda: True),
    )
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant.enter_floating_mode()
    assert assistant.orb.isVisible()
    quit_requests: list[bool] = []
    monkeypatch.setattr(
        floating.QApplication,
        "quit",
        lambda: quit_requests.append(True),
    )

    event = FakeCloseEvent(spontaneous=True)
    assistant.orb.closeEvent(event)  # type: ignore[arg-type]

    assert event.ignored is True
    assert event.accepted is False
    assert assistant.orb.isHidden()
    assert quit_requests == []
    assistant.shutdown()
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_programmatic_orb_close_remains_available_for_cleanup() -> None:
    _application()
    orb = FloatingOrb()
    event = FakeCloseEvent(spontaneous=False)
    close_requests: list[bool] = []
    orb.close_requested.connect(lambda: close_requests.append(True))

    orb.closeEvent(event)  # type: ignore[arg-type]

    assert event.accepted is True
    assert event.ignored is False
    assert close_requests == []
    orb.close()


def test_system_tray_shutdown_is_idempotent_and_clears_references(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    monkeypatch.setattr(
        floating.QSystemTrayIcon,
        "isSystemTrayAvailable",
        staticmethod(lambda: True),
    )
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    tray = assistant._tray_icon
    menu = assistant._tray_menu
    assert tray is not None
    assert menu is not None
    closed: list[bool] = []
    monkeypatch.setattr(assistant.manager, "close", lambda: closed.append(True))

    assistant.shutdown()
    assistant.shutdown()

    assert closed == [True]
    assert not tray.isVisible()
    assert tray.contextMenu() is None
    assert assistant._tray_icon is None
    assert assistant._tray_menu is None
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_settings_check_update_button_emits_request(tmp_path: Path) -> None:
    _application()
    panel = SettingsPanel(_settings(tmp_path), FloatingPreferences())
    requests: list[bool] = []
    panel.update_check_requested.connect(lambda: requests.append(True))

    panel.check_update_button.click()

    assert requests == [True]
    assert panel.update_status_label.text() == "稳定通道"
    panel.hide()


def test_startup_update_check_respects_background_throttle(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    settings = _settings(tmp_path)
    settings.setValue("updates/last_check_utc", int(time.time()) - 60)
    assistant = FloatingFormulaAssistant(settings=settings)
    scheduled: list[Any] = []
    started: list[Any] = []
    monkeypatch.setattr(
        floating.QTimer,
        "singleShot",
        lambda _milliseconds, callback: scheduled.append(callback),
    )
    monkeypatch.setattr(assistant._thread_pool, "start", started.append)

    assistant.start_update_checks()
    assistant.start_update_checks()
    assert len(scheduled) == 1

    scheduled[0]()

    assert started == []
    assert assistant._update_check_worker is None
    assert assistant.settings_panel.update_status_label.text() == "稳定通道"
    assert assistant.settings_panel.check_update_button.isEnabled()
    assistant.shutdown()


def test_background_update_check_keeps_twelve_hour_throttle(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    settings = _settings(tmp_path)
    settings.setValue("updates/last_check_utc", int(time.time()) - 60)
    assistant = FloatingFormulaAssistant(settings=settings)
    started: list[Any] = []
    monkeypatch.setattr(assistant._thread_pool, "start", started.append)

    assistant.check_for_updates()

    assert started == []
    assert assistant._update_check_worker is None
    assistant.shutdown()


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


def test_new_update_dialog_replaces_old_transaction(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()

    class Signal:
        def __init__(self) -> None:
            self.callback: Any = None

        def connect(self, callback: Any) -> None:
            self.callback = callback

    class Dialog:
        def __init__(self, _current: str, release: ReleaseInfo) -> None:
            self.release = release
            self.update_requested = Signal()
            self.closed = False

        def close(self) -> None:
            self.closed = True

        def show(self) -> None:
            pass

        def raise_(self) -> None:
            pass

        def activateWindow(self) -> None:  # noqa: N802
            pass

    monkeypatch.setattr(floating, "UpdateDialog", Dialog)
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    asset = UpdateAsset("setup.exe", "https://example.invalid/setup.exe", 5, "0" * 64)
    first_release = ReleaseInfo("0.3.0", "v0.3.0", "", asset)
    second_release = ReleaseInfo("0.4.0", "v0.4.0", "", asset)
    first_worker = object()
    second_worker = object()

    assistant._update_check_worker = first_worker  # type: ignore[assignment]
    assistant._update_available(first_release, True, first_worker)  # type: ignore[arg-type]
    first_dialog = assistant._update_dialog
    assert isinstance(first_dialog, Dialog)

    assistant._update_check_worker = second_worker  # type: ignore[assignment]
    assistant._update_available(second_release, True, second_worker)  # type: ignore[arg-type]

    assert first_dialog.closed is True
    assert assistant._update_dialog is not first_dialog
    assistant._begin_update(first_release, first_dialog)  # type: ignore[arg-type]
    assert assistant._update_download_worker is None
    assistant.shutdown()


def test_starting_download_cancels_overlapping_update_check(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()

    class CheckWorker:
        cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    class Dialog:
        def show_downloading(self) -> None:
            pass

    class Pool:
        def __init__(self) -> None:
            self.started: list[Any] = []

        def start(self, worker: Any) -> None:
            self.started.append(worker)

    monkeypatch.setattr(floating, "is_installed_build", lambda: True)
    monkeypatch.setattr(
        floating.QStandardPaths,
        "writableLocation",
        lambda _location: str(tmp_path),
    )
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant._thread_pool = Pool()  # type: ignore[assignment]
    dialog = Dialog()
    assistant._update_dialog = dialog  # type: ignore[assignment]
    check_worker = CheckWorker()
    assistant._update_check_worker = check_worker  # type: ignore[assignment]
    assistant._update_check_manual_requested = True
    assistant.settings_panel.set_update_status("正在检查更新…", checking=True)
    asset = UpdateAsset("setup.exe", "https://example.invalid/setup.exe", 5, "0" * 64)
    release = ReleaseInfo("0.3.0", "v0.3.0", "", asset)

    assistant._begin_update(release, dialog)  # type: ignore[arg-type]

    assert check_worker.cancelled is True
    assert assistant._update_check_worker is None
    assert assistant._update_check_manual_requested is False
    assert assistant.settings_panel.check_update_button.isEnabled()
    assert len(assistant._thread_pool.started) == 1  # type: ignore[attr-defined]
    assistant.shutdown()


def test_cancelled_update_ignores_late_worker_signals_and_releases_results(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _application()

    class Worker:
        def __init__(self, completed_path: Path) -> None:
            self.completed_path: Path | None = completed_path
            self.completed_release: ReleaseInfo | None = release
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    class Dialog:
        def __init__(self) -> None:
            self.cancelled_count = 0
            self.progress: list[tuple[int, int]] = []
            self.errors: list[str] = []

        def show_cancelled(self) -> None:
            self.cancelled_count += 1

        def set_download_progress(self, received: int, total: int) -> None:
            self.progress.append((received, total))

        def show_error(self, message: str) -> None:
            self.errors.append(message)

    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    installer = tmp_path / "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    asset = UpdateAsset(installer.name, "https://example.invalid", 5, "0" * 64)
    release = ReleaseInfo("0.3.0", "v0.3.0", "", asset)
    worker = Worker(installer)
    dialog = Dialog()
    released: list[Path] = []
    monkeypatch.setattr(
        floating,
        "release_verified_installer",
        lambda path: released.append(Path(path)),
    )
    assistant._update_download_worker = worker  # type: ignore[assignment]
    assistant._update_dialog = dialog  # type: ignore[assignment]

    assistant._cancel_update(dialog)  # type: ignore[arg-type]
    assistant._update_download_progress(1, 2, worker)  # type: ignore[arg-type]
    assistant._update_downloaded(installer, release, worker)  # type: ignore[arg-type]
    assistant._update_download_failed("late failure", worker)  # type: ignore[arg-type]

    assert worker.cancelled is True
    assert worker.completed_path is None
    assert assistant._update_download_worker is None
    assert assistant._pending_update_install is None
    assert dialog.cancelled_count == 1
    assert dialog.progress == []
    assert dialog.errors == []
    assert released == [installer, installer]
    assistant.shutdown()


@pytest.mark.parametrize("terminal", ("recognition", "shutdown"))
def test_cancelled_waiting_install_never_launches(
    terminal: str,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _application()

    class RecognitionWorker:
        def cancel(self) -> None:
            pass

    class Dialog:
        def show_cancelled(self) -> None:
            pass

    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    installer = tmp_path / "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    asset = UpdateAsset(installer.name, "https://example.invalid", 5, "0" * 64)
    release = ReleaseInfo("0.3.0", "v0.3.0", "", asset)
    launched: list[Path] = []
    released: list[Path] = []
    monkeypatch.setattr(
        floating,
        "launch_verified_installer",
        lambda path, *_args, **_kwargs: launched.append(Path(path)) or True,
    )
    monkeypatch.setattr(
        floating,
        "release_verified_installer",
        lambda path: released.append(Path(path)),
    )
    assistant._worker = RecognitionWorker()  # type: ignore[assignment]
    assistant._pending_update_install = (installer, release)
    assistant._update_dialog = Dialog()  # type: ignore[assignment]

    assistant._cancel_update()
    if terminal == "recognition":
        assistant._recognition_finished(RecognitionResult("x", "test", 0.1))
    else:
        assistant.shutdown()

    assert launched == []
    assert released == [installer]
    if terminal == "recognition":
        assistant.shutdown()


def test_update_waits_for_active_recognition_before_starting_installer(
    tmp_path: Path, monkeypatch: Any, caplog: Any
) -> None:
    _application()
    caplog.set_level("INFO", logger=floating.__name__)
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
    assert "update-backend-close-finished" in caplog.text
    assert "result=closed" in caplog.text
    assert f"asset={installer.name}" in caplog.text
    assert "kind=full" in caplog.text
    assert "elapsed_ms=" in caplog.text
    assert "result=started" in caplog.text


def test_shutdown_launches_pending_installer_exactly_once(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    settings = _settings(tmp_path)
    settings.setValue("updates/last_check_utc", 123)
    assistant = FloatingFormulaAssistant(settings=settings)
    installer = tmp_path / "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    installer.write_bytes(b"setup")
    asset = UpdateAsset(installer.name, "https://example.invalid", 5, "0" * 64)
    release = ReleaseInfo("0.3.0", "v0.3.0", "", asset)
    launches: list[Path] = []
    monkeypatch.setattr(
        floating,
        "launch_verified_installer",
        lambda path, *_args, **_kwargs: launches.append(path) or True,
    )
    assistant._pending_update_install = (installer, release)

    assistant.shutdown()
    assistant.shutdown()

    assert launches == [installer]
    assert assistant._pending_update_install is None
    assert settings.value("updates/last_check_utc") is not None


def test_shutdown_failed_pending_installer_clears_update_throttle(
    tmp_path: Path, monkeypatch: Any, caplog: Any
) -> None:
    _application()
    settings = _settings(tmp_path)
    settings.setValue("updates/last_check_utc", 123)
    assistant = FloatingFormulaAssistant(settings=settings)
    installer = tmp_path / "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    installer.write_bytes(b"setup")
    asset = UpdateAsset(installer.name, "https://example.invalid", 5, "0" * 64)
    release = ReleaseInfo("0.3.0", "v0.3.0", "", asset)
    monkeypatch.setattr(floating, "launch_verified_installer", lambda *_a, **_kw: False)
    assistant._pending_update_install = (installer, release)

    assistant.shutdown()

    assert settings.value("updates/last_check_utc") is None
    assert "update-installer-start-failed" in caplog.text


def test_startup_settings_and_preferences_are_applied(tmp_path: Path) -> None:
    application = _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant.show()
    application.processEvents()

    assert assistant.settings_panel.isVisible()
    assert assistant.orb.isHidden()
    preferences = FloatingPreferences("mathcraft", "green", "light", False)
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
    created: list[tuple[Any, Any, str, dict[str, Any]]] = []

    class Hook:
        def connect(self, _callback: Any) -> None:
            pass

    class Signals:
        finished = Hook()
        failed = Hook()

    class FakeWorker:
        signals = Signals()

        def __init__(
            self,
            manager: Any,
            image: Any,
            mode: str,
            **kwargs: Any,
        ) -> None:
            created.append((manager, image, mode, kwargs))

    class Pool:
        started: Any = None

        def start(self, worker: Any) -> None:
            self.started = worker

    monkeypatch.setattr(floating, "RecognitionWorker", FakeWorker)
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant.preferences = FloatingPreferences("mathcraft", "blue", "dark", True)
    assistant._thread_pool = Pool()  # type: ignore[assignment]
    pixmap = QPixmap(80, 40)
    pixmap.fill(Qt.GlobalColor.white)

    assistant._captured(pixmap)

    assert created[0][2] == "mathcraft"
    assert assistant._last_image is None
    assert created[0][3] == {
        "ai_enabled": False,
        "ai_api_key": None,
        "ai_base_url": "",
        "ai_model": "",
    }
    assistant._worker = None
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_capture_during_model_warmup_is_queued_then_started_once(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _application()
    created: list[Any] = []
    started: list[Any] = []

    class Hook:
        def connect(self, _callback: Any) -> None:
            pass

    class Signals:
        finished = Hook()
        failed = Hook()

    class FakeWorker:
        signals = Signals()

        def __init__(self, _manager: Any, image: Any, *_args: Any, **_kwargs: Any) -> None:
            self.image = image.copy()
            created.append(self)

    class Pool:
        def start(self, worker: Any) -> None:
            started.append(worker)

    monkeypatch.setattr(floating, "RecognitionWorker", FakeWorker)
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant._thread_pool = Pool()  # type: ignore[assignment]
    assistant._model_warmup_state = "warming"
    assistant._warmup_worker = object()  # type: ignore[assignment]
    pixmap = QPixmap(80, 40)
    pixmap.fill(Qt.GlobalColor.white)

    assistant._captured(pixmap)

    pending = assistant._pending_recognition_image
    assert pending is not None
    assert created == []
    assert "完成后自动识别" in assistant.orb.toolTip()

    assistant._model_warmup_finished()

    assert assistant._pending_recognition_image is None
    assert created == started
    assert len(created) == 1
    with pytest.raises(ValueError):
        pending.getpixel((0, 0))
    created[0].image.close()
    assistant._worker = None
    assistant.shutdown()
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_cancelled_capture_waiting_for_warmup_is_released_and_not_started(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant._model_warmup_state = "warming"
    assistant._warmup_worker = object()  # type: ignore[assignment]
    starts: list[Any] = []
    monkeypatch.setattr(assistant, "_start_recognition", starts.append)
    pixmap = QPixmap(80, 40)
    pixmap.fill(Qt.GlobalColor.white)
    assistant._captured(pixmap)
    pending = assistant._pending_recognition_image
    assert pending is not None

    assistant._cancel_current_recognition()
    assistant._model_warmup_finished()

    assert starts == []
    assert assistant._pending_recognition_image is None
    assert assistant._recognition_cancel_requested is False
    assert assistant.orb._busy is False
    assert assistant._can_start_capture()
    with pytest.raises(ValueError):
        pending.getpixel((0, 0))
    assistant.shutdown()


def test_shutdown_releases_capture_waiting_for_model(
    tmp_path: Path,
) -> None:
    _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    assistant._model_warmup_state = "warming"
    pixmap = QPixmap(80, 40)
    pixmap.fill(Qt.GlobalColor.white)
    assistant._captured(pixmap)
    pending = assistant._pending_recognition_image
    assert pending is not None

    assistant.shutdown()

    assert assistant._pending_recognition_image is None
    with pytest.raises(ValueError):
        pending.getpixel((0, 0))
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_enabled_ai_configuration_is_passed_to_worker(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _application()
    key_store = FakeApiKeyStore("unit-test-token")
    monkeypatch.setattr(floating, "OpenAIApiKeyStore", lambda: key_store)
    created: list[dict[str, Any]] = []

    class Hook:
        def connect(self, _callback: Any) -> None:
            pass

    class Signals:
        finished = Hook()
        failed = Hook()

    class FakeWorker:
        signals = Signals()

        def __init__(self, *_args: Any, **kwargs: Any) -> None:
            created.append(kwargs)

    class Pool:
        def start(self, _worker: Any) -> None:
            pass

    monkeypatch.setattr(floating, "RecognitionWorker", FakeWorker)
    settings = _settings(tmp_path)
    settings.setValue("recognition/ai_correction_enabled", True)
    settings.setValue("recognition/ai_base_url", "https://api.openai.com/v1")
    settings.setValue("recognition/ai_model", "gpt-5.6-luna")
    assistant = FloatingFormulaAssistant(settings=settings)
    assistant._thread_pool = Pool()  # type: ignore[assignment]
    pixmap = QPixmap(80, 40)
    pixmap.fill(Qt.GlobalColor.white)

    assistant._captured(pixmap)

    assert created == [
        {
            "ai_enabled": True,
            "ai_api_key": "unit-test-token",
            "ai_base_url": "https://api.openai.com/v1",
            "ai_model": "gpt-5.6-luna",
        }
    ]
    assistant._worker = None
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_draft_provider_change_disables_ai_before_replacement_key_capture(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _application()
    key_store = FakeApiKeyStore("provider-a-key")
    monkeypatch.setattr(floating, "OpenAIApiKeyStore", lambda: key_store)
    created: list[dict[str, Any]] = []

    class Hook:
        def connect(self, _callback: Any) -> None:
            pass

    class Signals:
        finished = Hook()
        failed = Hook()

    class FakeWorker:
        signals = Signals()

        def __init__(self, *_args: Any, **kwargs: Any) -> None:
            self.ai_enabled = bool(kwargs["ai_enabled"])
            created.append(kwargs)

    class Pool:
        def start(self, _worker: Any) -> None:
            pass

    monkeypatch.setattr(floating, "RecognitionWorker", FakeWorker)
    settings = _settings(tmp_path)
    saved = FloatingPreferences(
        ai_correction_enabled=True,
        ai_base_url="https://provider-a.example/v1",
        ai_model="provider-a-model",
    )
    saved.save(settings)
    assistant = FloatingFormulaAssistant(settings=settings)
    assistant._thread_pool = Pool()  # type: ignore[assignment]

    assistant.settings_panel.ai_base_url_input.setText(
        "https://provider-b.example/v1"
    )
    assert assistant.preferences.ai_correction_enabled is False
    assert settings_ui._boolean(
        settings.value("recognition/ai_correction_enabled"), True
    ) is False

    assistant.settings_panel.ai_api_key_input.setText("provider-b-key")
    assistant.settings_panel.ai_save_key_button.click()
    assistant.settings_panel.close()
    settings.sync()
    restarted_settings = QSettings(settings.fileName(), QSettings.Format.IniFormat)

    assert key_store.key == "provider-b-key"
    assert FloatingPreferences.load(restarted_settings).ai_correction_enabled is False
    assert settings.value("recognition/ai_base_url") == "https://provider-a.example/v1"
    assert all(
        "provider-b-key" not in str(settings.value(key)) for key in settings.allKeys()
    )

    pixmap = QPixmap(80, 40)
    pixmap.fill(Qt.GlobalColor.white)
    assistant._captured(pixmap)

    assert created == [
        {
            "ai_enabled": False,
            "ai_api_key": None,
            "ai_base_url": "https://provider-a.example/v1",
            "ai_model": "provider-a-model",
        }
    ]
    assistant._worker = None
    assistant.shutdown()
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_capture_conversion_failure_clears_qimage_before_showing_error(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _application()
    monkeypatch.setattr(
        floating,
        "qimage_to_pil",
        lambda _image: (_ for _ in ()).throw(ValueError("转换失败")),
    )
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    pixmap = QPixmap(80, 40)
    pixmap.fill(Qt.GlobalColor.white)

    assistant._captured(pixmap)

    assert assistant._last_image is None
    assert assistant._worker is None
    assert "无法处理截图" in assistant.panel.preview_message.text()
    assistant.panel.close()
    assert assistant._last_image is None
    assistant.orb.close()
    assistant.settings_panel.hide()


def test_both_recognition_failures_do_not_retain_capture_qimage(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    application = _application()

    class Manager:
        def recognize(self, _image: Any, _backend_key: str) -> RecognitionResult:
            raise RuntimeError("local failure")

    monkeypatch.setattr(
        worker_module,
        "transcribe_formula",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("AI failure")),
    )
    assistant = FloatingFormulaAssistant(
        settings=_settings(tmp_path),
        manager=Manager(),  # type: ignore[arg-type]
    )
    assistant.preferences = FloatingPreferences(ai_correction_enabled=True)
    assistant._api_key_store = FakeApiKeyStore("unit-test-token")  # type: ignore[assignment]
    pixmap = QPixmap(80, 40)
    pixmap.fill(Qt.GlobalColor.white)

    assistant._captured(pixmap)
    assert assistant._last_image is None

    deadline = time.monotonic() + 3
    while assistant._worker is not None and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(5)

    assert assistant._worker is None
    assert "本地识别失败" in assistant.panel.preview_message.text()
    assert "AI 识别失败" in assistant.panel.preview_message.text()
    assert assistant._last_image is None
    assistant.panel.close()
    assert assistant._last_image is None
    assistant.orb.close()
    assistant.settings_panel.hide()


@pytest.mark.parametrize("terminal", ("success", "failure", "cancel"))
def test_recognition_terminal_signals_release_worker_and_image(
    terminal: str,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    application = _application()
    local = RecognitionResult("local-x", "MathCraft", 0.1)

    class Manager:
        def recognize(self, _image: Any, _backend_key: str) -> RecognitionResult:
            if terminal == "failure":
                raise RuntimeError("local failure")
            return local

    if terminal == "cancel":
        def cancel_before_ai_delivery(
            _image: Any,
            _api_key: str,
            **kwargs: Any,
        ) -> RecognitionCandidate:
            kwargs["cancel_event"].set()
            return RecognitionCandidate(
                "stale-ai-y", "AI · vision-model", 0.2, source="ai"
            )

        monkeypatch.setattr(worker_module, "transcribe_formula", cancel_before_ai_delivery)

    assistant = FloatingFormulaAssistant(
        settings=_settings(tmp_path),
        manager=Manager(),  # type: ignore[arg-type]
    )
    # A one-thread pool makes the sentinel run on the same Qt pool thread as
    # the worker. The global pool can choose another idle thread and leave the
    # completed Python runnable in the original thread's bounded cache.
    assistant._thread_pool = QThreadPool()
    assistant._thread_pool.setMaxThreadCount(1)
    assistant.preferences = FloatingPreferences(
        ai_correction_enabled=terminal == "cancel",
    )
    assistant._api_key_store = FakeApiKeyStore("unit-test-token")  # type: ignore[assignment]
    pixmap = QPixmap(80, 40)
    pixmap.fill(Qt.GlobalColor.white)

    assistant._captured(pixmap)
    assert assistant._last_image is None
    worker = assistant._worker
    assert worker is not None
    worker_ref = weakref.ref(worker)
    image_ref = weakref.ref(worker.image)

    deadline = time.monotonic() + 3
    while assistant._worker is not None and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(5)
    assert assistant._worker is None
    if terminal == "failure":
        assert assistant._last_result is None
    else:
        assert assistant._last_result is not None
        assert assistant._last_result.latex == "local-x"
        if terminal == "cancel":
            assert "已取消" in assistant._last_result.warnings[-1]
    assert image_ref() is None

    del worker
    # PySide's global pool may retain its most recently completed Python runnable.
    # Advancing it with a sentinel distinguishes that bounded cache from a signal
    # callback cycle, while the heavyweight screenshot must already be released.
    sentinel = QRunnable.create(lambda: None)
    sentinel.setAutoDelete(False)
    assistant._thread_pool.start(sentinel)
    assert assistant._thread_pool.waitForDone(3000)
    del sentinel
    deadline = time.monotonic() + 3
    while worker_ref() is not None and time.monotonic() < deadline:
        application.processEvents()
        gc.collect()
        QTest.qWait(5)

    assert worker_ref() is None
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_cancelled_queued_ai_result_is_replaced_with_local_result(
    tmp_path: Path,
) -> None:
    _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    local = RecognitionResult("local-x", "MathCraft", 0.1)
    stale_ai = RecognitionResult(
        "stale-ai-y",
        "MathCraft + vision-model",
        0.2,
        "ai-assisted",
    )

    class QueuedWorker:
        cancelled = False
        ai_enabled = True

        def cancel_ai(self) -> None:
            self.cancelled = True

        def result_for_delivery(self, result: RecognitionResult) -> RecognitionResult:
            assert result is stale_ai
            if not self.cancelled:
                return result
            return RecognitionResult(
                local.latex,
                local.backend_name,
                local.elapsed_seconds,
                local.strategy,
                ("AI 辅助已取消，已保留本地结果。",),
            )

        def release_resources(self) -> None:
            pass

    worker = QueuedWorker()
    assistant._worker = worker  # type: ignore[assignment]
    assistant.orb.set_busy(True)

    # Credential changes can happen after Qt has queued the finished signal.
    assistant._cancel_active_recognition()
    assistant._worker_recognition_finished(worker, stale_ai)  # type: ignore[arg-type]

    assert assistant._worker is None
    assert assistant._last_result is not None
    assert assistant._last_result.latex == "local-x"
    assert assistant._last_result.strategy != "ai-assisted"
    assert assistant.orb._busy is False
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


@pytest.mark.parametrize("terminal", ("finished", "failed"))
def test_cancelled_running_recognition_converges_without_presenting_output(
    terminal: str,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _application()

    class Worker:
        ai_enabled = False

        def __init__(self) -> None:
            self.cancelled = False
            self.release_count = 0

        def cancel(self) -> None:
            self.cancelled = True

        def result_for_delivery(
            self, result: RecognitionResult
        ) -> RecognitionResult:
            return result

        def release_resources(self) -> None:
            self.release_count += 1

    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    worker = Worker()
    assistant._worker = worker  # type: ignore[assignment]
    assistant.orb.set_busy(True)
    monkeypatch.setattr(
        assistant.panel,
        "show_result",
        lambda *_args: pytest.fail("cancelled result must stay hidden"),
    )
    monkeypatch.setattr(
        assistant.panel,
        "show_error",
        lambda *_args: pytest.fail("cancelled failure must stay hidden"),
    )

    assistant._cancel_current_recognition()
    if terminal == "finished":
        assistant._worker_recognition_finished(
            worker,  # type: ignore[arg-type]
            RecognitionResult("late", "test", 0.1),
        )
    else:
        assistant._worker_recognition_failed(worker, "late")  # type: ignore[arg-type]

    assert worker.cancelled is True
    assert worker.release_count == 1
    assert assistant._worker is None
    assert assistant._recognition_cancel_requested is False
    assert assistant.orb._busy is False
    assert assistant._pending_error is None
    assert assistant._can_start_capture()
    assistant.shutdown()


def test_stale_worker_signals_do_not_change_current_worker_state(tmp_path: Path) -> None:
    _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    class StaleWorker:
        release_count = 0

        def release_resources(self) -> None:
            self.release_count += 1

    old_worker = StaleWorker()
    current_worker = object()
    retained = RecognitionResult("current-local", "MathCraft", 0.1)
    assistant._worker = current_worker  # type: ignore[assignment]
    assistant._last_result = retained
    assistant.orb.set_busy(True)

    assistant._worker_recognition_finished(  # type: ignore[arg-type]
        old_worker,
        RecognitionResult("stale-ai", "AI", 0.2, "ai-assisted"),
    )
    assistant._worker_recognition_failed(old_worker, "stale failure")  # type: ignore[arg-type]

    assert assistant._worker is current_worker
    assert assistant._last_result is retained
    assert assistant.orb._busy is True
    assert assistant._pending_error is None
    assert old_worker.release_count == 2
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


def test_settings_round_trip_preserves_edited_local_result_source(tmp_path: Path) -> None:
    application = _application()
    assistant = FloatingFormulaAssistant(settings=_settings(tmp_path))
    local = RecognitionCandidate("local-x", "MathCraft", 0.2, source="local")
    ai = RecognitionCandidate("ai-y", "AI · vision-model", 0.3, source="ai")
    assistant._recognition_finished(
        RecognitionResult(
            ai.latex,
            ai.backend,
            0.35,
            "ai-parallel",
            alternatives=(local, ai),
            comparison="different",
        )
    )
    assistant.panel.local_result_button.click()
    assistant.panel.latex_view.setPlainText("local-edited")

    assistant.open_settings()
    assistant.enter_floating_mode()
    application.processEvents()

    assert assistant.panel.local_result_button.isChecked()
    assert not assistant.panel.ai_result_button.isChecked()
    assert "MathCraft" in assistant.panel.backend_label.text()
    assert assistant.panel.latex_view.toPlainText() == "local-edited"
    assistant.panel.copy_latex_button.click()
    assert QApplication.clipboard().text() == "local-edited"
    assert assistant._last_result_source is None
    QApplication.clipboard().clear()
    assistant.orb.close()
    assistant.panel.close()
    assistant.settings_panel.hide()


def test_cancelled_recapture_preserves_edited_local_source_and_mathml(
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
    local = RecognitionCandidate("local-x", "MathCraft", 0.2, source="local")
    ai = RecognitionCandidate("ai-y", "AI · vision-model", 0.3, source="ai")
    assistant._recognition_finished(
        RecognitionResult(
            ai.latex,
            ai.backend,
            0.35,
            "ai-parallel",
            alternatives=(local, ai),
            comparison="different",
        )
    )
    assistant.panel.local_result_button.click()
    assistant.panel.latex_view.setPlainText("local-edited")

    assistant.start_capture()
    assert len(scheduled) == 1
    assistant._capture_cancelled()
    application.processEvents()

    assert assistant.panel.local_result_button.isChecked()
    assert not assistant.panel.ai_result_button.isChecked()
    assert "MathCraft" in assistant.panel.backend_label.text()
    assert assistant.panel.latex_view.toPlainText() == "local-edited"
    assistant.panel.copy_mathml_button.click()
    assert converted == ["local-edited"]
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
