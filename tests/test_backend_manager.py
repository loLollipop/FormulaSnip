from __future__ import annotations

from threading import Event, Lock, Thread
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
        self.recognition_calls = 0
        self.warmup_calls = 0

    def recognize(self, _image: Image.Image) -> RecognitionResult:
        self.recognition_calls += 1
        return self.result

    def warmup(self) -> None:
        self.warmup_calls += 1

    def close(self) -> None:
        pass


def formula_image(*, touches_edge: bool = False) -> Image.Image:
    image = Image.new("L", (180, 60), "white")
    left = 0 if touches_edge else 20
    ImageDraw.Draw(image).rectangle((left, 20, 150, 40), fill="black")
    return image


def configure_availability(monkeypatch: Any, available: bool) -> None:
    monkeypatch.setattr(
        manager_module.MathCraftBackend,
        "is_available",
        classmethod(lambda cls: available),
    )


def test_backend_summaries_only_exposes_mathcraft(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, True)
    assert backend_summaries() == [
        ("mathcraft", "MathCraft OCR（CPU）", True),
    ]


@pytest.mark.parametrize("selected_key", ("mathcraft", "auto", "rapid", "paddle"))
def test_legacy_keys_alias_to_one_mathcraft_call(
    monkeypatch: Any, selected_key: str
) -> None:
    configure_availability(monkeypatch, True)
    backend = FakeBackend(RecognitionResult("x+y", "MathCraft", 0.2))
    manager = BackendManager()
    manager._instances = {"mathcraft": backend}  # type: ignore[dict-item]

    result = manager.recognize(formula_image(), selected_key)

    assert result.backend_name == "MathCraft"
    assert backend.recognition_calls == 1
    assert len(result.alternatives) == 1


def test_default_uses_mathcraft_once(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, True)
    backend = FakeBackend(RecognitionResult("x+y", "MathCraft", 0.2))
    manager = BackendManager()
    manager._instances = {"mathcraft": backend}  # type: ignore[dict-item]

    manager.recognize(formula_image())

    assert backend.recognition_calls == 1


def test_unknown_backend_is_rejected(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, True)
    with pytest.raises(BackendUnavailableError, match="未知"):
        BackendManager().recognize(formula_image(), "other")


def test_missing_mathcraft_is_reported(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, False)
    with pytest.raises(BackendUnavailableError, match="MathCraft OCR"):
        BackendManager().recognize(formula_image())


def test_quality_preview_and_image_warnings_are_preserved(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, True)
    backend = FakeBackend(
        RecognitionResult(r"\frac{x}{y", "MathCraft", 0.2, warnings=("上游提示",))
    )
    manager = BackendManager()
    manager._instances = {"mathcraft": backend}  # type: ignore[dict-item]
    monkeypatch.setattr(manager_module, "is_formula_previewable", lambda _value: False)

    result = manager.recognize(formula_image(touches_edge=True))

    assert any("人工校对" in warning for warning in result.warnings)
    assert any("无法生成电子公式预览" in warning for warning in result.warnings)
    assert any("触边" in warning for warning in result.warnings)
    assert "上游提示" in result.warnings


def test_complex_formula_adds_review_warning_without_changing_result(
    monkeypatch: Any,
) -> None:
    configure_availability(monkeypatch, True)
    backend = FakeBackend(RecognitionResult(r"\int_0^1 x\,dx", "MathCraft", 0.2))
    manager = BackendManager()
    manager._instances = {"mathcraft": backend}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.latex == r"\int_0^1 x\,dx"
    assert any("结构较复杂" in warning for warning in result.warnings)


def test_complex_review_warning_is_not_duplicated(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, True)
    warning = "公式版式或结构较复杂，请对照原图人工核对。"
    backend = FakeBackend(
        RecognitionResult(r"\int_0^1 x\,dx", "MathCraft", 0.2, warnings=(warning,))
    )
    manager = BackendManager()
    manager._instances = {"mathcraft": backend}  # type: ignore[dict-item]

    result = manager.recognize(formula_image())

    assert result.warnings.count(warning) == 1


def test_warmup_reuses_backend_and_failure_can_be_retried(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, True)

    class RetryBackend(FakeBackend):
        def warmup(self) -> None:
            self.warmup_calls += 1
            if self.warmup_calls == 1:
                raise RecognitionError("first failure")

    backend = RetryBackend(RecognitionResult("x", "MathCraft", 0.1))
    manager = BackendManager()
    manager._instances = {"mathcraft": backend}  # type: ignore[dict-item]

    with pytest.raises(RecognitionError, match="first failure"):
        manager.warmup("auto")
    manager.warmup("rapid")
    assert backend.warmup_calls == 2


def test_concurrent_recognition_calls_are_serialized(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, True)
    first_started = Event()
    release_first = Event()

    class SerialBackend(FakeBackend):
        def __init__(self) -> None:
            super().__init__(RecognitionResult("x", "MathCraft", 0.1))
            self.active = 0
            self.max_active = 0
            self.guard = Lock()

        def recognize(self, image: Image.Image) -> RecognitionResult:
            with self.guard:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                call = self.recognition_calls
                self.recognition_calls += 1
            if call == 0:
                first_started.set()
                release_first.wait(2.0)
            with self.guard:
                self.active -= 1
            return self.result

    backend = SerialBackend()
    manager = BackendManager()
    manager._instances = {"mathcraft": backend}  # type: ignore[dict-item]
    first = Thread(target=manager.recognize, args=(formula_image(),))
    second = Thread(target=manager.recognize, args=(formula_image(),))
    first.start()
    assert first_started.wait(1.0)
    second.start()
    try:
        second.join(0.1)
        assert second.is_alive()
    finally:
        release_first.set()
        first.join(2.0)
        second.join(2.0)

    assert backend.max_active == 1
    assert backend.recognition_calls == 2
    assert not first.is_alive()
    assert not second.is_alive()


def test_close_is_idempotent_and_stops_future_backend_creation(monkeypatch: Any) -> None:
    configure_availability(monkeypatch, True)
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
        manager.recognize(formula_image())
