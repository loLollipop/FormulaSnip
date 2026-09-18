from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from threading import RLock

from formulasnip.core.latex import normalize_latex
from formulasnip.diagnostics import log_exception

_RENDER_LOCK = RLock()


def render_formula_svg(latex: str) -> bytes:
    """Render common LaTeX as SVG without depending on Qt."""

    normalized = normalize_latex(latex)
    if not normalized:
        raise ValueError("公式预览内容为空")
    try:
        return _render_formula_svg(normalized)
    except Exception as exc:
        log_exception("formula-preview-render-failed", exc)
        raise ValueError("当前 LaTeX 无法生成电子公式预览") from None


def is_formula_previewable(latex: str) -> bool:
    """Return whether the exact renderer used by the UI accepts ``latex``."""

    normalized = normalize_latex(latex)
    if not normalized:
        return False
    try:
        _render_formula_svg(normalized)
    except Exception as exc:
        log_exception("formula-preview-render-failed", exc)
        return False
    return True


@lru_cache(maxsize=64)
def _render_formula_svg(normalized: str) -> bytes:
    """Render and cache successful previews; exceptions are never cached."""

    # Matplotlib does not guarantee thread safety. Candidate checks happen in
    # a worker thread while edited previews are rendered on the GUI thread, so
    # serialize cache misses through the same renderer.
    with _RENDER_LOCK:
        buffer = BytesIO()
        from matplotlib.mathtext import math_to_image

        math_to_image(
            f"${normalized}$",
            buffer,
            format="svg",
            color="#172033",
        )
        svg = buffer.getvalue()
    if b"<svg" not in svg:
        raise ValueError("SVG renderer returned no SVG document")
    return svg
