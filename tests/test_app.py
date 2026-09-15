from __future__ import annotations

import sys
from typing import Any

from formulasnip import app


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
