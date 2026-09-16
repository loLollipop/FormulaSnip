from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from threading import RLock

from formulasnip.core.latex import normalize_latex

_RENDER_LOCK = RLock()


def render_formula_svg(latex: str) -> bytes:
    """Render common LaTeX as SVG without depending on Qt."""

    normalized = normalize_latex(latex)
    if not normalized:
        raise ValueError("公式预览内容为空")
    svg = _render_formula_svg(normalized)
    if svg is None:
        raise ValueError("当前 LaTeX 无法生成电子公式预览")
    return svg


def is_formula_previewable(latex: str) -> bool:
    """Return whether the exact renderer used by the UI accepts ``latex``."""

    normalized = normalize_latex(latex)
    return bool(normalized and _render_formula_svg(normalized) is not None)


@lru_cache(maxsize=64)
def _render_formula_svg(normalized: str) -> bytes | None:
    """Cache both successful and rejected previews for candidate evaluation."""

    # Matplotlib does not guarantee thread safety. Candidate checks happen in
    # a worker thread while edited previews are rendered on the GUI thread, so
    # serialize cache misses through the same renderer.
    with _RENDER_LOCK:
        buffer = BytesIO()
        try:
            from matplotlib.mathtext import math_to_image

            math_to_image(
                f"${normalized}$",
                buffer,
                format="svg",
                color="#172033",
            )
        except Exception:
            return None
        svg = buffer.getvalue()
    return svg if b"<svg" in svg else None
