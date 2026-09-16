from PIL import Image, ImageDraw

from formulasnip.recognition.quality import (
    assess_latex,
    diagnose_image,
    has_complex_structure,
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
    assert not has_complex_structure(r"x+y")


def test_image_diagnostics_are_hints() -> None:
    small = Image.new("L", (30, 10), 128)
    assert diagnose_image(small) == ("图片尺寸偏小", "图片对比度偏低")

    image = Image.new("L", (100, 50), "white")
    ImageDraw.Draw(image).rectangle((0, 10, 20, 30), fill="black")
    assert "公式前景可能触边" in diagnose_image(image)
