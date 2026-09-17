from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from formulasnip import runtime


@pytest.mark.parametrize("flags", (0, 0x00000020, 0x00000010, 0x00000008))
@pytest.mark.parametrize("positional", (False, True))
def test_windowed_subprocess_flags_preserve_explicit_console_policy(
    monkeypatch: pytest.MonkeyPatch, flags: int, positional: bool
) -> None:
    received: list[int] = []

    class Popen:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            received.append(args[13] if len(args) > 13 else kwargs["creationflags"])

    monkeypatch.setattr(subprocess, "Popen", Popen)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with monkeypatch.context() as gui:
        gui.setattr(sys, "stdout", None)
        runtime._configure_windowed_subprocesses()
        wrapped = subprocess.Popen
        runtime._configure_windowed_subprocesses()
    assert subprocess.Popen is wrapped
    if positional:
        subprocess.Popen(*([None] * 13 + [flags]))
    else:
        subprocess.Popen(["where", "ccache"], creationflags=flags)
    assert received == [flags if flags & 0x18 else flags | 0x08000000]


@pytest.mark.parametrize(
    ("platform", "frozen", "windowed"),
    (("linux", True, True), ("win32", False, True), ("win32", True, False)),
)
def test_source_console_and_non_windows_processes_are_unchanged(
    monkeypatch: pytest.MonkeyPatch, platform: str, frozen: bool, windowed: bool
) -> None:
    original = subprocess.Popen
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    with monkeypatch.context() as gui:
        if windowed:
            gui.setattr(sys, "stdout", None)
        runtime._configure_windowed_subprocesses()
    assert subprocess.Popen is original


def test_configure_runtime_applies_both_windowed_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        runtime, "_configure_windowed_subprocesses", lambda: calls.append("subprocesses")
    )
    monkeypatch.setattr(runtime, "_configure_windowed_streams", lambda: calls.append("streams"))

    runtime.configure_runtime()

    assert calls == ["subprocesses", "streams"]
