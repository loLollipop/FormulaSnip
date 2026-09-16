from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from PIL import Image

from formulasnip.exceptions import RecognitionError
from formulasnip.recognition.paddle_backend import PaddleFormulaBackend, _extract_formula
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


def test_paddle_parses_real_result_shape_and_cleans_style_commands() -> None:
    class Result:
        json = {"res": {"rec_formula": r"\textstyle \frac{x}{y}"}}

    class Model:
        def predict(self, *, input: np.ndarray[Any, Any], batch_size: int) -> list[Result]:
            assert input.flags.c_contiguous
            assert batch_size == 1
            return [Result()]

    backend = PaddleFormulaBackend()
    backend._model = Model()
    result = backend.recognize(Image.new("RGB", (30, 20), "white"))

    assert result.latex == r"\frac{x}{y}"
    assert _extract_formula({"res": {"rec_formula": "z"}}) == "z"


def test_paddle_rejects_excessively_long_output() -> None:
    class Model:
        def predict(self, **_kwargs: Any) -> list[dict[str, dict[str, str]]]:
            return [{"res": {"rec_formula": r"\alpha+x" * 130}}]

    backend = PaddleFormulaBackend()
    backend._model = Model()

    with pytest.raises(RecognitionError, match="输出异常"):
        backend.recognize(Image.new("RGB", (30, 20), "white"))


@pytest.mark.parametrize(
    "formula",
    (
        r"\begin{pmatrix}0&0&0&0\\0&0&0&0\\0&0&0&0\\0&0&0&0\end{pmatrix}",
        r"\frac{x}{y}+\frac{x}{y}+\frac{x}{y}+\frac{x}{y}",
    ),
)
def test_paddle_keeps_legitimate_repeated_math(formula: str) -> None:
    class Model:
        def predict(self, **_kwargs: Any) -> list[dict[str, dict[str, str]]]:
            return [{"res": {"rec_formula": formula}}]

    backend = PaddleFormulaBackend()
    backend._model = Model()

    assert backend.recognize(Image.new("RGB", (30, 20), "white")).latex == formula


def test_paddle_keeps_legitimate_repeated_text() -> None:
    class Model:
        def predict(self, **_kwargs: Any) -> list[dict[str, dict[str, str]]]:
            return [{"res": {"rec_formula": r"\text{a a a a a a a a}"}}]

    backend = PaddleFormulaBackend()
    backend._model = Model()

    result = backend.recognize(Image.new("RGB", (30, 20), "white"))

    assert result.latex == r"\text{a a a a a a a a}"


def test_paddle_does_not_treat_an_ordinary_bracket_issue_as_fatal() -> None:
    class Model:
        def predict(self, **_kwargs: Any) -> list[dict[str, dict[str, str]]]:
            return [{"res": {"rec_formula": r"\frac{x}{y"}}]

    backend = PaddleFormulaBackend()
    backend._model = Model()

    assert backend.recognize(Image.new("RGB", (30, 20), "white")).latex == r"\frac{x}{y"
