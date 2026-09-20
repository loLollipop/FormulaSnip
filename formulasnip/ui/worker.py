from __future__ import annotations

from threading import Event, Thread
from time import perf_counter

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from formulasnip.core.latex import latex_equivalent
from formulasnip.core.preview import is_formula_previewable
from formulasnip.diagnostics import log_exception
from formulasnip.domain import RecognitionCandidate, RecognitionResult
from formulasnip.recognition import BackendManager
from formulasnip.recognition.openai_correction import (
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_MODEL,
    AICorrectionError,
    list_compatible_models,
    test_compatible_model_access,
    transcribe_formula,
)
from formulasnip.recognition.quality import assess_latex
from formulasnip.ui.image_conversion import ensure_supported_image_size

_DISAGREEMENT_WARNING = "本地与 AI 结果不一致，请显式选择一个结果、核对后再复制。"
_LOCAL_DEPENDENT_WARNING_PREFIXES = (
    "识别结果需要人工校对：",
    "当前识别结果无法生成电子公式预览",
)


class RecognitionSignals(QObject):
    finished = Signal(object, object)
    failed = Signal(object, str)


class RecognitionWorker(QRunnable):
    def __init__(
        self,
        manager: BackendManager,
        image: Image.Image,
        backend_key: str,
        *,
        ai_enabled: bool = False,
        ai_api_key: str | None = None,
        ai_base_url: str = DEFAULT_AI_BASE_URL,
        ai_model: str = DEFAULT_AI_MODEL,
    ) -> None:
        super().__init__()
        self.manager = manager
        ensure_supported_image_size(*image.size)
        self.image: Image.Image | None = image.copy()
        self.backend_key = backend_key
        self.ai_enabled = ai_enabled
        self.ai_api_key = ai_api_key
        self.ai_base_url = ai_base_url
        self.ai_model = ai_model
        self._task_identity = object()
        self._cancel_event = Event()
        self._local_cancel_event = Event()
        self._local_result: RecognitionResult | None = None
        self.signals = RecognitionSignals()

    def cancel(self) -> None:
        self._cancel_event.set()
        self._local_cancel_event.set()
        if isinstance(self.manager, BackendManager):
            self.manager.cancel_current(self._task_identity)

    def cancel_ai(self) -> None:
        """Stop only the optional AI branch and retain local OCR work."""

        self._cancel_event.set()

    def result_for_delivery(
        self, result: RecognitionResult
    ) -> RecognitionResult | None:
        """Prevent a queued AI signal from escaping after cancellation."""

        if not self._cancel_event.is_set():
            return result
        if self._local_result is None:
            return None
        return self._local_only_result(
            self._local_result,
            result.elapsed_seconds,
            "AI 识别已取消，已保留本地结果。",
        )

    def release_resources(self) -> None:
        """Drop the screenshot after the UI has finalized this task."""

        image = self.image
        self.image = None
        self._local_result = None
        self.ai_api_key = None
        if image is not None:
            image.close()

    @Slot()
    def run(self) -> None:
        image = self.image
        if image is None:
            self.ai_api_key = None
            self.signals.failed.emit(self, "识别任务截图不可用。")
            return
        if self._local_cancel_event.is_set():
            self.ai_api_key = None
            self.signals.failed.emit(self, "识别任务已取消。")
            return
        started = perf_counter()
        ai_key = (self.ai_api_key or "").strip()
        use_ai = self.ai_enabled and bool(ai_key) and not self._cancel_event.is_set()
        ai_state: dict[str, RecognitionCandidate | Exception] = {}
        ai_thread: Thread | None = None
        if use_ai:
            try:
                ai_image = image.copy()
            except Exception as exc:
                ai_state["error"] = exc
            else:

                def recognize_with_ai() -> None:
                    try:
                        ai_state["candidate"] = transcribe_formula(
                            ai_image,
                            ai_key,
                            base_url=self.ai_base_url,
                            model=self.ai_model,
                            cancel_event=self._cancel_event,
                        )
                    except Exception as exc:
                        ai_state["error"] = exc
                    finally:
                        ai_image.close()

                ai_thread = Thread(
                    target=recognize_with_ai,
                    name="FormulaSnip AI recognition",
                )
                try:
                    ai_thread.start()
                except Exception as exc:
                    ai_image.close()
                    ai_state["error"] = exc
                    ai_thread = None

        local_result: RecognitionResult | None = None
        local_error: Exception | None = None
        try:
            if isinstance(self.manager, BackendManager):
                local_result = self.manager.recognize(
                    image,
                    self.backend_key,
                    task_identity=self._task_identity,
                    cancel_event=self._local_cancel_event,
                )
            else:
                local_result = self.manager.recognize(image, self.backend_key)
            self._local_result = local_result
        except Exception as exc:
            local_error = exc.with_traceback(None)
        if ai_thread is not None:
            ai_thread.join()

        del image
        self.ai_api_key = None
        elapsed = perf_counter() - started
        ai_candidate = ai_state.get("candidate")
        ai_error = ai_state.get("error")
        if not isinstance(ai_candidate, RecognitionCandidate):
            ai_candidate = None

        if not use_ai:
            if local_result is None:
                message = self._error_message(local_error, "本地识别失败。")
                self.signals.failed.emit(self, message)
                return
            if self.ai_enabled:
                warning = (
                    "AI 识别已取消，已保留本地结果。"
                    if self._cancel_event.is_set()
                    else "AI 识别未配置有效 API Key，已保留本地结果。"
                )
                result = self._local_only_result(local_result, elapsed, warning)
            else:
                result = local_result
            delivery = self.result_for_delivery(result)
            if delivery is None:
                self.signals.failed.emit(self, "识别任务已取消。")
            else:
                self.signals.finished.emit(self, delivery)
            return

        if self._cancel_event.is_set():
            if local_result is None:
                self.signals.failed.emit(self, "识别任务已取消。")
                return
            result = self._local_only_result(
                local_result,
                elapsed,
                "AI 识别已取消，已保留本地结果。",
            )
        elif local_result is not None and ai_candidate is not None:
            result = self._combined_result(local_result, ai_candidate, elapsed)
        elif local_result is not None:
            if ai_error is not None and not isinstance(ai_error, AICorrectionError):
                log_exception("ai-recognition-failed", ai_error)
            warning = self._ai_error_message(
                ai_error,
                "AI 识别暂时不可用，已保留本地结果。",
            )
            result = self._local_only_result(local_result, elapsed, warning)
        elif ai_candidate is not None:
            local_message = self._error_message(local_error, "本地识别失败。")
            result = RecognitionResult(
                ai_candidate.latex,
                ai_candidate.backend,
                elapsed,
                "ai-parallel",
                (f"本地识别失败：{local_message}；已使用 AI 结果。",),
                (ai_candidate,),
            )
        else:
            local_message = self._error_message(local_error, "本地识别失败。")
            ai_message = self._ai_error_message(ai_error, "AI 识别失败。")
            self.signals.failed.emit(
                self,
                f"本地识别失败：{local_message}；AI 识别失败：{ai_message}",
            )
            return

        delivery = self.result_for_delivery(result)
        if delivery is None:
            self.signals.failed.emit(self, "识别任务已取消。")
        else:
            self.signals.finished.emit(self, delivery)

    @staticmethod
    def _error_message(error: object, fallback: str) -> str:
        if isinstance(error, BaseException):
            return str(error).strip() or type(error).__name__
        return fallback

    @staticmethod
    def _ai_error_message(error: object, fallback: str) -> str:
        if isinstance(error, AICorrectionError):
            return str(error).strip() or fallback
        return fallback

    @staticmethod
    def _local_candidate(result: RecognitionResult) -> RecognitionCandidate:
        for candidate in result.alternatives:
            if candidate.latex == result.latex and candidate.backend == result.backend_name:
                return RecognitionCandidate(
                    candidate.latex,
                    candidate.backend,
                    candidate.elapsed_seconds,
                    candidate.issues,
                    candidate.previewable,
                    "local",
                )
        return RecognitionCandidate(
            result.latex,
            result.backend_name,
            result.elapsed_seconds,
            assess_latex(result.latex).issues,
            None if is_formula_previewable(result.latex) else False,
            "local",
        )

    def _local_only_result(
        self,
        result: RecognitionResult,
        elapsed: float,
        warning: str,
    ) -> RecognitionResult:
        return RecognitionResult(
            result.latex,
            result.backend_name,
            elapsed,
            result.strategy,
            (*result.warnings, warning),
            (self._local_candidate(result),),
        )

    def _combined_result(
        self,
        local_result: RecognitionResult,
        ai_candidate: RecognitionCandidate,
        elapsed: float,
    ) -> RecognitionResult:
        local_candidate = self._local_candidate(local_result)
        equivalent = latex_equivalent(local_candidate.latex, ai_candidate.latex)
        warnings = [
            warning
            for warning in local_result.warnings
            if not warning.startswith(_LOCAL_DEPENDENT_WARNING_PREFIXES)
        ]
        if not equivalent:
            warnings.append(_DISAGREEMENT_WARNING)
        selected = ai_candidate if equivalent else local_candidate
        return RecognitionResult(
            selected.latex,
            selected.backend,
            elapsed,
            "ai-parallel",
            tuple(dict.fromkeys(warnings)),
            (local_candidate, ai_candidate),
            "equivalent" if equivalent else "different",
        )


class CompatibleModelSignals(QObject):
    succeeded = Signal(object, object)
    failed = Signal(object, str)
    finished = Signal(object)


class CompatibleModelWorker(QRunnable):
    """Load or verify models without blocking the settings window."""

    def __init__(
        self,
        action: str,
        api_key: str,
        base_url: str,
        model: str,
    ) -> None:
        super().__init__()
        if action not in {"list", "test"}:
            raise ValueError("unknown compatible model action")
        self.action = action
        self.api_key: str | None = api_key
        self.base_url = base_url
        self.model = model
        self._cancel_event = Event()
        self.signals = CompatibleModelSignals()

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        result: object | None = None
        error: str | None = None
        try:
            api_key = self.api_key
            if api_key is None:
                raise AICorrectionError("API Key 不可用。")
            if self.action == "list":
                result = list_compatible_models(
                    api_key,
                    self.base_url,
                    cancel_event=self._cancel_event,
                )
            else:
                result = test_compatible_model_access(
                    api_key,
                    self.base_url,
                    self.model,
                    cancel_event=self._cancel_event,
                )
        except AICorrectionError as exc:
            error = str(exc)
        except Exception as exc:
            log_exception("compatible-model-request-failed", exc)
            error = "AI 服务连接失败，请检查地址和网络。"
        self.api_key = None
        if error is not None:
            self.signals.failed.emit(self, error)
        else:
            self.signals.succeeded.emit(self, result)
        self.signals.finished.emit(self)


class ModelWarmupSignals(QObject):
    started = Signal(str)
    succeeded = Signal(str)
    failed = Signal(str, str)
    finished = Signal()


class ModelWarmupWorker(QRunnable):
    """Warm installed recognition engines sequentially in one background task."""

    def __init__(self, manager: BackendManager, backend_keys: tuple[str, ...]) -> None:
        super().__init__()
        self.manager = manager
        self.backend_keys = backend_keys
        self.signals = ModelWarmupSignals()

    @Slot()
    def run(self) -> None:
        for key in self.backend_keys:
            self.signals.started.emit(key)
            try:
                self.manager.warmup(key)
            except Exception as exc:
                message = str(exc).strip() or type(exc).__name__
                self.signals.failed.emit(key, message)
                continue
            self.signals.succeeded.emit(key)
        self.signals.finished.emit()
