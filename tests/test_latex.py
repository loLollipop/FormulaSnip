import pytest

from formulasnip.core.latex import latex_to_mathml, latex_to_word_linear, normalize_latex
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
