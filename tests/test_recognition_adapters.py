from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest
from PIL import Image

from formulasnip.exceptions import RecognitionError
from formulasnip.recognition.mathcraft_backend import _InProcessMathCraftBackend
from formulasnip.recognition.rapid_backend import RapidLatexBackend


def test_rapid_passes_contiguous_rgb_array_and_uses_model_timing() -> None:
    received: list[np.ndarray[Any, Any]] = []

    def model(value: np.ndarray[Any, Any]) -> tuple[str, float]:
        received.append(value)
        return "x+y", 0.25

    backend = RapidLatexBackend()
    backend._model = model
    result = backend.recognize(Image.new("L", (20, 10), 255))

    assert received[0].shape == (10, 20, 3)
    assert received[0].flags.c_contiguous
    assert result.elapsed_seconds >= 0.25


@dataclass
class FakeResult:
    text: str


class FakeRuntime:
    def __init__(self, *, provider_preference: str, text: str = r"\frac{x}{y}") -> None:
        assert provider_preference == "cpu"
        self.text = text
        self.images: list[Image.Image] = []
        self.warmups: list[str] = []

    def recognize_formula(self, image: Image.Image) -> FakeResult:
        self.images.append(image)
        return FakeResult(self.text)

    def warmup(self, profile: str) -> None:
        self.warmups.append(profile)


def test_mathcraft_uses_injected_cpu_runtime_without_package_or_download(
    monkeypatch: Any,
) -> None:
    runtimes: list[FakeRuntime] = []

    def factory(**kwargs: Any) -> FakeRuntime:
        runtime = FakeRuntime(**kwargs, text=r"  \frac{x}{y}  ")
        runtimes.append(runtime)
        return runtime

    backend = _InProcessMathCraftBackend(runtime_factory=factory)
    monkeypatch.setattr(backend, "is_available", lambda: False)
    result = backend.recognize(Image.new("L", (30, 20), "white"))

    assert result.latex == r"\frac{x}{y}"
    assert runtimes[0].images[0].mode == "RGB"


@pytest.mark.parametrize("formula", ("", "   ", r"\alpha+x" * 130))
def test_mathcraft_rejects_empty_or_fatal_output(formula: str) -> None:
    backend = _InProcessMathCraftBackend(
        runtime_factory=lambda **kwargs: FakeRuntime(**kwargs, text=formula)
    )

    with pytest.raises(RecognitionError, match="没有返回公式|输出异常"):
        backend.recognize(Image.new("RGB", (30, 20), "white"))


@pytest.mark.parametrize(
    "formula",
    (
        r"\begin{pmatrix}0&0&0&0\\0&0&0&0\\0&0&0&0\\0&0&0&0\end{pmatrix}",
        r"\frac{x}{y}+\frac{x}{y}+\frac{x}{y}+\frac{x}{y}",
        r"\text{a a a a a a a a}",
        r"\frac{x}{y",
    ),
)
def test_mathcraft_keeps_nonfatal_output(formula: str) -> None:
    backend = _InProcessMathCraftBackend(
        runtime_factory=lambda **kwargs: FakeRuntime(**kwargs, text=formula)
    )
    assert backend.recognize(Image.new("RGB", (30, 20), "white")).latex == formula


def test_mathcraft_warmup_loads_once_and_uses_formula_profile() -> None:
    runtimes: list[FakeRuntime] = []

    def factory(**kwargs: Any) -> FakeRuntime:
        runtime = FakeRuntime(**kwargs)
        runtimes.append(runtime)
        return runtime

    backend = _InProcessMathCraftBackend(runtime_factory=factory)
    backend.warmup()
    backend.warmup()

    assert len(runtimes) == 1
    assert runtimes[0].warmups == ["formula", "formula"]


def test_rapid_warmup_only_loads_model(monkeypatch: Any) -> None:
    backend = RapidLatexBackend()
    loaded: list[bool] = []
    monkeypatch.setattr(backend, "_load_model", lambda: loaded.append(True) or object())

    backend.warmup()

    assert loaded == [True]
