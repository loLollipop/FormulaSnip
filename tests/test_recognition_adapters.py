from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

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
