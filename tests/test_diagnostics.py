from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

import pytest

from formulasnip import diagnostics


def test_logs_are_bounded_and_exceptions_exclude_private_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = logging.getLogger("formulasnip-test-diagnostics")
    monkeypatch.setattr(diagnostics, "_LOGGER", logger)
    monkeypatch.setattr(diagnostics, "_initialized", False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # Preserve interpreter hooks after this test.
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    try:
        diagnostics.initialize_logging()
        handler = logger.handlers[0]
        assert handler.maxBytes == 1_000_000  # type: ignore[attr-defined]
        assert handler.backupCount == 2  # type: ignore[attr-defined]
        try:
            raise RuntimeError("secret formula and C:/private/user/image.png")
        except RuntimeError as exc:
            diagnostics.log_exception("recognition-failed", exc)
        handler.flush()
        content = (tmp_path / "FormulaSnip/logs/application.log").read_text(encoding="utf-8")
        assert "RuntimeError" in content
        assert "test_diagnostics.py" in content
        assert "secret formula" not in content
        assert "C:/private" not in content
        assert str(tmp_path) not in content
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


def test_logging_initialization_failure_is_nonfatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(diagnostics, "_initialized", False)
    base = tmp_path / "not-a-directory"
    base.touch()
    monkeypatch.setenv("LOCALAPPDATA", str(base))
    diagnostics.initialize_logging()
    assert not diagnostics._initialized
