from __future__ import annotations

from typing import Any

import pytest
from PIL import Image, ImageDraw

from formulasnip.domain import RecognitionCandidate, RecognitionResult
from formulasnip.exceptions import BackendUnavailableError, RecognitionError
from formulasnip.recognition import manager as manager_module
from formulasnip.recognition.manager import (
    BackendManager,
    _choose_candidate,
    backend_summaries,
)
from formulasnip.recognition.quality import assess_latex


def test_backend_summaries_have_unique_keys() -> None:
    summaries = backend_summaries()
    keys = [key for key, _name, _available in summaries]
    assert keys == ["rapid", "paddle"]
    assert len(set(keys)) == len(keys)


class FakeBackend:
    def __init__(self, result: RecognitionResult | Exception) -> None:
        self.result = result
        self.calls = 0

    def recognize(self, _image: Image.Image) -> RecognitionResult:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def formula_image() -> Image.Image:
    image = Image.new("RGB", (180, 60), "white")
    ImageDraw.Draw(image).rectangle((30, 20, 150, 40), fill="black")
    return image


def configure_availability(monkeypatch: Any, *, rapid: bool, paddle: bool) -> None:
    monkeypatch.setattr(
        manager_module.RapidLatexBackend, "is_available", classmethod(lambda cls: rapid)
    )
    monkeypatch.setattr(
        manager_module.PaddleFormulaBackend, "is_available", classmethod(lambda cls: paddle)
    )


def test_auto_uses_paddle_when_rapid_is_unavailable(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=False, paddle=True)
    paddle = FakeBackend(RecognitionResult("x+y", "Paddle", 0.2))
    manager = BackendManager()
    manager._instances = {"paddle": paddle}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "Paddle"
    assert result.strategy == "auto-fallback"
    assert paddle.calls == 1


def test_auto_reports_missing_models_when_no_backend_is_available(
    monkeypatch: Any,
) -> None:
    configure_availability(monkeypatch, rapid=False, paddle=False)

    with pytest.raises(BackendUnavailableError, match="没有检测到本地公式模型"):
        BackendManager().recognize(formula_image())


def test_auto_clean_simple_formula_stays_on_rapid(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, paddle=True)
    rapid = FakeBackend(RecognitionResult("x+y", "Rapid", 0.2))
    paddle = FakeBackend(RecognitionResult("wrong", "Paddle", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "paddle": paddle}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.latex == "x+y"
    assert result.strategy == "auto-rapid"
    assert rapid.calls == 1
    assert paddle.calls == 0


def test_auto_complex_formula_reviews_and_keeps_cleaner_candidate(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, paddle=True)
    rapid = FakeBackend(RecognitionResult(r"\int_{0}^{1", "Rapid", 0.2))
    paddle = FakeBackend(RecognitionResult(r"\int_{0}^{1} x\,dx", "Paddle", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "paddle": paddle}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "Paddle"
    assert len(result.alternatives) == 2
    assert result.elapsed_seconds >= 0


def test_new_quality_rule_triggers_review_and_selects_clean_candidate(
    monkeypatch: Any,
) -> None:
    configure_availability(monkeypatch, rapid=True, paddle=True)
    rapid = FakeBackend(RecognitionResult("x == y", "Rapid", 0.2))
    paddle = FakeBackend(RecognitionResult("x = y", "Paddle", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "paddle": paddle}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "Paddle"
    assert result.strategy == "auto-reviewed"
    assert rapid.calls == paddle.calls == 1


def test_candidate_choice_prioritizes_quality_score_before_issue_count() -> None:
    rapid_latex = "frac{x}{y}--z"
    paddle_latex = r"\alpha+x" * 20
    rapid_report = assess_latex(rapid_latex)
    paddle_report = assess_latex(paddle_latex)
    assert len(rapid_report.issues) > len(paddle_report.issues)
    assert rapid_report.score > paddle_report.score
    candidates = (
        RecognitionCandidate(rapid_latex, "Rapid", 0.2, rapid_report.issues),
        RecognitionCandidate(paddle_latex, "Paddle", 0.3, paddle_report.issues),
    )

    winner = _choose_candidate(candidates, prefer_paddle_on_tie=False)

    assert winner.backend == "Rapid"


def test_auto_never_lets_malformed_paddle_replace_clean_rapid(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, paddle=True)
    rapid = FakeBackend(RecognitionResult(r"\int_0^1 x\,dx", "Rapid", 0.2))
    paddle = FakeBackend(RecognitionResult("frac{x}{y}--z", "Paddle", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "paddle": paddle}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "Rapid"
    assert result.alternatives[1].issues


def test_auto_returns_rapid_with_warning_when_review_fails(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, paddle=True)
    rapid = FakeBackend(RecognitionResult(r"\sum_i x_i", "Rapid", 0.2))
    paddle = FakeBackend(RecognitionError("boom"))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "paddle": paddle}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "Rapid"
    assert "复核失败" in result.warnings[-1]


def test_auto_surfaces_rapid_quality_issue_when_paddle_is_missing(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, paddle=False)
    rapid = FakeBackend(RecognitionResult(r"\int_{0}^{1", "Rapid", 0.2))
    manager = BackendManager()
    manager._instances = {"rapid": rapid}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.backend_name == "Rapid"
    assert result.warnings[0].startswith("识别结果需要人工校对")
    assert "括号不配对" in result.warnings[0]


def test_specific_backend_surfaces_quality_issue(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=False, paddle=True)
    paddle = FakeBackend(RecognitionResult("frac{x}{y}--z", "Paddle", 0.2))
    manager = BackendManager()
    manager._instances = {"paddle": paddle}  # type: ignore[dict-item]

    result = manager.recognize(formula_image(), "paddle")

    assert result.warnings[0].startswith("识别结果需要人工校对")
    assert len(result.alternatives) == 1


def test_specific_backend_does_not_run_adaptive_route(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, paddle=True)
    rapid = FakeBackend(RecognitionResult(r"\int x", "Rapid", 0.2))
    manager = BackendManager()
    manager._instances = {"rapid": rapid}  # type: ignore[dict-item]

    result = manager.recognize(formula_image(), "rapid")

    assert result.strategy == "single"
    assert result.alternatives == ()


def test_candidate_choice_prefers_the_only_previewable_result() -> None:
    candidates = (
        RecognitionCandidate("x+y", "Rapid", 0.2, (), False),
        RecognitionCandidate("frac{x", "Paddle", 0.3, ("括号不配对",), True),
    )

    winner = _choose_candidate(candidates, prefer_paddle_on_tie=False)

    assert winner.backend == "Paddle"


def test_unpreviewable_rapid_result_triggers_paddle_review(
    monkeypatch: Any,
) -> None:
    configure_availability(monkeypatch, rapid=True, paddle=True)
    monkeypatch.setattr(
        manager_module,
        "is_formula_previewable",
        lambda latex: latex == "paddle-result",
    )
    rapid = FakeBackend(RecognitionResult("rapid-result", "Rapid", 0.2))
    paddle = FakeBackend(RecognitionResult("paddle-result", "Paddle", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "paddle": paddle}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert paddle.calls == 1
    assert result.latex == "paddle-result"
    assert result.alternatives[0].previewable is False
    assert result.alternatives[1].previewable is True


def test_auto_marks_when_neither_candidate_can_be_previewed(
    monkeypatch: Any,
) -> None:
    configure_availability(monkeypatch, rapid=True, paddle=True)
    monkeypatch.setattr(manager_module, "is_formula_previewable", lambda _latex: False)
    rapid = FakeBackend(RecognitionResult("x+y", "Rapid", 0.2))
    paddle = FakeBackend(RecognitionResult("x-y", "Paddle", 0.3))
    manager = BackendManager()
    manager._instances = {"rapid": rapid, "paddle": paddle}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.strategy == "auto-reviewed-no-preview"
    assert any("两个引擎均未生成可预览候选" in warning for warning in result.warnings)


def test_specific_backend_warns_when_result_cannot_be_previewed(
    monkeypatch: Any,
) -> None:
    configure_availability(monkeypatch, rapid=True, paddle=False)
    monkeypatch.setattr(manager_module, "is_formula_previewable", lambda _latex: False)
    rapid = FakeBackend(RecognitionResult("unknown", "Rapid", 0.2))
    manager = BackendManager()
    manager._instances = {"rapid": rapid}  # type: ignore[dict-item]

    result = manager.recognize(formula_image(), "rapid")

    assert any("无法生成电子公式预览" in warning for warning in result.warnings)
    assert result.alternatives[0].previewable is False


def test_warmup_reuses_backend_and_failure_can_be_retried(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, rapid=True, paddle=False)

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
    assert manager._instances["rapid"] is backend
