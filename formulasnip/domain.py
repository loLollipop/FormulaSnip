from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecognitionCandidate:
    """One backend prediction retained by an adaptive recognition run."""

    latex: str
    backend: str
    elapsed_seconds: float
    issues: tuple[str, ...] = ()
    previewable: bool = True
    source: str = ""


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    """Normalized result returned by every recognition backend."""

    latex: str
    backend_name: str
    elapsed_seconds: float
    strategy: str = "single"
    warnings: tuple[str, ...] = ()
    alternatives: tuple[RecognitionCandidate, ...] = ()
    comparison: str = "not_compared"
