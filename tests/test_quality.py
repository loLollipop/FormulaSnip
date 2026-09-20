import pytest
from PIL import Image, ImageDraw

from formulasnip.recognition.quality import (
    assess_latex,
    diagnose_image,
    has_clean_partial_command,
    has_complex_image_layout,
    has_complex_structure,
    has_suspected_derivative_confusion,
)


def test_quality_detects_malformed_patterns_deterministically() -> None:
    report = assess_latex("frac{x}{y--z")
    assert report.issues == (
        "括号不配对",
        "疑似缺少反斜杠：frac",
        "疑似重复运算符",
    )
    assert report.score == 40


def test_quality_allows_negative_arrow_and_control_words() -> None:
    assert assess_latex(r"-x + \sqrt{x} \longrightarrow y").issues == ()


@pytest.mark.parametrize(
    "latex",
    (r"\text{(}", r"\operatorname{foo(}", r"\verb|(|"),
)
def test_quality_ignores_delimiters_in_literal_contexts(latex: str) -> None:
    assert "括号不配对" not in assess_latex(latex).issues


def test_quality_still_detects_real_unbalanced_grouping() -> None:
    assert "括号不配对" in assess_latex(r"\frac{x}{y").issues


def test_quality_checks_environments_and_left_right_pairs() -> None:
    valid = (
        r"\begin{cases}\begin{matrix}a & b \\ c & d\end{matrix}\end{cases}"
        r"+\left(x\right)"
    )
    assert assess_latex(valid).issues == ()

    assert "LaTeX 环境开始与结束不匹配" in assess_latex(
        r"\begin{matrix}x\end{cases}"
    ).issues
    assert "LaTeX 环境开始与结束不匹配" in assess_latex(
        r"\begin{cases}\begin{matrix}x\end{cases}\end{matrix}"
    ).issues
    assert r"\left 与 \right 数量不平衡" in assess_latex(r"\left. x").issues


def test_quality_detects_unescaped_repeated_relation_and_token_run() -> None:
    assert "疑似重复关系符 ==" in assess_latex("x == y").issues
    assert "疑似重复关系符 ==" not in assess_latex(r"x \== y").issues
    assert "疑似重复关系符 ==" not in assess_latex(
        r"\text{C == C++} + \textbf{A == B} + \emph{x == y} + \verb|==|"
    ).issues
    assert "输出含相同符号异常连续重复" in assess_latex(
        " ".join([r"\alpha"] * 8)
    ).issues
    assert assess_latex(r"\text{a a a a a a a a}").issues == ()
    assert assess_latex(" ".join(["x"] * 8)).issues == ()
    assert assess_latex(r"x+\cdots+\begin{matrix}0&0&0&0\end{matrix}").issues == ()


def test_quality_honors_backslash_parity_before_commands() -> None:
    assert assess_latex(r"\\\begin{matrix}x\end{matrix}").issues == ()
    assert assess_latex(r"\\\left(x\right)").issues == ()


def test_quality_detects_long_and_repetitive_output() -> None:
    assert "输出异常过长" in assess_latex(" a" * 500).issues
    assert "输出含异常重复片段" in assess_latex(r"\alpha+x" * 20).issues


def test_quality_allows_legitimate_repeated_math() -> None:
    formulas = (
        r"\begin{pmatrix}0&0&0&0\\0&0&0&0\\0&0&0&0\\0&0&0&0\end{pmatrix}",
        r"\frac{x}{y}+\frac{x}{y}+\frac{x}{y}+\frac{x}{y}",
    )

    for formula in formulas:
        assert "输出含异常重复片段" not in assess_latex(formula).issues


def test_complex_structure_detection() -> None:
    assert has_complex_structure(r"\int_0^1 x dx")
    assert has_complex_structure(r"\begin{cases}x&x>0\end{cases}")
    assert has_complex_structure(r"\frac{u}{x}+\frac{v}{y}")
    assert has_complex_structure(r"\partial_t u+\nabla u")
    assert has_complex_structure(r"\begin{aligned}x&=y\end{aligned}")
    assert not has_complex_structure(r"x+y")


@pytest.mark.parametrize(
    "latex",
    (
        r"\partial_t u",
        r"\nabla u",
        r"\frac{a}{b}+\frac{c}{d}",
        r"\begin{align}x&=y\end{align}",
        r"\begin{aligned}x&=y\end{aligned}",
        r"\begin{array}{cc}a&b\end{array}",
        r"\begin{gathered}x=y\end{gathered}",
        r"\begin{split}x=y\end{split}",
        r"\begin{multline}x=y\end{multline}",
    ),
)
def test_all_precision_routing_structures_are_complex(latex: str) -> None:
    assert has_complex_structure(latex)


def test_image_diagnostics_are_hints() -> None:
    small = Image.new("L", (30, 10), 128)
    assert diagnose_image(small) == ("图片尺寸偏小", "图片对比度偏低")

    image = Image.new("L", (100, 50), "white")
    ImageDraw.Draw(image).rectangle((0, 10, 20, 30), fill="black")
    assert "公式前景可能触边" in diagnose_image(image)


def test_complex_image_layout_uses_foreground_not_rapid_text() -> None:
    simple = Image.new("L", (180, 60), "white")
    ImageDraw.Draw(simple).rectangle((20, 20, 150, 40), fill="black")
    assert not has_complex_image_layout(simple)

    long_two_dimensional = Image.new("L", (260, 90), "white")
    ImageDraw.Draw(long_two_dimensional).rectangle((20, 20, 230, 65), fill="black")
    assert has_complex_image_layout(long_two_dimensional)

    large_single_line = Image.new("L", (120, 80), "white")
    ImageDraw.Draw(large_single_line).rectangle((20, 15, 99, 60), fill="black")
    assert not has_complex_image_layout(large_single_line)


@pytest.mark.parametrize("latex", (
    r"\frac{partial u}{partial x}",
    r"\hat{\partial} u",
    r"\widetilde\partial_t u",
))
def test_derivative_confusions_are_review_hints_without_rewriting(latex: str) -> None:
    assert has_suspected_derivative_confusion(latex)
    assert any("疑似偏导" in issue for issue in assess_latex(latex).issues)


@pytest.mark.parametrize("latex", (
    r"\frac{\partial u}{\partial x}",
    r"\frac{\tilde C u}{\tilde Q t}",
    r"\frac{\widetilde{\sigma} u}{x}",
    r"\frac{u}{\widetilde C x}",
    r"\frac{\hat C u}{\bar Q t}",
    r"\frac{\overline{x}}{\ddot y}",
    r"\tilde x + \widetilde\sigma",
    r"\frac{\text{partial}}{x}",
    r"\text{\frac{\tilde C}{x}}",
))
def test_ordinary_math_and_literal_text_do_not_trigger_derivative_hint(latex: str) -> None:
    assert not has_suspected_derivative_confusion(latex)


@pytest.mark.parametrize(
    ("latex", "expected"),
    (
        (r"\frac{\partial u}{\partial x}", True),
        (r"\hat{\partial}u", False),
        (r"\frac{partial u}{partial x}", False),
        (r"\text{\partial}", False),
    ),
)
def test_clean_partial_command_requires_an_unaccented_math_token(
    latex: str, expected: bool
) -> None:
    assert has_clean_partial_command(latex) is expected
