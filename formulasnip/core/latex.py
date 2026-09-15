from __future__ import annotations

import re

from formulasnip.exceptions import FormulaSnipError

_DISPLAY_WRAPPERS = (("$$", "$$"), ("\\[", "\\]"), ("$", "$"))
_WORD_GROUP_COMMANDS = ("mathbb", "mathbf", "mathrm", "mathcal", "mathsf", "mathtt")
_UNSUPPORTED_WORD_MARKERS = (
    "\\begin",
    "\\end",
    "\\eqarray",
    "\\Middle",
    "\\dsmash",
)


def normalize_latex(value: str) -> str:
    """Trim common display delimiters without changing mathematical content."""

    normalized = value.strip()
    for opening, closing in _DISPLAY_WRAPPERS:
        if normalized.startswith(opening) and normalized.endswith(closing):
            normalized = normalized[len(opening) : -len(closing)].strip()
            break
    return normalized


def latex_to_mathml(value: str) -> str:
    """Convert LaTeX to presentation MathML for clipboard exchange."""

    latex = normalize_latex(value)
    if not latex:
        raise FormulaSnipError("没有可转换的 LaTeX。")
    try:
        from latex2mathml.converter import convert
    except ImportError as exc:  # pragma: no cover - dependency is part of the app install
        raise FormulaSnipError("缺少 latex2mathml，无法生成 MathML。") from exc
    try:
        return convert(latex)
    except Exception as exc:
        raise FormulaSnipError(f"MathML 转换失败：{exc}") from exc


def latex_to_word_linear(value: str) -> str:
    """Convert a deliberately small LaTeX subset to Word-friendly UnicodeMath.

    Word's COM API does not expose a switch that forces arbitrary input to be
    parsed as LaTeX. Reject complex environments instead of silently inserting
    misleading plain text.
    """

    latex = normalize_latex(value)
    if not latex:
        raise FormulaSnipError("没有可插入 Word 的公式。")
    if any(marker in latex for marker in _UNSUPPORTED_WORD_MARKERS):
        raise FormulaSnipError(
            "这条公式包含 Word 第一版暂不支持的复杂 LaTeX 环境，"
            "请复制 LaTeX 后人工插入。"
        )
    converted = _convert_fragment(latex)
    converted = re.sub(r"\s+", " ", converted).strip()
    if not converted:
        raise FormulaSnipError("公式转换后为空。")
    return converted


def _read_group(text: str, start: int, opening: str = "{", closing: str = "}") -> tuple[str, int]:
    if start >= len(text) or text[start] != opening:
        raise FormulaSnipError("公式括号结构不完整，无法安全转换。")
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start + 1 : index], index + 1
    raise FormulaSnipError("公式括号结构不完整，无法安全转换。")


def _convert_fragment(text: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(text):
        if _starts_control_word(text, index, "left"):
            index += len("\\left")
            continue
        if _starts_control_word(text, index, "right"):
            index += len("\\right")
            continue
        if text.startswith("\\frac", index):
            cursor = _skip_space(text, index + len("\\frac"))
            numerator, cursor = _read_group(text, cursor)
            cursor = _skip_space(text, cursor)
            denominator, cursor = _read_group(text, cursor)
            output.append(f"({_convert_fragment(numerator)})/({_convert_fragment(denominator)})")
            index = cursor
            continue
        if text.startswith("\\sqrt", index):
            cursor = _skip_space(text, index + len("\\sqrt"))
            root_index: str | None = None
            if cursor < len(text) and text[cursor] == "[":
                root_index, cursor = _read_group(text, cursor, "[", "]")
                cursor = _skip_space(text, cursor)
            radicand, cursor = _read_group(text, cursor)
            body = _convert_fragment(radicand)
            if root_index is None:
                output.append(f"\\sqrt({body})")
            else:
                output.append(f"\\sqrt({_convert_fragment(root_index)}&{body})")
            index = cursor
            continue

        matched_group_command = False
        for command in _WORD_GROUP_COMMANDS:
            token = f"\\{command}"
            if text.startswith(token, index):
                cursor = _skip_space(text, index + len(token))
                content, cursor = _read_group(text, cursor)
                output.append(f"{token}({_convert_fragment(content)})")
                index = cursor
                matched_group_command = True
                break
        if matched_group_command:
            continue

        char = text[index]
        if char in "_^" and index + 1 < len(text) and text[index + 1] == "{":
            content, cursor = _read_group(text, index + 1)
            output.append(f"{char}({_convert_fragment(content)})")
            index = cursor
            continue
        if char == "{":
            content, cursor = _read_group(text, index)
            output.append(f"({_convert_fragment(content)})")
            index = cursor
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _skip_space(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _starts_control_word(text: str, index: int, command: str) -> bool:
    """Return whether an exact LaTeX control word starts at ``index``."""

    token = f"\\{command}"
    if not text.startswith(token, index):
        return False
    following = index + len(token)
    return following >= len(text) or not text[following].isalpha()
