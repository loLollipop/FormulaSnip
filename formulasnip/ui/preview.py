from __future__ import annotations

from io import BytesIO

from formulasnip.core.latex import normalize_latex


def render_formula_svg(latex: str) -> bytes:
    """Render common LaTeX as a scalable vector formula."""

    normalized = normalize_latex(latex)
    if not normalized:
        raise ValueError("公式预览内容为空")
    from matplotlib.mathtext import math_to_image

    buffer = BytesIO()
    math_to_image(
        f"${normalized}$",
        buffer,
        format="svg",
        color="#172033",
    )
    svg = buffer.getvalue()
    if b"<svg" not in svg:
        raise ValueError("电子公式预览生成失败")
    return svg
