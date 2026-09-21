from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image, ImageStat

from formulasnip.core.limits import MAX_QUALITY_SCAN_CHARS

_BARE_COMMAND = re.compile(r"(?<!\\)\b(frac|sqrt)\s*\{")
_REPEATED_OPERATOR = re.compile(r"(?<!-)--(?![-=>])|(?<!\+)\+\+(?!\+)")
_REPEATED_RELATION = re.compile(r"==")
_ENVIRONMENT = re.compile(r"\\(begin|end)\s*\{([^{}]+)\}")
_LEFT_RIGHT = re.compile(r"\\(left|right)(?![A-Za-z])")
_LITERAL_GROUP = re.compile(
    r"\\(?:text|textbf|textmd|textrm|textsf|texttt|textup|textit|textsl|textsc|"
    r"textnormal|emph|mbox|operatorname)\s*\{"
)
_VERB = re.compile(r"\\verb\*?([^\sA-Za-z])")
_COMPLEX_STRUCTURE = re.compile(
    r"\\(?:int|iint|iiint|oint|sum|prod|lim|partial|nabla)(?![A-Za-z])"
    r"|\\begin\s*\{(?:matrix|pmatrix|bmatrix|cases|aligned|align\*?|array|"
    r"gathered|split|multline\*?)\}"
)
_TOKEN = re.compile(r"\\[A-Za-z]+|[A-Za-z0-9]+|\S")
_BARE_PARTIAL = re.compile(r"(?<!\\)\bpartial\b")
_ACCENTED_PARTIAL = re.compile(
    r"\\(?:tilde|widetilde|hat|widehat|bar|overline|dot|ddot)\s*"
    r"(?:\{\s*)*\\partial(?![A-Za-z])"
)
_FRACTION = re.compile(r"\\(?:frac|dfrac|tfrac)(?![A-Za-z])\s*\{")
_PARTIAL_COMMAND = re.compile(r"\\partial(?![A-Za-z])")
DERIVATIVE_CONFUSION_ISSUE = "疑似偏导符号与重音字符混淆，请对照原图"


@dataclass(frozen=True, slots=True)
class QualityReport:
    issues: tuple[str, ...]
    score: int


def assess_latex(latex: str) -> QualityReport:
    """Return deterministic syntax heuristics, not model confidence."""

    if len(latex) > MAX_QUALITY_SCAN_CHARS:
        return QualityReport(("输出异常过长",), 0)
    issues: list[str] = []
    penalties: list[int] = []
    structural_latex = _mask_literal_contexts(latex)
    if _has_unbalanced_delimiters(structural_latex):
        issues.append("括号不配对")
        penalties.append(25)
    bare = sorted(set(_BARE_COMMAND.findall(latex)))
    if bare:
        issues.append("疑似缺少反斜杠：" + "、".join(bare))
        penalties.append(20)
    if _REPEATED_OPERATOR.search(latex):
        issues.append("疑似重复运算符")
        penalties.append(15)
    if _has_mismatched_environments(structural_latex):
        issues.append("LaTeX 环境开始与结束不匹配")
        penalties.append(30)
    if _has_unbalanced_left_right(structural_latex):
        issues.append(r"\left 与 \right 数量不平衡")
        penalties.append(25)
    if _has_repeated_relation(structural_latex):
        issues.append("疑似重复关系符 ==")
        penalties.append(15)
    if has_suspected_derivative_confusion(latex):
        issues.append(DERIVATIVE_CONFUSION_ISSUE)

    tokens = _TOKEN.findall(latex)
    structural_tokens = _TOKEN.findall(structural_latex)
    if _has_repeated_token_run(structural_tokens):
        issues.append("输出含相同符号异常连续重复")
        penalties.append(40)
    if len(latex) > 900 or len(tokens) > 160:
        issues.append("输出异常过长")
        penalties.append(50)
    if _has_repeated_fragment(structural_latex):
        issues.append("输出含异常重复片段")
        penalties.append(45)
    return QualityReport(tuple(issues), max(0, 100 - sum(penalties)))


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


def has_complex_image_layout(image: Image.Image) -> bool:
    """Conservatively route visibly two-dimensional or long formula crops.

    This signal is independent of OCR text and identifies screenshots that
    deserve extra care during manual review.
    """

    gray = image.convert("L")
    width, height = gray.size
    if width < 3 or height < 3:
        return False
    pixels = gray.load()
    corners = sorted(
        (
            pixels[0, 0],
            pixels[width - 1, 0],
            pixels[0, height - 1],
            pixels[width - 1, height - 1],
        )
    )
    background = (corners[1] + corners[2]) / 2
    foreground = gray.point(
        lambda value: 255 if abs(value - background) > 35 else 0,
        mode="1",
    )
    bounds = foreground.getbbox()
    if bounds is None:
        return False
    foreground_width = bounds[2] - bounds[0]
    foreground_height = bounds[3] - bounds[1]
    # Absolute glyph height alone mostly reflects font size. Requiring both axes
    # avoids labelling a large but ordinary one-line expression as 2-D layout.
    return foreground_width >= 180 and foreground_height >= 30


def has_complex_structure(latex: str) -> bool:
    value = _mask_literal_contexts(latex)
    if _COMPLEX_STRUCTURE.search(value) is not None:
        return True
    # Multiple fractions commonly represent derivatives or nested PDE terms.
    fractions = sum(
        1
        for match in _FRACTION.finditer(value)
        if _is_active_command(value, match.start())
    )
    return fractions >= 2


def has_suspected_derivative_confusion(latex: str) -> bool:
    """Flag model confusions, never repair symbols or assert math correctness.

    Only direct evidence is considered: a bare ``partial`` token or a
    ``\\partial`` command decorated with an accent. Ordinary accented symbols and
    text mentioning ``partial`` do not trigger this hint.
    """

    value = _mask_literal_contexts(latex)
    return bool(_BARE_PARTIAL.search(value) or _ACCENTED_PARTIAL.search(value))


def has_clean_partial_command(latex: str) -> bool:
    """Return whether an undecorated partial token survives structural checks."""

    value = _mask_literal_contexts(latex)
    return bool(
        _PARTIAL_COMMAND.search(value)
        and not _BARE_PARTIAL.search(value)
        and not _ACCENTED_PARTIAL.search(value)
    )


def has_fatal_output_issue(latex: str) -> bool:
    issues = assess_latex(latex).issues
    return "输出异常过长" in issues


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


def _has_mismatched_environments(value: str) -> bool:
    stack: list[str] = []
    for match in _ENVIRONMENT.finditer(value):
        if not _is_active_command(value, match.start()):
            continue
        kind, name = match.groups()
        name = name.strip()
        if kind == "begin":
            stack.append(name)
        elif not stack or stack.pop() != name:
            return True
    return bool(stack)


def _has_unbalanced_left_right(value: str) -> bool:
    balance = 0
    for match in _LEFT_RIGHT.finditer(value):
        if not _is_active_command(value, match.start()):
            continue
        if match.group(1) == "left":
            balance += 1
        else:
            balance -= 1
            if balance < 0:
                return True
    return balance != 0


def _has_repeated_relation(value: str) -> bool:
    return any(
        not _is_escaped_character(value, match.start())
        for match in _REPEATED_RELATION.finditer(value)
    )


def _has_repeated_token_run(tokens: list[str], threshold: int = 8) -> bool:
    previous = ""
    run_length = 0
    for token in tokens:
        repeatable = token.startswith("\\")
        if repeatable and token == previous:
            run_length += 1
        elif repeatable:
            previous = token
            run_length = 1
        else:
            previous = ""
            run_length = 0
        if run_length >= threshold:
            return True
    return False


def _mask_literal_contexts(value: str) -> str:
    """Hide literal text from math-structure checks without changing offsets."""

    masked = list(value)
    occupied: list[tuple[int, int]] = []
    for match in _VERB.finditer(value):
        if not _is_active_command(value, match.start()):
            continue
        delimiter = match.group(1)
        end = value.find(delimiter, match.end())
        if end >= 0:
            occupied.append((match.start(), end + 1))

    for match in _LITERAL_GROUP.finditer(value):
        if not _is_active_command(value, match.start()):
            continue
        end = _matching_group_end(value, match.end() - 1)
        if end is not None:
            occupied.append((match.start(), end + 1))

    for start, end in occupied:
        masked[start:end] = " " * (end - start)
    return "".join(masked)


def _matching_group_end(value: str, opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(value)):
        char = value[index]
        if char == "{" and not _is_escaped_character(value, index):
            depth += 1
        elif char == "}" and not _is_escaped_character(value, index):
            depth -= 1
            if depth == 0:
                return index
    return None


def _is_active_command(value: str, index: int) -> bool:
    backslashes = 0
    position = index - 1
    while position >= 0 and value[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 0


def _is_escaped_character(value: str, index: int) -> bool:
    return not _is_active_command(value, index)


def _has_repeated_fragment(value: str) -> bool:
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) < 96:
        return False
    minimum_repeats = 6
    for size in range(8, min(65, len(compact) // minimum_repeats + 1)):
        for start in range(0, len(compact) - size * minimum_repeats + 1):
            fragment = compact[start : start + size]
            if len(set(fragment)) <= 2:
                continue
            repeat_end = start + size
            repeat_count = 1
            while compact.startswith(fragment, repeat_end):
                repeat_count += 1
                repeat_end += size
            repeated_span = repeat_end - start
            if (
                repeat_count >= minimum_repeats
                and repeated_span >= 96
                and repeated_span >= len(compact) * 0.75
            ):
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
