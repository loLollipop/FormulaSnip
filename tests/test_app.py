from __future__ import annotations

import sys
from typing import Any

from formulasnip import app


def test_after_update_argument_is_consumed_before_qt() -> None:
    argv, after_update = app._consume_startup_arguments(
        ["FormulaSnip.exe", "-platform", "offscreen", "--after-update"]
    )

    assert argv == ["FormulaSnip.exe", "-platform", "offscreen"]
    assert after_update is True


def test_normal_arguments_do_not_enable_after_update() -> None:
    argv, after_update = app._consume_startup_arguments(
        ["FormulaSnip.exe", "-platform", "offscreen"]
    )

    assert argv == ["FormulaSnip.exe", "-platform", "offscreen"]
    assert after_update is False


def test_run_application_shows_before_scheduling_warmups(monkeypatch: Any) -> None:
    from formulasnip.ui import floating

    events: list[Any] = []

    class Signal:
        def connect(self, callback: Any) -> None:
            events.append(("connect", callback.__name__))

    class Application:
        aboutToQuit = Signal()

        def setQuitOnLastWindowClosed(self, value: bool) -> None:  # noqa: N802
            events.append(("keep-alive", value))

        def exec(self) -> int:
            events.append("exec")
            return 17

    class Assistant:
        def show(self, *, after_update: bool = False) -> None:
            events.append(("show", after_update))

        def start_model_warmup(self) -> None:
            pass

        def start_preview_warmup(self) -> None:
            pass

        def start_update_checks(self) -> None:
            events.append("updates")

        def shutdown(self) -> None:
            events.append("shutdown")

    application = Application()
    assistant = Assistant()
    monkeypatch.setattr(app, "create_application", lambda argv: application)
    monkeypatch.setattr(floating, "FloatingFormulaAssistant", lambda: assistant)
    monkeypatch.setattr(
        app.QTimer,
        "singleShot",
        lambda delay, callback: events.append(("warmup", delay, callback.__name__)),
    )

    assert app._run_application(["FormulaSnip.exe"], after_update=True) == 17
    assert events.index(("show", True)) < events.index(
        ("warmup", app.MODEL_WARMUP_DELAY_MS, "start_model_warmup")
    )
    assert events.index(("show", True)) < events.index(
        ("warmup", app.PREVIEW_WARMUP_DELAY_MS, "start_preview_warmup")
    )
    assert app.MODEL_WARMUP_DELAY_MS > 0
    assert app.PREVIEW_WARMUP_DELAY_MS > app.MODEL_WARMUP_DELAY_MS
    assert events.count("shutdown") == 1


def test_second_instance_exits_before_application_creation(monkeypatch: Any) -> None:
    monkeypatch.setattr(app.multiprocessing, "freeze_support", lambda: None)
    monkeypatch.setattr(app.SingleInstanceGuard, "acquire", lambda self: False)
    monkeypatch.setattr(app, "create_application",
                        lambda: (_ for _ in ()).throw(AssertionError("created app")))
    assert app.main() == 0


def test_windows_mutex_is_per_user_and_released() -> None:
    import pytest

    from formulasnip.single_instance import SingleInstanceGuard

    if sys.platform != "win32":
        pytest.skip("Windows kernel mutex")
    first, second, restarted = (SingleInstanceGuard() for _ in range(3))
    try:
        assert first.acquire()
        assert not second.acquire()
        first.close()
        assert restarted.acquire()
    finally:
        first.close()
        second.close()
        restarted.close()


def test_non_windows_guard_degrades_without_os_calls(monkeypatch: Any) -> None:
    from formulasnip import single_instance

    monkeypatch.setattr(single_instance.sys, "platform", "linux")
    guard = single_instance.SingleInstanceGuard()
    assert guard.acquire()
    guard.close()


def test_windowed_streams_are_writable_when_bootloader_omits_them(
    monkeypatch: Any,
) -> None:
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    app._configure_windowed_streams()

    replacement_stdout = sys.stdout
    replacement_stderr = sys.stderr
    assert replacement_stdout is not None
    assert replacement_stderr is not None
    assert replacement_stdout.writable()
    assert replacement_stderr.writable()

    monkeypatch.setattr(sys, "stdout", original_stdout)
    monkeypatch.setattr(sys, "stderr", original_stderr)
    replacement_stdout.close()
    replacement_stderr.close()
