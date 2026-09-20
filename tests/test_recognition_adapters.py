from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from PIL import Image

from formulasnip.exceptions import RecognitionError
from formulasnip.recognition.mathcraft_backend import _InProcessMathCraftBackend


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
    assert runtimes[0].warmups == ["formula"]
    assert len(runtimes[0].images) == 1
    assert runtimes[0].images[0].mode == "RGB"
    assert runtimes[0].images[0].size == (48, 24)
