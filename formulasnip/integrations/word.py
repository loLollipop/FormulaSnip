from __future__ import annotations

from typing import Any

from formulasnip.core.latex import latex_to_word_linear
from formulasnip.exceptions import FormulaSnipError, WordIntegrationError


def insert_formula_into_active_word(latex: str) -> str:
    """Insert a common formula subset at the active Word selection."""

    try:
        linear = latex_to_word_linear(latex)
    except FormulaSnipError:
        raise
    except Exception as exc:
        raise WordIntegrationError("公式转换失败，无法插入 Word。") from exc

    try:
        from pywintypes import com_error
        from win32com.client import GetActiveObject
    except ImportError as exc:  # pragma: no cover - Windows runtime dependency
        raise WordIntegrationError("缺少 pywin32，无法连接 Microsoft Word。") from exc
    except Exception as exc:  # pragma: no cover - defensive dependency initialization
        raise WordIntegrationError("加载 Microsoft Word 集成时发生意外错误。") from exc

    try:
        app = GetActiveObject("Word.Application")
    except com_error as exc:
        raise WordIntegrationError("没有找到正在运行的 Word，请先打开目标文档并放置光标。") from exc
    except Exception as exc:
        raise WordIntegrationError("连接 Microsoft Word 时发生意外错误。") from exc

    try:
        _insert_linear_formula(app, linear)
    except WordIntegrationError:
        raise
    except Exception as exc:
        raise WordIntegrationError(
            "Word 没有成功建立原生公式。请检查公式内容，或先使用“复制 LaTeX”。"
        ) from exc
    return linear


def _insert_linear_formula(app: Any, linear: str) -> None:
    """Insert an already converted formula, rolling back a changed selection on failure."""

    if app.Documents.Count == 0:
        raise WordIntegrationError("Word 中没有打开的文档。")
    document = app.ActiveDocument
    if bool(document.ReadOnly):
        raise WordIntegrationError("当前 Word 文档是只读的，无法插入公式。")
    # wdNoProtection is -1. Avoid generated COM constants, which may not be cached.
    if int(document.ProtectionType) != -1:
        raise WordIntegrationError("当前 Word 文档受到保护，无法插入公式。")

    selection = app.Selection
    original_range = selection.Range.Duplicate
    original_start = int(original_range.Start)
    original_end = int(original_range.End)
    original_text = str(original_range.Text or "")
    source_range = original_range.Duplicate
    equation_range = None
    mutation_started = False

    try:
        # Assignment can replace selected text or insert at an empty caret. Mark the
        # mutation first because a COM setter may fail after Word has changed the document.
        mutation_started = True
        source_range.Text = linear
        equation_range = selection.OMaths.Add(source_range)
        equation_range.OMaths(1).BuildUp()
        equation_range.Select()
    except Exception as exc:
        if mutation_started:
            changed_range = _returned_range_or_source(equation_range, source_range)
            _restore_word_selection(
                document,
                changed_range,
                source_range,
                original_start,
                original_end,
                original_text,
            )
        raise WordIntegrationError(
            "Word 没有成功建立原生公式，已尝试恢复原来的选区内容。"
        ) from exc


def _returned_range_or_source(equation_range: Any, source_range: Any) -> Any:
    if equation_range is not None:
        try:
            return equation_range.Duplicate
        except Exception:
            pass
    return source_range


def _restore_word_selection(
    document: Any,
    changed_range: Any,
    source_range: Any,
    original_start: int,
    original_end: int,
    original_text: str,
) -> None:
    """Best-effort restoration after Word has received the linear formula text."""

    restored = False
    try:
        changed_range.Text = original_text
        restored = True
    except Exception:
        pass

    if not restored:
        for candidate in (changed_range, source_range):
            try:
                rollback_range = document.Range(original_start, int(candidate.End))
                rollback_range.Text = original_text
                restored = True
                break
            except Exception:
                continue

    # Restoring the original text returns the document to its previous coordinate
    # system, so the saved endpoints work for both an empty caret and selected text.
    try:
        document.Range(original_start, original_end).Select()
    except Exception:
        try:
            changed_range.SetRange(original_start, original_end)
            changed_range.Select()
        except Exception:
            pass
