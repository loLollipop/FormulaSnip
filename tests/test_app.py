from __future__ import annotations

import sys
from typing import Any

from formulasnip import app


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
