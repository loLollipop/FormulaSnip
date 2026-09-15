from __future__ import annotations

from dataclasses import dataclass

import pytest

from formulasnip.exceptions import WordIntegrationError
from formulasnip.integrations.word import _insert_linear_formula


@dataclass
class FakeDocumentState:
    text: str


class FakeRange:
    def __init__(self, state: FakeDocumentState, start: int, end: int) -> None:
        self.state = state
        self.Start = start
        self.End = end
        self.selected = False

    @property
    def Duplicate(self) -> FakeRange:
        return FakeRange(self.state, self.Start, self.End)

    @property
    def Text(self) -> str:
        return self.state.text[self.Start : self.End]

    @Text.setter
    def Text(self, value: str) -> None:
        self.state.text = self.state.text[: self.Start] + value + self.state.text[self.End :]
        self.End = self.Start + len(value)

    def Select(self) -> None:
        self.selected = True

    def SetRange(self, start: int, end: int) -> None:  # noqa: N802
        self.Start = start
        self.End = end


class FakeDocument:
    ReadOnly = False
    ProtectionType = -1

    def __init__(self, state: FakeDocumentState) -> None:
        self.state = state
        self.selected_range: FakeRange | None = None

    def Range(self, start: int, end: int) -> FakeRange:  # noqa: N802
        result = FakeRange(self.state, start, end)
        original_select = result.Select

        def select() -> None:
            original_select()
            self.selected_range = result

        result.Select = select  # type: ignore[method-assign]
        return result


class FakeEquation:
    def __init__(self, fail_build: bool) -> None:
        self.fail_build = fail_build
        self.built = False

    def BuildUp(self) -> None:  # noqa: N802
        if self.fail_build:
            raise RuntimeError("BuildUp failed")
        self.built = True


class FakeOMaths:
    def __init__(self, fail_build: bool) -> None:
        self.fail_build = fail_build
        self.equation = FakeEquation(fail_build)
        self.returned_range: FakeRange | None = None

    def Add(self, source_range: FakeRange) -> FakeRange:  # noqa: N802
        self.returned_range = source_range
        source_range.OMaths = lambda index: self.equation
        return source_range


class FakeApp:
    def __init__(self, text: str, start: int, end: int, *, fail_build: bool = False) -> None:
        self.state = FakeDocumentState(text)
        self.ActiveDocument = FakeDocument(self.state)
        self.Documents = type("Documents", (), {"Count": 1})()
        self.Selection = type("Selection", (), {})()
        self.Selection.Range = FakeRange(self.state, start, end)
        self.Selection.OMaths = FakeOMaths(fail_build)


@pytest.mark.parametrize(("start", "end"), [(2, 2), (1, 4)])
def test_insert_linear_formula_builds_returned_omath(start: int, end: int) -> None:
    app = FakeApp("abcdef", start, end)

    _insert_linear_formula(app, "x/y")

    equation = app.Selection.OMaths.equation
    assert equation.built
    returned_range = app.Selection.OMaths.returned_range
    assert returned_range is not None
    assert returned_range.selected


@pytest.mark.parametrize(("start", "end"), [(2, 2), (1, 4)])
def test_insert_linear_formula_rolls_back_after_buildup_failure(start: int, end: int) -> None:
    app = FakeApp("abcdef", start, end, fail_build=True)

    with pytest.raises(WordIntegrationError, match="已尝试恢复"):
        _insert_linear_formula(app, "x/y")

    assert app.state.text == "abcdef"
    restored = app.ActiveDocument.selected_range
    assert restored is not None
    assert (restored.Start, restored.End) == (start, end)
