from __future__ import annotations

import logging
from threading import Event, Lock

from PIL import Image

from formulasnip.core.preview import is_formula_previewable
from formulasnip.diagnostics import log_exception
from formulasnip.domain import RecognitionCandidate, RecognitionResult
from formulasnip.exceptions import BackendUnavailableError, RecognitionError
from formulasnip.recognition.base import RecognitionBackend
from formulasnip.recognition.mathcraft_backend import MathCraftBackend
from formulasnip.recognition.quality import (
    assess_latex,
    diagnose_image,
    has_complex_image_layout,
    has_complex_structure,
)

_BACKEND_TYPES: tuple[type[RecognitionBackend], ...] = (MathCraftBackend,)
_LEGACY_BACKEND_KEYS = frozenset({"auto", "rapid", "paddle"})
_LOG = logging.getLogger(__name__)


def backend_summaries() -> list[tuple[str, str, bool]]:
    return [
        (backend.key, backend.display_name, backend.is_available()) for backend in _BACKEND_TYPES
    ]


class BackendManager:
    """Resolve, cache and serialize access to the MathCraft recognizer."""

    def __init__(self) -> None:
        self._instances: dict[str, RecognitionBackend] = {}
        self._lock = Lock()
        self._state_lock = Lock()
        self._closed = False
        self._active_task_identity: object | None = None
        self._cancelled_task_identity: object | None = None

    def recognize(
        self,
        image: Image.Image,
        selected_key: str = "mathcraft",
        *,
        task_identity: object | None = None,
        cancel_event: Event | None = None,
    ) -> RecognitionResult:
        with self._lock:
            with self._state_lock:
                self._active_task_identity = task_identity
                self._cancelled_task_identity = None
            _LOG.info("recognition-start mode=%s width=%d height=%d", selected_key, *image.size)
            try:
                backend = self._get_backend(selected_key)
                with self._state_lock:
                    if (
                        task_identity is not None
                        and self._cancelled_task_identity is task_identity
                    ):
                        raise RecognitionError("公式识别任务已取消。")
                backend_result = (
                    backend.recognize(image, cancel_event=cancel_event)
                    if isinstance(backend, MathCraftBackend)
                    else backend.recognize(image)
                )
                result = _with_quality_warning(
                    backend_result,
                    diagnose_image(image),
                    image=image,
                )
            except Exception as exc:
                log_exception("recognition-failed", exc)
                raise
            finally:
                with self._state_lock:
                    if self._active_task_identity is task_identity:
                        self._active_task_identity = None
                    if self._cancelled_task_identity is task_identity:
                        self._cancelled_task_identity = None
            _LOG.info(
                "recognition-done backend=%s strategy=%s seconds=%.3f warnings=%d",
                result.backend_name,
                result.strategy,
                result.elapsed_seconds,
                len(result.warnings),
            )
            return result

    def cancel_current(self, task_identity: object) -> bool:
        """Cancel the matching active task without invalidating manager reuse."""

        with self._state_lock:
            if self._active_task_identity is not task_identity:
                return False
            self._cancelled_task_identity = task_identity
            backend = self._instances.get("mathcraft")
            if backend is not None:
                cancel = getattr(backend, "cancel_current", None)
                if callable(cancel):
                    # Keep task ownership stable until the native generation is
                    # disposed, so a delayed cancel cannot terminate its successor.
                    cancel()
            return True

    def warmup(self, key: str = "mathcraft") -> None:
        """Warm the MathCraft backend without blocking an active recognition call."""

        _LOG.info("warmup-start backend=%s", key)
        try:
            self._get_backend(key).warmup()
        except Exception as exc:
            log_exception("warmup-failed", exc)
            raise
        _LOG.info("warmup-done backend=%s", key)

    def close(self) -> None:
        """Stop external workers even if a model is blocked in native code."""

        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            backends = tuple(self._instances.values())
        for backend in backends:
            try:
                backend.close()
            except Exception as exc:
                log_exception("recognition-service-close-failed", exc)
        _LOG.info("recognition-services-closed")

    def _get_backend(self, selected_key: str) -> RecognitionBackend:
        with self._state_lock:
            if self._closed:
                raise RecognitionError("公式识别服务已关闭。")
            key = self._resolve_key(selected_key)
            if key not in self._instances:
                self._instances[key] = MathCraftBackend()
            return self._instances[key]

    @staticmethod
    def _resolve_key(selected_key: str) -> str:
        key = "mathcraft" if selected_key in _LEGACY_BACKEND_KEYS else selected_key
        if key != "mathcraft":
            raise BackendUnavailableError(f"未知识别后端：{selected_key}")
        if not MathCraftBackend.is_available():
            raise BackendUnavailableError(
                f"尚未安装 {MathCraftBackend.display_name}。请运行："
                f"{MathCraftBackend.install_hint}"
            )
        return key


def _candidate(result: RecognitionResult) -> RecognitionCandidate:
    report = assess_latex(result.latex)
    structurally_previewable = is_formula_previewable(result.latex)
    return RecognitionCandidate(
        result.latex,
        result.backend_name,
        result.elapsed_seconds,
        report.issues,
        None if structurally_previewable else False,
    )


def _candidate_warnings(
    candidate: RecognitionCandidate, warnings: tuple[str, ...]
) -> tuple[str, ...]:
    candidate_warnings: list[str] = []
    if candidate.issues:
        candidate_warnings.append("识别结果需要人工校对：" + "；".join(candidate.issues))
    if candidate.previewable is False:
        candidate_warnings.append(
            "当前识别结果无法生成电子公式预览，可在结果框中继续修改 LaTeX。"
        )
    return (*candidate_warnings, *warnings)


def _with_quality_warning(
    result: RecognitionResult,
    image_warnings: tuple[str, ...] = (),
    *,
    image: Image.Image | None = None,
) -> RecognitionResult:
    candidate = _candidate(result)
    complexity_warnings: tuple[str, ...] = ()
    if has_complex_structure(result.latex) or (
        image is not None and has_complex_image_layout(image)
    ):
        complexity_warnings = ("公式版式或结构较复杂，请对照原图人工核对。",)
    warnings = _candidate_warnings(candidate, (*result.warnings, *image_warnings))
    warnings = tuple(dict.fromkeys((*warnings, *complexity_warnings)))
    alternatives = result.alternatives or (candidate,)
    if warnings == result.warnings and alternatives == result.alternatives:
        return result
    return RecognitionResult(
        result.latex,
        result.backend_name,
        result.elapsed_seconds,
        result.strategy,
        warnings,
        alternatives,
    )
