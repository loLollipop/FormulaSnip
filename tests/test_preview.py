from __future__ import annotations

import html as html_module
import re

import pytest

from formulasnip.__main__ import _run_preview_smoke_test
from formulasnip.core import preview


@pytest.mark.parametrize(
    "latex",
    (
        r"\begin{matrix}a & b \\ c & d\end{matrix}",
        r"f(x)=\begin{cases}x^2,&x\ge0\\-x,&x<0\end{cases}",
        r"\begin{aligned}a&=b+c\\d&=e-f\end{aligned}",
        r"\notacommand{x}",
    ),
)
def test_worker_preflight_accepts_structurally_valid_mathjax_input(latex: str) -> None:
    assert preview.is_formula_previewable(latex)


@pytest.mark.parametrize(
    "latex",
    (
        "",
        "   ",
        "x\x00y",
        r"\frac{x}{y",
        r"\begin{matrix}x\end{cases}",
        r"\end{matrix}",
    ),
)
def test_worker_preflight_rejects_empty_or_unbalanced_input(latex: str) -> None:
    assert not preview.is_formula_previewable(latex)


def test_mathjax_html_escapes_formula_as_text_and_not_javascript() -> None:
    latex = r"x & y < z > 0 \text{'quoted'} </div><script>alert(1)</script>"

    document = preview.build_mathjax_html(latex, 41)

    formula_match = re.search(r'<div id="formula">\\\[(.*?)\\\]</div>', document)
    assert formula_match is not None
    encoded_formula = formula_match.group(1)
    assert html_module.unescape(encoded_formula) == latex
    assert "</div><script>alert(1)</script>" not in document
    assert "&lt;/div&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in document
    assert "requestId: 41" in document
    assert "connect-src 'none'" in document


def test_mathjax_html_is_offline_scrollable_and_keeps_readable_type() -> None:
    document = preview.build_mathjax_html("x+y", 1)

    assert '<script src="tex-svg-full.js"' in document
    assert "https://" not in document
    assert "http://" not in document
    assert "overflow: auto" in document
    assert "font-size: 20px" in document
    assert "font-size: 12px" in document
    assert "scale: 1.15" in document
    assert "enableMenu: false" in document
    assert "pointer-events: none" in document
    assert "mjx-merror, g[data-mml-node=\"merror\"]" in document


def test_mathjax_resource_is_vendored_as_expected() -> None:
    script = preview.mathjax_script_path()

    assert script.name == "tex-svg-full.js"
    assert script.is_file()
    assert script.stat().st_size == 2_275_146


def test_packaged_preview_smoke_entry_point() -> None:
    assert _run_preview_smoke_test() == 0
