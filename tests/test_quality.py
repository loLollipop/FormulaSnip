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


def test_quality_detects_long_and_repetitive_output() -> None:
    report = assess_latex((r"\alpha+x" * 4) + (" a" * 260))
    assert "输出异常过长" in report.issues
    assert "输出含异常重复片段" in report.issues


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
