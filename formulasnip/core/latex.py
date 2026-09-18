from __future__ import annotations

import re
import xml.etree.ElementTree as ET

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
_MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML"
_MATHML_ROW_ELEMENTS = {"math", "mrow", "mstyle", "mtd"}
_MATHML_TOKEN_ELEMENTS = {"mi", "mn", "mo", "mtext", "mspace", "ms"}
_IGNORED_EQUIVALENCE_ATTRIBUTES = {
    "display",
    "displaystyle",
    "fence",
    "form",
    "lspace",
    "maxsize",
    "minsize",
    "rspace",
    "scriptlevel",
    "symmetric",
}
_MATHTYPE_BINARY_SPACE = "0.222em"
_MATHTYPE_RELATION_SPACE = "0.278em"
_BINARY_OPERATORS = frozenset(
    "+−-±∓×·⋅∙÷∗⋆∘•∪∩∨∧⊕⊖⊗⊘⊙⊎⊓⊔∖≀⋄△▽⊲⊳⊴⊵†‡⨿"
)
_RELATION_OPERATORS = frozenset(
    "=<>≤≥≠≈≡∼≃≅∝∈∉∋∌⊂⊃⊆⊇⊄⊅⊈⊉⊥∥"
)
_OPENING_FENCES = frozenset("([{⟨⌈⌊")
_CLOSING_FENCES = frozenset(")]}⟩⌉⌋")
_FENCE_TOKENS = _OPENING_FENCES | _CLOSING_FENCES
_PREFIX_PREDECESSORS = _BINARY_OPERATORS | _RELATION_OPERATORS | frozenset(",;:")
_BINARY_FOLLOWERS = (
    _BINARY_OPERATORS | _RELATION_OPERATORS | _CLOSING_FENCES | frozenset(",;:")
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
        return _make_mathml_mathtype_compatible(convert(latex))
    except Exception as exc:
        raise FormulaSnipError(f"MathML 转换失败：{exc}") from exc


def latex_equivalent(left: str, right: str) -> bool:
    """Conservatively compare mathematical structure through presentation MathML.

    The normal form discards spacing and delimiter-rendering hints, but deliberately
    keeps semantic style attributes such as ``mathvariant`` and structural nodes for
    scripts, arrows, text and tables. Any conversion or XML failure is treated as a
    non-match so a questionable pair remains visible to the user.
    """

    try:
        left_root = ET.fromstring(latex_to_mathml(left))
        right_root = ET.fromstring(latex_to_mathml(right))
    except (FormulaSnipError, ET.ParseError, ValueError, TypeError):
        return False
    return _canonical_mathml(left_root) == _canonical_mathml(right_root)


def _canonical_mathml(element: ET.Element) -> tuple[object, ...] | None:
    local_name = _local_name(element.tag)
    if local_name == "mspace":
        linebreak_attributes = tuple(
            sorted(
                (_local_name(name), value)
                for name, value in element.attrib.items()
                if _local_name(name) == "linebreak"
            )
        )
        if not linebreak_attributes:
            return None
        return local_name, linebreak_attributes, "", ()

    attributes = tuple(
        sorted(
            (_local_name(name), value)
            for name, value in element.attrib.items()
            if not _ignore_equivalence_attribute(element, name)
        )
    )
    if local_name in {"mtext", "ms"}:
        text = element.text or ""
    elif local_name in _MATHML_TOKEN_ELEMENTS:
        text = (element.text or "").strip()
    else:
        text = "" if not (element.text or "").strip() else (element.text or "").strip()
    children = tuple(
        canonical
        for child in element
        if (canonical := _canonical_mathml(child)) is not None
    )
    if local_name == "mrow" and not attributes and not text and len(children) == 1:
        return children[0]
    return local_name, attributes, text, children


def _ignore_equivalence_attribute(element: ET.Element, name: str) -> bool:
    local_name = _local_name(name)
    if local_name in _IGNORED_EQUIVALENCE_ATTRIBUTES:
        return True
    if local_name != "stretchy":
        return False
    token = (element.text or "").strip()
    return element.get("fence", "").casefold() == "true" or token in _FENCE_TOKENS


def _make_mathml_mathtype_compatible(mathml: str) -> str:
    """Materialize operator spacing for MathType's MathML importer.

    MathType 7 ignores ``mo`` lspace/rspace attributes but preserves ``mspace``
    widths. Explicit spaces plus zeroed ``mo`` spacing keep the same layout in
    standards-compliant renderers without relying on an operator dictionary.
    """

    root = ET.fromstring(mathml)
    ET.register_namespace("", _MATHML_NAMESPACE)
    _space_mathml_tree(root)
    return ET.tostring(root, encoding="unicode", short_empty_elements=True)


def _space_mathml_tree(element: ET.Element) -> None:
    local_name = _local_name(element.tag)
    if local_name in _MATHML_TOKEN_ELEMENTS:
        return
    if local_name in _MATHML_ROW_ELEMENTS:
        _space_mathml_row(element)
    for child in element:
        _space_mathml_tree(child)


def _space_mathml_row(row: ET.Element) -> None:
    children = list(row)
    rewritten: list[ET.Element] = []
    index = 0
    while index < len(children):
        child = children[index]
        operator = _operator_text(child)
        spacing = _operator_spacing(child, rewritten, children[index + 1 :])
        if spacing is None:
            rewritten.append(child)
            index += 1
            continue

        has_explicit_left_space = bool(
            rewritten and _local_name(rewritten[-1].tag) == "mspace"
        )
        has_explicit_right_space = bool(
            index + 1 < len(children)
            and _local_name(children[index + 1].tag) == "mspace"
        )
        index += 1

        if _local_name(child.tag) == "mi" and operator in {"±", "∓"}:
            child.tag = _qualified_name("mo")
        left_space = _positive_operator_space(child.get("lspace"), spacing)
        right_space = _positive_operator_space(child.get("rspace"), spacing)
        child.set("lspace", "0em")
        child.set("rspace", "0em")
        if not has_explicit_left_space:
            rewritten.append(_mathml_space(left_space))
        rewritten.append(child)
        if not has_explicit_right_space:
            rewritten.append(_mathml_space(right_space))
    row[:] = rewritten


def _operator_spacing(
    element: ET.Element,
    preceding: list[ET.Element],
    following: list[ET.Element],
) -> str | None:
    operator = _operator_text(element)
    if operator is None:
        return None
    explicit_space = element.get("lspace") or element.get("rspace")
    if explicit_space is not None:
        return explicit_space
    if operator in _RELATION_OPERATORS or any("←" <= char <= "⇿" for char in operator):
        return _MATHTYPE_RELATION_SPACE
    if operator not in _BINARY_OPERATORS:
        return None
    previous = next(
        (item for item in reversed(preceding) if _local_name(item.tag) != "mspace"),
        None,
    )
    previous_operator = _operator_text(previous) if previous is not None else None
    following_element = next(
        (item for item in following if _local_name(item.tag) != "mspace"),
        None,
    )
    following_operator = (
        _operator_text(following_element) if following_element is not None else None
    )
    if (
        previous is None
        or previous_operator in _PREFIX_PREDECESSORS
        or previous_operator in _OPENING_FENCES
    ):
        return None
    if following_element is None or following_operator in _BINARY_FOLLOWERS:
        return None
    return _MATHTYPE_BINARY_SPACE


def _operator_text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    local_name = _local_name(element.tag)
    value = "".join(element.itertext()).strip()
    if len(value) != 1:
        return None
    if local_name == "mo" or (
        local_name == "mi" and not list(element) and value in {"±", "∓"}
    ):
        return value
    return None


def _positive_operator_space(value: str | None, fallback: str) -> str:
    if value and not value.strip().lower().startswith(("-", "negative")):
        return value
    return fallback


def _mathml_space(width: str) -> ET.Element:
    return ET.Element(_qualified_name("mspace"), {"width": width})


def _qualified_name(local_name: str) -> str:
    return f"{{{_MATHML_NAMESPACE}}}{local_name}"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


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
