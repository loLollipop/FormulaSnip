from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image, ImageStat

_BARE_COMMAND = re.compile(r"(?<!\\)\b(frac|sqrt)\s*\{")
_REPEATED_OPERATOR = re.compile(r"(?<!-)--(?![-=>])|(?<!\+)\+\+(?!\+)")
_COMPLEX_STRUCTURE = re.compile(
    r"\\(?:int|iint|iiint|oint|sum|prod|lim)(?![A-Za-z])"
    r"|\\begin\s*\{(?:matrix|pmatrix|bmatrix|cases)\}"
)
_TOKEN = re.compile(r"\\[A-Za-z]+|[A-Za-z0-9]+|\S")


@dataclass(frozen=True, slots=True)
class QualityReport:
    issues: tuple[str, ...]
    score: int


def assess_latex(latex: str) -> QualityReport:
    """Return deterministic syntax heuristics, not model confidence."""

    issues: list[str] = []
    if _has_unbalanced_delimiters(latex):
        issues.append("括号不配对")
    bare = sorted(set(_BARE_COMMAND.findall(latex)))
    if bare:
        issues.append("疑似缺少反斜杠：" + "、".join(bare))
    if _REPEATED_OPERATOR.search(latex):
        issues.append("疑似重复运算符")

    tokens = _TOKEN.findall(latex)
    if len(latex) > 900 or len(tokens) > 160:
        issues.append("输出异常过长")
    if _has_repeated_fragment(latex):
        issues.append("输出含异常重复片段")
    return QualityReport(tuple(issues), max(0, 100 - 20 * len(issues)))


def diagnose_image(image: Image.Image) -> tuple[str, ...]:
    """Describe routing risks without altering the image or claiming confidence."""

    width, height = image.size
    issues: list[str] = []
    if width < 48 or height < 20:
        issues.append("图片尺寸偏小")
    if width > height * 14 or height > width * 4:
        issues.append("图片长宽比极端")

    gray = image.convert("L")
    if ImageStat.Stat(gray).stddev[0] < 10:
        issues.append("图片对比度偏低")
    if _foreground_touches_edge(gray):
        issues.append("公式前景可能触边")
    return tuple(issues)


def has_complex_structure(latex: str) -> bool:
    return _COMPLEX_STRUCTURE.search(latex) is not None


def has_fatal_output_issue(latex: str) -> bool:
    issues = assess_latex(latex).issues
    return "输出异常过长" in issues or "输出含异常重复片段" in issues


def _has_unbalanced_delimiters(value: str) -> bool:
    pairs = {"}": "{", "]": "[", ")": "("}
    stack: list[str] = []
    escaped = False
    for char in value:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in pairs.values():
            stack.append(char)
        elif char in pairs and (not stack or stack.pop() != pairs[char]):
            return True
    return bool(stack)


def _has_repeated_fragment(value: str) -> bool:
    compact = re.sub(r"\s+", " ", value).strip()
    for size in range(8, min(65, len(compact) // 3 + 1)):
        for start in range(0, len(compact) - size * 3 + 1):
            fragment = compact[start : start + size]
            if len(set(fragment)) > 2 and fragment * 3 in compact:
                return True
    return False


def _foreground_touches_edge(gray: Image.Image) -> bool:
    width, height = gray.size
    if width < 3 or height < 3:
        return False
    pixels = gray.load()
    corners = (
        pixels[0, 0],
        pixels[width - 1, 0],
        pixels[0, height - 1],
        pixels[width - 1, height - 1],
    )
    background = sum(corners) / len(corners)
    threshold = 35
    edge = [pixels[x, 0] for x in range(width)]
    edge += [pixels[x, height - 1] for x in range(width)]
    edge += [pixels[0, y] for y in range(1, height - 1)]
    edge += [pixels[width - 1, y] for y in range(1, height - 1)]
    changed = sum(abs(pixel - background) > threshold for pixel in edge)
    return changed / len(edge) > 0.03
