"""Bounded, best-effort diagnostics without image, LaTeX or user path data."""

from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

_LOGGER = logging.getLogger("formulasnip")
_initialized = False


class _QuietRotatingHandler(RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802
        # Disk-full, read-only and rotation failures must not interrupt the GUI.
        pass


def log_exception(event: str, error: BaseException) -> None:
    frames: list[str] = []
    trace = error.__traceback__
    while trace is not None:
        code = trace.tb_frame.f_code
        frames.append(f"{Path(code.co_filename).name}:{trace.tb_lineno}:{code.co_name}")
        trace = trace.tb_next
    # Exception messages and traceback source lines can contain user content.
    _LOGGER.error("%s error=%s frames=%s", event, type(error).__name__, " > ".join(frames))


def initialize_logging(*, worker: bool = False) -> None:
    global _initialized
    if _initialized:
        return
    try:
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            return
        directory = Path(base) / "FormulaSnip" / "logs"
        directory.mkdir(parents=True, exist_ok=True)
        handler = _QuietRotatingHandler(
            directory / ("paddle-worker.log" if worker else "application.log"),
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s pid=%(process)d %(name)s %(message)s"
        ))
        _LOGGER.addHandler(handler)
        _LOGGER.setLevel(logging.INFO)
        _LOGGER.propagate = False
        _initialized = True
    except (OSError, ValueError):
        return

    previous_hook = sys.excepthook

    def exception_hook(
        kind: type[BaseException], error: BaseException, trace: TracebackType | None
    ) -> None:
        log_exception("uncaught-python-exception", error)
        previous_hook(kind, error, trace)

    previous_thread_hook = threading.excepthook

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        log_exception("uncaught-thread-exception", args.exc_value)
        previous_thread_hook(args)

    sys.excepthook = exception_hook
    threading.excepthook = thread_hook
    _LOGGER.info("runtime-start worker=%s", worker)
