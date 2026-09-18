from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO

import pytest

from formulasnip.__main__ import _run_preview_smoke_test
from formulasnip.core import preview


@pytest.fixture(autouse=True)
def clear_preview_cache() -> Iterator[None]:
    preview._render_formula_svg.cache_clear()
    yield
    preview._render_formula_svg.cache_clear()


def test_renders_pde_formula_from_reported_preview_failure() -> None:
    latex = (
        r"\frac{\partial u}{\partial t}"
        r"+u\frac{\partial u}{\partial x}"
        r"=\nu\frac{\partial^2u}{\partial x^2}"
    )

    svg = preview.render_formula_svg(latex)

    assert svg.startswith(b"<?xml")
    assert b"<svg" in svg
    assert preview.is_formula_previewable(latex)


def test_packaged_preview_smoke_entry_point() -> None:
    assert _run_preview_smoke_test() == 0


def test_successful_svg_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    from matplotlib import mathtext

    original = mathtext.math_to_image
    calls = 0

    def counting_math_to_image(*args: object, **kwargs: object) -> float:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(mathtext, "math_to_image", counting_math_to_image)

    first = preview.render_formula_svg(r"x^2+y^2")
    second = preview.render_formula_svg(r"x^2+y^2")

    assert first == second
    assert calls == 1


def test_runtime_failure_is_logged_without_being_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from matplotlib import mathtext

    original = mathtext.math_to_image
    calls = 0
    logged: list[tuple[str, type[BaseException]]] = []

    def flaky_math_to_image(
        expression: str,
        output: BytesIO,
        **kwargs: object,
    ) -> float:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError(f"temporary SVG failure for {expression}")
        return original(expression, output, **kwargs)

    def record_exception(event: str, error: BaseException) -> None:
        logged.append((event, type(error)))

    monkeypatch.setattr(mathtext, "math_to_image", flaky_math_to_image)
    monkeypatch.setattr(preview, "log_exception", record_exception)
    private_latex = r"\frac{\partial secret_user_formula}{\partial t}"

    assert not preview.is_formula_previewable(private_latex)
    assert preview.is_formula_previewable(private_latex)
    assert preview.is_formula_previewable(private_latex)
    assert calls == 2
    assert logged == [("formula-preview-render-failed", RuntimeError)]
    assert all("secret_user_formula" not in event for event, _error_type in logged)


@pytest.mark.parametrize("latex", [r"\frac{x}{y", r"\notacommand{x}"])
def test_invalid_or_unsupported_latex_remains_unpreviewable(latex: str) -> None:
    assert not preview.is_formula_previewable(latex)
    with pytest.raises(ValueError, match="无法生成电子公式预览"):
        preview.render_formula_svg(latex)
