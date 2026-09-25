from xml.etree import ElementTree as ET

import pytest

from formulasnip.core.latex import (
    MATHTYPE_MATHML_CLIPBOARD_FORMATS,
    latex_equivalent,
    latex_same_content,
    latex_to_mathml,
    latex_to_word_linear,
    normalize_latex,
)
from formulasnip.exceptions import FormulaSnipError


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("  $$x^2$$  ", "x^2"),
        ("\\[ \\frac{a}{b} \\]", "\\frac{a}{b}"),
        ("$x$", "x"),
        ("x+y", "x+y"),
    ],
)
def test_normalize_latex(source: str, expected: str) -> None:
    assert normalize_latex(source) == expected


def test_word_linear_converts_common_formula() -> None:
    source = r"\frac{x_1+1}{\sqrt{y^2}}"
    assert latex_to_word_linear(source) == r"(x_1+1)/(\sqrt(y^2))"


def test_word_linear_converts_limits_and_root_index() -> None:
    source = r"\int_{0}^{\infty}\sqrt[3]{x}\,dx"
    assert latex_to_word_linear(source) == r"\int_(0)^(\infty)\sqrt(3&x)\,dx"


def test_word_linear_only_removes_standalone_delimiter_commands() -> None:
    source = r"\left( x \right) + \leftarrow + \rightarrow + \leftrightarrow"
    assert latex_to_word_linear(source) == (
        r"( x ) + \leftarrow + \rightarrow + \leftrightarrow"
    )


def test_word_linear_rejects_complex_environment() -> None:
    with pytest.raises(FormulaSnipError):
        latex_to_word_linear(r"\begin{matrix}a&b\\c&d\end{matrix}")


def test_latex_to_mathml_returns_math_root() -> None:
    mathml = latex_to_mathml(r"\frac{a}{b}")
    assert "<math" in mathml
    assert "<mfrac>" in mathml
    root = ET.fromstring(mathml)
    assert root.attrib["display"] == "block"
    style = next(iter(root))
    assert style.tag.rsplit("}", 1)[-1] == "mstyle"
    assert style.attrib["displaystyle"] == "true"
    assert style.attrib["scriptlevel"] == "0"
    assert MATHTYPE_MATHML_CLIPBOARD_FORMATS == (
        'application/x-qt-windows-mime;value="MathML Presentation"',
        "MathML Presentation",
        "application/mathml-presentation+xml",
        'application/x-qt-windows-mime;value="MathML"',
        "MathML",
        "application/mathml+xml",
    )


def test_latex_to_mathml_preserves_single_letter_roman_style() -> None:
    root = ET.fromstring(latex_to_mathml(r"\int f(x)\,\mathrm{d}x"))
    roman_d = [
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "mi"
        and (element.text or "") == "d"
    ]

    assert len(roman_d) == 1
    assert roman_d[0].attrib["mathvariant"] == "normal"


def test_latex_to_mathml_does_not_rewrite_mathrm_inside_verb() -> None:
    root = ET.fromstring(latex_to_mathml(r"\verb|\mathrm{x}|"))
    verbatim = [
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "mtext"
    ]

    assert len(verbatim) == 1
    assert verbatim[0].text == r"\mathrm{x}"


@pytest.mark.parametrize(
    "latex",
    [
        r"\def\A{{\B}{\B}}\def\B{x}\A",
        r"\def0{{1}{1}}\def1{x}0",
        r"\def_{{1}{1}}\def1{x}_",
        r"\defΩ{{1}{1}}\def1{x}Ω",
        r"\newcommand{\A}{x}\A",
        r"\newenvironment{A}{x}{y}\begin{A}\end{A}",
        r"\DeclareMathOperator{\foo}{foo}\foo",
    ],
)
def test_latex_to_mathml_rejects_custom_macro_definitions(latex: str) -> None:
    with pytest.raises(FormulaSnipError, match="自定义宏"):
        latex_to_mathml(latex)


@pytest.mark.parametrize(
    ("local", "ai"),
    (
        (r"  { x  +  y } ", r"x+y"),
        (r"a\!+\,b", r"a+b"),
        (r"\left( x+y \right)", r"(x+y)"),
    ),
)
def test_latex_equivalent_ignores_only_layout_differences(local: str, ai: str) -> None:
    assert latex_equivalent(local, ai)


@pytest.mark.parametrize(
    ("local", "ai"),
    (
        (r"q_{\mathrm{loss}}", r"q_{loss}"),
        (r"\rho c_{\mathrm p}", r"\rho c_p"),
        (r"\vec{AB}", r"\overrightarrow{AB}"),
        (r"\tilde{AB}", r"\widetilde{AB}"),
        (r"\leftarrow", r"\rightarrow"),
        (r"\text{a b}", r"\text{ab}"),
        (r"x_1", r"x_2"),
        (
            r"\begin{gathered}x=1\\y=2\end{gathered}",
            r"\begin{gathered}x=1y=2\end{gathered}",
        ),
        (
            r"\begin{gather}x=1\\y=2\end{gather}",
            r"\begin{gather}x=1y=2\end{gather}",
        ),
        (
            r"\begin{matrix}a&b\\c&d\end{matrix}",
            r"\begin{matrix}a&b\\d&c\end{matrix}",
        ),
    ),
)
def test_latex_equivalent_preserves_semantic_differences(local: str, ai: str) -> None:
    assert not latex_equivalent(local, ai)


def test_latex_equivalent_returns_false_when_conversion_fails() -> None:
    assert not latex_equivalent(r"\begin{matrix}", r"\begin{matrix}")


def test_latex_same_content_accepts_compact_ai_single_letter_subscript() -> None:
    local = (
        r"\rho c _ { \mathrm { p } } \frac { \partial T } { \partial t } "
        r"= \frac 1 r \frac { \partial } { \partial r }"
    )
    ai = r"\rho c_p\frac{\partial T}{\partial t}=\frac{1}{r}\frac{\partial}{\partial r}"

    assert not latex_equivalent(local, ai)
    assert latex_same_content(local, ai)


def test_latex_same_content_accepts_unbraced_single_letter_roman_subscript() -> None:
    assert latex_same_content(r"c_{\mathrm p}", r"c_p")


@pytest.mark.parametrize(
    ("local", "ai"),
    (
        (r"\verb|_{\mathrm{p}}|", r"\verb|_{p}|"),
        (r"\text{label_{\mathrm{p}}}", r"\text{label_{p}}"),
        (r"\operatorname{rate_{\mathrm{p}}}", r"\operatorname{rate_{p}}"),
        (r"c\_{\mathrm p}", r"c\_{p}"),
        (r"\text{a\} b c}", r"\text{a\} bc}"),
        (r"\text{a {b\} c} d}", r"\text{a {b\} cd}"),
    ),
)
def test_latex_same_content_does_not_rewrite_opaque_contexts(
    local: str, ai: str
) -> None:
    assert not latex_same_content(local, ai)


@pytest.mark.parametrize(
    ("local", "ai"),
    (
        (r"q_{\mathrm{loss}}", r"q_{loss}"),
        (r"c_{\mathbf{p}}", r"c_p"),
    ),
)
def test_latex_same_content_keeps_semantic_font_differences(
    local: str, ai: str
) -> None:
    assert not latex_same_content(local, ai)


def test_latex_same_content_handles_escaped_brace_before_math_subscript() -> None:
    assert latex_same_content(
        r"\text{literal \} brace}c_{\mathrm p}",
        r"\text{literal \} brace}c_p",
    )


def _mathml_tokens(mathml: str) -> list[tuple[str, str, dict[str, str]]]:
    root = ET.fromstring(mathml)
    return [
        (element.tag.rsplit("}", 1)[-1], "".join(element.itertext()), element.attrib)
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] in {"mi", "mo", "mspace"}
    ]


def test_mathml_materializes_mathtype_operator_spacing() -> None:
    tokens = _mathml_tokens(latex_to_mathml(r"a=b+c"))

    assert ("mo", "=", {"lspace": "0em", "rspace": "0em"}) in tokens
    assert ("mo", "+", {"lspace": "0em", "rspace": "0em"}) in tokens
    widths = [
        attributes["width"]
        for name, _text, attributes in tokens
        if name == "mspace"
    ]
    assert widths == ["0.278em", "0.278em", "0.222em", "0.222em"]


@pytest.mark.parametrize(
    ("source", "expected_widths"),
    (
        (r"a+b", ["0.222em", "0.222em"]),
        (r"a\!+b", ["negativethinmathspace", "0.222em"]),
        (r"a+\!b", ["0.222em", "negativethinmathspace"]),
        (r"a\!+\!b", ["negativethinmathspace", "negativethinmathspace"]),
        (r"a\;+\;b", ["0.278em", "0.278em"]),
    ),
)
def test_mathml_preserves_explicit_operator_spacing_per_side(
    source: str,
    expected_widths: list[str],
) -> None:
    tokens = _mathml_tokens(latex_to_mathml(source))

    assert [
        attributes["width"]
        for name, _text, attributes in tokens
        if name == "mspace"
    ] == expected_widths
    assert ("mo", "+", {"lspace": "0em", "rspace": "0em"}) in tokens


def test_mathml_does_not_space_prefix_minus_or_fences() -> None:
    tokens = _mathml_tokens(latex_to_mathml(r"-x+f(-y)"))

    operators = [
        (text, attributes)
        for name, text, attributes in tokens
        if name == "mo"
    ]
    assert operators[0] == ("−", {})
    assert operators[1] == ("+", {"lspace": "0em", "rspace": "0em"})
    assert operators[2] == ("(", {"stretchy": "false"})
    assert operators[3] == ("−", {})
    assert operators[4] == (")", {"stretchy": "false"})


def test_mathml_does_not_space_binary_operator_at_end_or_before_closing_fence() -> None:
    trailing = _mathml_tokens(latex_to_mathml(r"x+"))
    before_fence = _mathml_tokens(latex_to_mathml(r"f(x+)"))

    assert not any(name == "mspace" for name, _text, _attributes in trailing)
    assert not any(name == "mspace" for name, _text, _attributes in before_fence)


def test_mathml_reclassifies_plus_minus_and_preserves_explicit_binary_width() -> None:
    plus_minus = _mathml_tokens(latex_to_mathml(r"x\pm y"))
    explicit_binary = _mathml_tokens(latex_to_mathml(r"x\mathbin{+}y"))

    assert ("mo", "±", {"lspace": "0em", "rspace": "0em"}) in plus_minus
    assert [
        attributes["width"]
        for name, _text, attributes in explicit_binary
        if name == "mspace"
    ] == ["0.22em", "0.22em"]


def test_mathml_respects_explicit_ord_and_materializes_unknown_mathbin() -> None:
    ordinary = _mathml_tokens(latex_to_mathml(r"x\mathord{+}y"))
    ordinary_plus_minus = _mathml_tokens(latex_to_mathml(r"x\mathord{\pm}y"))
    explicit_binary = _mathml_tokens(latex_to_mathml(r"x\mathbin{\star}y"))

    assert not any(name == "mspace" for name, _text, _attributes in ordinary)
    assert not any(
        name == "mspace" for name, _text, _attributes in ordinary_plus_minus
    )
    assert [
        attributes["width"]
        for name, _text, attributes in explicit_binary
        if name == "mspace"
    ] == ["0.22em", "0.22em"]


def test_mathml_materializes_spacing_inside_display_style() -> None:
    tokens = _mathml_tokens(latex_to_mathml(r"\displaystyle a=b"))

    assert ("mo", "=", {"lspace": "0em", "rspace": "0em"}) in tokens
    assert [
        attributes["width"]
        for name, _text, attributes in tokens
        if name == "mspace"
    ] == ["0.278em", "0.278em"]
