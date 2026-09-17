from __future__ import annotations

from threading import Event, Thread
from typing import Any

import pytest
from PIL import Image, ImageDraw

from formulasnip.domain import RecognitionResult
from formulasnip.exceptions import BackendUnavailableError, RecognitionError
from formulasnip.recognition import manager as manager_module
from formulasnip.recognition.manager import BackendManager, backend_summaries


class FakeBackend:
    def __init__(self, result: RecognitionResult) -> None:
        self.result = result
        self.calls = 0

    def recognize(self, _image: Image.Image) -> RecognitionResult:
        self.calls += 1
        return self.result

    def warmup(self) -> None:
        self.calls += 1

    def close(self) -> None:
        pass


def formula_image(*, touches_edge: bool = False) -> Image.Image:
    image = Image.new("L", (180, 60), "white")
    left = 0 if touches_edge else 20
    ImageDraw.Draw(image).rectangle((left, 20, 150, 40), fill="black")
    return image


def visually_complex_formula_image() -> Image.Image:
    image = Image.new("L", (260, 90), "white")
    ImageDraw.Draw(image).rectangle((20, 20, 230, 65), fill="black")
    return image


def configure_availability(monkeypatch: Any, *, rapid: bool, mathcraft: bool) -> None:
    monkeypatch.setattr(
        manager_module.RapidLatexBackend, "is_available", classmethod(lambda cls: rapid)
    )
    monkeypatch.setattr(
        manager_module.MathCraftBackend,
        "is_available",
        classmethod(lambda cls: mathcraft),
    )


def test_backend_summaries_have_unique_keys() -> None:
    assert [item[0] for item in backend_summaries()] == ["rapid", "mathcraft"]


def test_auto_uses_mathcraft_when_rapid_is_unavailable(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=False, mathcraft=True)
    mathcraft = FakeBackend(RecognitionResult("x+y", "MathCraft", 0.2))
    manager = BackendManager()
    manager._instances = {"mathcraft": mathcraft}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "MathCraft"
    assert result.strategy == "auto-fallback"
    assert mathcraft.calls == 1


def test_auto_reports_missing_models(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=False, mathcraft=False)
    with pytest.raises(BackendUnavailableError, match="默认双引擎"):
        BackendManager().recognize(formula_image())


def test_auto_clean_simple_formula_stays_on_rapid(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)
    rapid = FakeBackend(RecognitionResult("x+y", "Rapid", 0.2))
    mathcraft = FakeBackend(RecognitionResult("wrong", "MathCraft", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "mathcraft": mathcraft}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.strategy == "auto-rapid"
    assert rapid.calls == 1
    assert mathcraft.calls == 0


def test_auto_reviews_visually_complex_image_when_rapid_collapses_to_simple_text(
    monkeypatch: Any,
) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)
    rapid = FakeBackend(RecognitionResult("x+y", "Rapid", 0.2))
    mathcraft = FakeBackend(RecognitionResult(r"\frac{\partial u}{\partial t}", "MathCraft", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "mathcraft": mathcraft}  # type: ignore[dict-item]

    result = manager.recognize(visually_complex_formula_image())

    assert result.backend_name == "MathCraft"
    assert mathcraft.calls == 1
    assert any("两个引擎结果不一致" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    "rapid_latex",
    (
        r"\frac{\hat C u}{\bar Q t}+\nabla u",
        r"\frac{\dot C u}{x}+\frac{u}{\ddot Q t}",
        r"\begin{aligned}x&=y\end{aligned}",
    ),
)
def test_auto_routes_pde_and_complex_structures_to_mathcraft(
    monkeypatch: Any, rapid_latex: str
) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)
    exact = r"\frac{\partial u}{\partial t}+\nabla u"
    rapid = FakeBackend(RecognitionResult(rapid_latex, "Rapid", 0.2))
    mathcraft = FakeBackend(RecognitionResult(exact, "MathCraft", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "mathcraft": mathcraft}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert rapid.calls == mathcraft.calls == 1
    assert result.latex == exact
    assert result.backend_name == "MathCraft"
    assert len(result.alternatives) == 2
    assert any("两个引擎结果不一致" in warning for warning in result.warnings)


def test_review_defaults_to_mathcraft_when_valid_candidates_disagree(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)
    rapid = FakeBackend(RecognitionResult(r"\int_0^1 x\,dx", "Rapid", 0.2))
    mathcraft = FakeBackend(RecognitionResult(r"\int_0^1 x^2\,dx", "MathCraft", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "mathcraft": mathcraft}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "MathCraft"
    assert result.latex == mathcraft.result.latex
    assert any("复杂公式请重点校对" in warning for warning in result.warnings)


def test_review_treats_whitespace_only_latex_variants_as_agreement(
    monkeypatch: Any,
) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)
    rapid = FakeBackend(RecognitionResult(r"\int_0^1 x\,dx", "Rapid", 0.2))
    mathcraft = FakeBackend(
        RecognitionResult(r"\int _0^1 x \, d x", "MathCraft", 0.3)
    )
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "mathcraft": mathcraft}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "Rapid"
    assert not any("两个引擎结果不一致" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("rapid_latex", "mathcraft_latex"),
    (
        (r"\lim sup", r"\limsup"),
        (r"\int a arrow b", r"\int a\leftarrow b"),
    ),
)
def test_review_does_not_hide_semantic_control_word_differences(
    monkeypatch: Any, rapid_latex: str, mathcraft_latex: str
) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)
    rapid = FakeBackend(RecognitionResult(rapid_latex, "Rapid", 0.2))
    mathcraft = FakeBackend(RecognitionResult(mathcraft_latex, "MathCraft", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "mathcraft": mathcraft}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "MathCraft"
    assert any("两个引擎结果不一致" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    "exact",
    (
        r"\begin{array}{cc}a&b\\c&d\end{array}",
        r"\begin{cases}x&x>0\\0&x\leq0\end{cases}",
    ),
)
def test_matrix_or_cases_does_not_lose_only_because_preview_is_unavailable(
    monkeypatch: Any, exact: str
) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)
    rapid = FakeBackend(RecognitionResult(r"\int_0^1 x\,dx", "Rapid", 0.2))
    mathcraft = FakeBackend(RecognitionResult(exact, "MathCraft", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "mathcraft": mathcraft}  # type: ignore[dict-item]
    monkeypatch.setattr(manager_module, "is_formula_previewable", lambda value: value != exact)

    result = manager.recognize(formula_image())

    assert result.latex == exact
    assert result.backend_name == "MathCraft"


def test_obvious_mathcraft_syntax_failure_loses_to_valid_rapid(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)
    rapid = FakeBackend(RecognitionResult(r"\int_0^1 x\,dx", "Rapid", 0.2))
    mathcraft = FakeBackend(RecognitionResult(r"\frac{x}{y", "MathCraft", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "mathcraft": mathcraft}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "Rapid"
    assert any("两个引擎结果不一致" in warning for warning in result.warnings)


def test_repetitive_mathcraft_failure_loses_to_valid_rapid(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)
    rapid = FakeBackend(RecognitionResult(r"\int_0^1 x\,dx", "Rapid", 0.2))
    mathcraft = FakeBackend(RecognitionResult(r"\alpha+x" * 20, "MathCraft", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "mathcraft": mathcraft}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "Rapid"
    assert any(
        "异常重复片段" in issue
        for candidate in result.alternatives
        for issue in candidate.issues
    )


def test_legitimate_rapid_accent_is_kept_without_partial_evidence(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)
    rapid = FakeBackend(RecognitionResult(r"\frac{\hat\theta}{x}", "Rapid", 0.2))
    mathcraft = FakeBackend(RecognitionResult(r"\frac{\theta}{x}", "MathCraft", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "mathcraft": mathcraft}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "Rapid"
    assert any("两个引擎结果不一致" in warning for warning in result.warnings)


def test_image_risk_is_retained_after_review(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)
    rapid = FakeBackend(RecognitionResult("x+y", "Rapid", 0.2))
    mathcraft = FakeBackend(RecognitionResult("x+y", "MathCraft", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "mathcraft": mathcraft}  # type: ignore[dict-item]

    result = manager.recognize(formula_image(touches_edge=True))

    assert any("触边" in warning for warning in result.warnings)


def test_review_failure_keeps_rapid(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)

    class Broken(FakeBackend):
        def recognize(self, _image: Image.Image) -> RecognitionResult:
            raise RecognitionError("offline")

    manager = BackendManager()
    manager._instances = {
        "rapid": FakeBackend(RecognitionResult(r"\int x", "Rapid", 0.2)),
        "mathcraft": Broken(RecognitionResult("", "MathCraft", 0.0)),
    }  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "Rapid"
    assert any("MathCraft OCR 复核失败" in warning for warning in result.warnings)


def test_warmup_reuses_backend_and_failure_can_be_retried(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=False)

    class RetryBackend(FakeBackend):
        def warmup(self) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RecognitionError("first failure")

    backend = RetryBackend(RecognitionResult("x", "Rapid", 0.1))
    manager = BackendManager()
    manager._instances = {"rapid": backend}  # type: ignore[dict-item]

    with pytest.raises(RecognitionError, match="first failure"):
        manager.warmup("rapid")
    manager.warmup("rapid")
    assert backend.calls == 2


def test_warmup_does_not_block_recognition_on_another_backend(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)
    warmup_started = Event()
    release_warmup = Event()
    recognition_finished = Event()

    class SlowMathCraft(FakeBackend):
        def warmup(self) -> None:
            warmup_started.set()
            release_warmup.wait(2.0)

    manager = BackendManager()
    manager._instances = {
        "rapid": FakeBackend(RecognitionResult("x+y", "Rapid", 0.2)),
        "mathcraft": SlowMathCraft(RecognitionResult("x+y", "MathCraft", 0.3)),
    }  # type: ignore[dict-item]
    warmup_thread = Thread(target=manager.warmup, args=("mathcraft",))
    recognition_thread = Thread(
        target=lambda: (
            manager.recognize(formula_image(), "rapid"),
            recognition_finished.set(),
        )
    )

    warmup_thread.start()
    assert warmup_started.wait(1.0)
    recognition_thread.start()
    try:
        assert recognition_finished.wait(0.5)
    finally:
        release_warmup.set()
        warmup_thread.join(2.0)
        recognition_thread.join(2.0)

    assert not warmup_thread.is_alive()
    assert not recognition_thread.is_alive()


def test_close_is_idempotent_and_stops_future_backend_creation(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, mathcraft=True)
    closed: list[bool] = []

    class Backend(FakeBackend):
        def close(self) -> None:
            closed.append(True)

    manager = BackendManager()
    manager._instances["mathcraft"] = Backend(
        RecognitionResult("x", "MathCraft", 0.2)
    )  # type: ignore[assignment]
    manager.close()
    manager.close()

    assert closed == [True]
    with pytest.raises(RecognitionError, match="已关闭"):
        manager.recognize(formula_image(), "mathcraft")
