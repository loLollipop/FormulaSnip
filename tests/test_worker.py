from __future__ import annotations

from threading import Barrier
from typing import Any

from PIL import Image

from formulasnip.domain import RecognitionCandidate, RecognitionResult
from formulasnip.recognition.openai_correction import AICorrectionError
from formulasnip.ui import worker as worker_module
from formulasnip.ui.worker import CompatibleModelWorker, RecognitionWorker


class Manager:
    def __init__(self, result: RecognitionResult | Exception) -> None:
        self.result = result

    def recognize(self, _image: Image.Image, _backend_key: str) -> RecognitionResult:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_worker_starts_local_and_ai_concurrently(monkeypatch: Any) -> None:
    barrier = Barrier(2, timeout=1)
    image_ids: list[int] = []

    class BarrierManager:
        def recognize(self, image: Image.Image, _backend_key: str) -> RecognitionResult:
            image_ids.append(id(image))
            barrier.wait()
            return RecognitionResult("x", "MathCraft", 0.1)

    def transcribe(image: Image.Image, _key: str, **_kwargs: Any) -> RecognitionCandidate:
        image_ids.append(id(image))
        barrier.wait()
        return RecognitionCandidate("y", "AI · vision-model", 0.1, source="ai")

    monkeypatch.setattr(worker_module, "transcribe_formula", transcribe)
    worker = RecognitionWorker(
        BarrierManager(),  # type: ignore[arg-type]
        Image.new("RGB", (8, 8), "white"),
        "mathcraft",
        ai_enabled=True,
        ai_api_key="unit-test-token",
        ai_model="vision-model",
    )
    results: list[RecognitionResult] = []
    worker.signals.finished.connect(lambda _task, result: results.append(result))

    worker.run()

    assert len(set(image_ids)) == 2
    assert results[0].latex == "x"
    assert results[0].comparison == "different"
    assert [candidate.source for candidate in results[0].alternatives] == ["local", "ai"]
    assert "显式选择" in results[0].warnings[-1]
    assert worker.ai_api_key is None


def test_worker_marks_equivalent_results_and_keeps_ai_default(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        worker_module,
        "transcribe_formula",
        lambda *_args, **_kwargs: RecognitionCandidate(
            "x+y", "AI · vision-model", 0.1, source="ai"
        ),
    )
    worker = RecognitionWorker(
        Manager(RecognitionResult(r"{ x \! + \, y }", "MathCraft", 0.1)),  # type: ignore[arg-type]
        Image.new("RGB", (8, 8), "white"),
        "mathcraft",
        ai_enabled=True,
        ai_api_key="unit-test-token",
    )
    results: list[RecognitionResult] = []
    worker.signals.finished.connect(lambda _task, result: results.append(result))
    worker.run()

    assert results[0].latex == "x+y"
    assert results[0].comparison == "equivalent"


def test_worker_preserves_multiline_disagreement_for_source_switch(
    monkeypatch: Any,
) -> None:
    local_latex = r"\begin{gathered}x=1\\y=2\end{gathered}"
    ai_latex = r"\begin{gathered}x=1y=2\end{gathered}"
    monkeypatch.setattr(
        worker_module,
        "transcribe_formula",
        lambda *_args, **_kwargs: RecognitionCandidate(
            ai_latex, "AI · vision-model", 0.1, source="ai"
        ),
    )
    worker = RecognitionWorker(
        Manager(RecognitionResult(local_latex, "MathCraft", 0.1)),  # type: ignore[arg-type]
        Image.new("RGB", (8, 8), "white"),
        "mathcraft",
        ai_enabled=True,
        ai_api_key="unit-test-token",
    )
    results: list[RecognitionResult] = []
    worker.signals.finished.connect(lambda _task, result: results.append(result))

    worker.run()

    assert results[0].comparison == "different"
    assert [candidate.latex for candidate in results[0].alternatives] == [
        local_latex,
        ai_latex,
    ]
    assert "显式选择" in results[0].warnings[-1]


def test_worker_keeps_local_result_when_ai_fails(monkeypatch: Any) -> None:
    local = RecognitionResult("x", "MathCraft", 0.1)

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise AICorrectionError("AI 不可用，已保留 MathCraft 结果。")

    monkeypatch.setattr(worker_module, "transcribe_formula", fail)
    worker = RecognitionWorker(
        Manager(local),  # type: ignore[arg-type]
        Image.new("RGB", (8, 8), "white"),
        "mathcraft",
        ai_enabled=True,
        ai_api_key="unit-test-token",
    )
    results: list[tuple[RecognitionWorker, RecognitionResult]] = []
    worker.signals.finished.connect(lambda task, result: results.append((task, result)))

    worker.run()

    assert results[0][0] is worker
    assert results[0][1].latex == local.latex
    assert results[0][1].backend_name == local.backend_name
    assert "AI 不可用" in results[0][1].warnings[-1]


def test_worker_redacts_unexpected_ai_error(monkeypatch: Any) -> None:
    marker = "sensitive-upstream-body"

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(marker)

    monkeypatch.setattr(worker_module, "transcribe_formula", fail)
    worker = RecognitionWorker(
        Manager(RecognitionResult("x", "MathCraft", 0.1)),  # type: ignore[arg-type]
        Image.new("RGB", (8, 8), "white"),
        "mathcraft",
        ai_enabled=True,
        ai_api_key="unit-test-token",
    )
    results: list[RecognitionResult] = []
    worker.signals.finished.connect(lambda _task, result: results.append(result))

    worker.run()

    assert marker not in "\n".join(results[0].warnings)
    assert "AI 识别暂时不可用" in results[0].warnings[-1]


def test_worker_replaces_ai_result_when_cancelled_before_emit(monkeypatch: Any) -> None:
    local = RecognitionResult("local-x", "MathCraft", 0.1)
    worker: RecognitionWorker

    def finish_ai_then_cancel(*_args: Any, **_kwargs: Any) -> RecognitionCandidate:
        worker.cancel()
        return RecognitionCandidate("stale-ai-y", "AI · vision-model", 0.2, source="ai")

    monkeypatch.setattr(worker_module, "transcribe_formula", finish_ai_then_cancel)
    worker = RecognitionWorker(
        Manager(local),  # type: ignore[arg-type]
        Image.new("RGB", (8, 8), "white"),
        "mathcraft",
        ai_enabled=True,
        ai_api_key="unit-test-token",
    )
    results: list[tuple[RecognitionWorker, RecognitionResult]] = []
    worker.signals.finished.connect(lambda task, result: results.append((task, result)))

    worker.run()

    assert results[0][0] is worker
    assert results[0][1].latex == "local-x"
    assert results[0][1].backend_name == "MathCraft"
    assert results[0][1].strategy != "ai-assisted"
    assert "已取消" in results[0][1].warnings[-1]


def test_ai_only_cancel_before_run_still_delivers_local_result() -> None:
    calls: list[tuple[Image.Image, str]] = []

    class TrackingManager:
        def recognize(self, image: Image.Image, backend_key: str) -> RecognitionResult:
            calls.append((image, backend_key))
            return RecognitionResult("local-x", "MathCraft", 0.1)

    worker = RecognitionWorker(
        TrackingManager(),  # type: ignore[arg-type]
        Image.new("RGB", (8, 8), "white"),
        "mathcraft",
        ai_enabled=True,
        ai_api_key="unit-test-token",
    )
    results: list[RecognitionResult] = []
    failures: list[str] = []
    worker.signals.finished.connect(lambda _task, result: results.append(result))
    worker.signals.failed.connect(lambda _task, message: failures.append(message))

    worker.cancel_ai()
    worker.run()

    assert worker._cancel_event.is_set()
    assert not worker._local_cancel_event.is_set()
    assert len(calls) == 1
    assert calls[0][1] == "mathcraft"
    assert failures == []
    assert results[0].latex == "local-x"
    assert results[0].backend_name == "MathCraft"
    assert "AI 识别已取消" in results[0].warnings[-1]


def test_worker_does_not_call_ai_when_disabled(monkeypatch: Any) -> None:
    local = RecognitionResult("x", "MathCraft", 0.1)
    monkeypatch.setattr(
        worker_module,
        "transcribe_formula",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not call AI")),
    )
    worker = RecognitionWorker(
        Manager(local),  # type: ignore[arg-type]
        Image.new("RGB", (8, 8), "white"),
        "mathcraft",
        ai_enabled=False,
        ai_api_key="unit-test-token",
    )
    results: list[tuple[RecognitionWorker, RecognitionResult]] = []
    worker.signals.finished.connect(lambda task, result: results.append((task, result)))

    worker.run()

    assert results == [(worker, local)]
    assert worker.ai_api_key is None


def test_worker_delivers_ai_when_local_recognition_fails(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        worker_module,
        "transcribe_formula",
        lambda *_args, **_kwargs: RecognitionCandidate(
            "ai-x", "AI · vision-model", 0.1, source="ai"
        ),
    )
    worker = RecognitionWorker(
        Manager(RuntimeError("local failure")),  # type: ignore[arg-type]
        Image.new("RGB", (8, 8), "white"),
        "mathcraft",
        ai_enabled=True,
        ai_api_key="unit-test-token",
    )
    results: list[RecognitionResult] = []
    worker.signals.finished.connect(lambda _task, result: results.append(result))

    worker.run()

    assert results[0].latex == "ai-x"
    assert "local failure" in results[0].warnings[0]
    assert worker.ai_api_key is None


def test_worker_fails_only_when_both_branches_fail(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        worker_module,
        "transcribe_formula",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AICorrectionError("AI failure")),
    )
    worker = RecognitionWorker(
        Manager(RuntimeError("local failure")),  # type: ignore[arg-type]
        Image.new("RGB", (8, 8), "white"),
        "mathcraft",
        ai_enabled=True,
        ai_api_key="unit-test-token",
    )
    failures: list[str] = []
    worker.signals.failed.connect(lambda _task, message: failures.append(message))
    worker.run()

    assert "local failure" in failures[0]
    assert "AI failure" in failures[0]
    assert worker.ai_api_key is None


def test_compatible_model_worker_loads_models_and_clears_key(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        worker_module,
        "list_compatible_models",
        lambda key, base_url, **_kwargs: (f"{key}:{base_url}",),
    )
    worker = CompatibleModelWorker(
        "list",
        "unit-test-token",
        "https://gateway.example/v1",
        "vision-model",
    )
    results: list[tuple[CompatibleModelWorker, object]] = []
    finished: list[CompatibleModelWorker] = []
    worker.signals.succeeded.connect(
        lambda task, result: results.append((task, result))
    )
    worker.signals.finished.connect(finished.append)

    worker.run()

    assert results == [
        (worker, ("unit-test-token:https://gateway.example/v1",))
    ]
    assert finished == [worker]
    assert worker.api_key is None


def test_compatible_model_worker_tests_selected_model(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        worker_module,
        "test_compatible_model_access",
        lambda key, base_url, model, **_kwargs: f"{model}:{len(key)}:{base_url}",
    )
    worker = CompatibleModelWorker(
        "test",
        "unit-test-token",
        "https://gateway.example/v1",
        "vision-model",
    )
    results: list[tuple[CompatibleModelWorker, object]] = []
    worker.signals.succeeded.connect(
        lambda task, result: results.append((task, result))
    )

    worker.run()

    assert results == [
        (worker, "vision-model:15:https://gateway.example/v1")
    ]
    assert worker.api_key is None


def test_compatible_model_worker_failure_carries_worker_and_clears_key(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        worker_module,
        "list_compatible_models",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AICorrectionError("request failed")
        ),
    )
    worker = CompatibleModelWorker(
        "list",
        "unit-test-token",
        "https://gateway.example/v1",
        "vision-model",
    )
    failures: list[tuple[CompatibleModelWorker, str]] = []
    finished: list[CompatibleModelWorker] = []
    worker.signals.failed.connect(
        lambda task, message: failures.append((task, message))
    )
    worker.signals.finished.connect(finished.append)

    worker.run()

    assert failures == [(worker, "request failed")]
    assert finished == [worker]
    assert worker.api_key is None
