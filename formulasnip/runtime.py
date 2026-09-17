"""Runtime setup shared by the GUI and spawned model processes (no Qt imports)."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, TextIO

_windowed_streams: list[TextIO] = []


def _configure_windowed_streams() -> None:
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
            _windowed_streams.append(stream)
            setattr(sys, name, stream)


def _configure_windowed_subprocesses() -> None:
    """Hide console helpers only in a Windows frozen/windowed application.

    Keep Popen a class, preserve caller flags, and respect explicit console or
    detached-process requests. Qt's installer launch is intentionally unaffected.
    """

    if (
        sys.platform != "win32"
        or not getattr(sys, "frozen", False)
        or (sys.stdout is not None and sys.stderr is not None)
        or getattr(subprocess.Popen, "_formulasnip_windowed", False)
    ):
        return
    original = subprocess.Popen

    class WindowedPopen(original):  # type: ignore[misc, valid-type]
        _formulasnip_windowed = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            flags = args[13] if len(args) > 13 else kwargs.get("creationflags", 0)
            if not flags & (0x00000010 | 0x00000008):  # NEW_CONSOLE | DETACHED_PROCESS
                flags |= 0x08000000  # CREATE_NO_WINDOW
                if len(args) > 13:
                    args = (*args[:13], flags, *args[14:])
                else:
                    kwargs["creationflags"] = flags
            super().__init__(*args, **kwargs)

    subprocess.Popen = WindowedPopen


def configure_runtime() -> None:
    _configure_windowed_subprocesses()
    _configure_windowed_streams()
