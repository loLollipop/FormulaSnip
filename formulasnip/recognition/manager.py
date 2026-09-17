from __future__ import annotations

import logging
import re
from threading import Lock
from time import perf_counter

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
    has_clean_partial_command,
    has_complex_image_layout,
    has_complex_structure,
    has_suspected_derivative_confusion,
)
from formulasnip.recognition.rapid_backend import RapidLatexBackend

_BACKEND_TYPES: tuple[type[RecognitionBackend], ...] = (
    RapidLatexBackend,
    MathCraftBackend,
)
_LOG = logging.getLogger(__name__)


def backend_summaries() -> list[tuple[str, str, bool]]:
    return [
        (backend.key, backend.display_name, backend.is_available()) for backend in _BACKEND_TYPES
    ]


class BackendManager:
    """Resolve, cache and serialize access to local formula recognizers."""

    def __init__(self) -> None:
        self._instances: dict[str, RecognitionBackend] = {}
        self._lock = Lock()
        self._state_lock = Lock()
        self._closed = False

    def recognize(self, image: Image.Image, selected_key: str = "auto") -> RecognitionResult:
        with self._lock:
            _LOG.info("recognition-start mode=%s width=%d height=%d", selected_key, *image.size)
            try:
                if selected_key != "auto":
                    result = _with_quality_warning(self._get_backend(selected_key).recognize(image))
                else:
                    result = self._recognize_auto(image)
            except Exception as exc:
                log_exception("recognition-failed", exc)
                raise
            _LOG.info(
                "recognition-done backend=%s strategy=%s seconds=%.3f warnings=%d",
                result.backend_name, result.strategy, result.elapsed_seconds, len(result.warnings),
            )
            return result

    def warmup(self, key: str) -> None:
        """Warm one backend without blocking requests that use another engine."""

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

    def _recognize_auto(self, image: Image.Image) -> RecognitionResult:
        started = perf_counter()
        if not RapidLatexBackend.is_available():
            for key in ("mathcraft",):
                backend_type = next(item for item in _BACKEND_TYPES if item.key == key)
                if backend_type.is_available():
                    result = self._get_backend(key).recognize(image)
                    candidate = _candidate(result)
                    return RecognitionResult(
                        result.latex,
                        result.backend_name,
                        perf_counter() - started,
                        "auto-fallback",
                        _candidate_warnings(
                            candidate,
                            ("推荐的 RapidLaTeXOCR 未安装，已使用可用后端。",),
                        ),
                        (candidate,),
                    )
            raise BackendUnavailableError(
                "没有检测到本地公式模型。请在项目目录运行 `uv sync` 安装默认双引擎。"
            )

        try:
            rapid_result = self._get_backend("rapid").recognize(image)
        except (BackendUnavailableError, RecognitionError):
            for key in ("mathcraft",):
                backend_type = next(item for item in _BACKEND_TYPES if item.key == key)
                if not backend_type.is_available():
                    continue
                try:
                    result = self._get_backend(key).recognize(image)
                except (BackendUnavailableError, RecognitionError):
                    continue
                candidate = _candidate(result)
                return RecognitionResult(
                    result.latex,
                    result.backend_name,
                    perf_counter() - started,
                    f"auto-{key}-fallback",
                    _candidate_warnings(
                        candidate,
                        (f"RapidLaTeXOCR 识别失败，已改用 {result.backend_name}。",),
                    ),
                    (candidate,),
                )
            raise
        rapid_candidate = _candidate(rapid_result)
        image_risks = diagnose_image(image)
        complex_formula = has_complex_structure(rapid_result.latex)
        complex_layout = has_complex_image_layout(image)
        should_review = bool(
            rapid_candidate.issues
            or image_risks
            or complex_formula
            or complex_layout
            or not rapid_candidate.previewable
        )
        if not should_review or not MathCraftBackend.is_available():
            warnings = list(_candidate_warnings(rapid_candidate, image_risks))
            if should_review and not MathCraftBackend.is_available():
                if rapid_candidate.previewable:
                    warnings.append(
                        "检测到复核条件，但 MathCraft OCR 未安装，保留 Rapid 结果。"
                    )
                else:
                    warnings.append(
                        "Rapid 结果无法预览，且 MathCraft OCR 未安装；"
                        "可在结果框中继续修改 LaTeX。"
                    )
            return RecognitionResult(
                rapid_result.latex,
                rapid_result.backend_name,
                perf_counter() - started,
                "auto-rapid",
                tuple(warnings),
                (rapid_candidate,),
            )

        try:
            mathcraft_result = self._get_backend("mathcraft").recognize(image)
        except (BackendUnavailableError, RecognitionError) as exc:
            log_exception("mathcraft-review-failed-keeping-rapid", exc)
            warning = f"MathCraft OCR 复核失败，已保留 Rapid 结果：{exc}"
            return RecognitionResult(
                rapid_result.latex,
                rapid_result.backend_name,
                perf_counter() - started,
                "auto-review-fallback",
                _candidate_warnings(rapid_candidate, (*image_risks, warning)),
                (rapid_candidate,),
            )

        mathcraft_candidate = _candidate(mathcraft_result)
        candidates = (rapid_candidate, mathcraft_candidate)
        winner = _choose_candidate(candidates)
        review_warnings: list[str] = []
        candidates_disagree = (
            _candidate_content_key(rapid_candidate.latex)
            != _candidate_content_key(mathcraft_candidate.latex)
        )
        derivative_confusion = (
            has_suspected_derivative_confusion(rapid_candidate.latex)
            and has_clean_partial_command(mathcraft_candidate.latex)
        )
        if candidates_disagree and derivative_confusion:
            review_warnings.append(
                "两个引擎结果不一致；Rapid 疑似把偏导符号识别为重音字符，"
                "已采用精确候选，复杂公式请重点校对。"
            )
        elif candidates_disagree:
            review_warnings.append(
                "两个引擎结果不一致；已采用精确候选，复杂公式请重点校对。"
            )
        no_preview = not any(candidate.previewable for candidate in candidates)
        if no_preview:
            review_warnings.append(
                "两个引擎均未生成可预览候选；已按候选质量规则保留"
                f" {winner.backend} 结果，请在结果框中修改 LaTeX。"
            )
            strategy = "auto-reviewed-no-preview"
        else:
            strategy = "auto-reviewed"
        return RecognitionResult(
            winner.latex,
            winner.backend,
            perf_counter() - started,
            strategy,
            _candidate_warnings(winner, (*image_risks, *review_warnings)),
            candidates,
        )

    def _get_backend(self, selected_key: str) -> RecognitionBackend:
        with self._state_lock:
            if self._closed:
                raise RecognitionError("公式识别服务已关闭。")
            key = self._resolve_key(selected_key)
            if key not in self._instances:
                backend_type = next(item for item in _BACKEND_TYPES if item.key == key)
                self._instances[key] = backend_type()
            return self._instances[key]

    @staticmethod
    def _resolve_key(selected_key: str) -> str:
        if selected_key == "auto":
            for backend in _BACKEND_TYPES:
                if backend.is_available():
                    return backend.key
            raise BackendUnavailableError(
                "没有检测到本地公式模型。请在项目目录运行 `uv sync` 安装默认双引擎。"
            )
        for backend in _BACKEND_TYPES:
            if backend.key == selected_key:
                if not backend.is_available():
                    raise BackendUnavailableError(
                        f"尚未安装 {backend.display_name}。请运行：{backend.install_hint}"
                    )
                return backend.key
        raise BackendUnavailableError(f"未知识别后端：{selected_key}")


def _candidate(result: RecognitionResult) -> RecognitionCandidate:
    report = assess_latex(result.latex)
    return RecognitionCandidate(
        result.latex,
        result.backend_name,
        result.elapsed_seconds,
        report.issues,
        is_formula_previewable(result.latex),
    )


def _candidate_warnings(
    candidate: RecognitionCandidate, warnings: tuple[str, ...]
) -> tuple[str, ...]:
    candidate_warnings: list[str] = []
    if candidate.issues:
        candidate_warnings.append("识别结果需要人工校对：" + "；".join(candidate.issues))
    if not candidate.previewable:
        candidate_warnings.append(
            "当前识别结果无法生成电子公式预览，可在结果框中继续修改 LaTeX。"
        )
    return (*candidate_warnings, *warnings)


def _with_quality_warning(result: RecognitionResult) -> RecognitionResult:
    candidate = _candidate(result)
    warnings = _candidate_warnings(candidate, result.warnings)
    if warnings == result.warnings:
        return result
    return RecognitionResult(
        result.latex,
        result.backend_name,
        result.elapsed_seconds,
        result.strategy,
        warnings,
        result.alternatives or (candidate,),
    )


def _choose_candidate(
    candidates: tuple[RecognitionCandidate, ...],
) -> RecognitionCandidate:
    rapid, mathcraft = candidates
    rapid_score = assess_latex(rapid.latex).score
    mathcraft_score = assess_latex(mathcraft.latex).score
    rapid_severe = _has_severe_issue(rapid)
    mathcraft_severe = _has_severe_issue(mathcraft)
    if rapid_severe != mathcraft_severe:
        return rapid if not rapid_severe else mathcraft
    if rapid_severe and mathcraft_severe:
        return mathcraft if mathcraft_score > rapid_score else rapid
    if _candidate_content_key(rapid.latex) != _candidate_content_key(mathcraft.latex):
        if (
            has_suspected_derivative_confusion(rapid.latex)
            and not has_clean_partial_command(mathcraft.latex)
        ):
            return rapid
        return mathcraft
    return rapid


def _candidate_content_key(latex: str) -> str:
    """Compare harmless formatting variants without claiming algebraic equivalence."""

    without_sizing = re.sub(r"\\(?:left|right)(?![A-Za-z])", "", latex)

    def normalize_space(match: re.Match[str]) -> str:
        prefix = without_sizing[: match.start()]
        suffix = without_sizing[match.end() :]
        if re.search(r"\\[A-Za-z]+$", prefix) and re.match(r"[A-Za-z]", suffix):
            return " "
        return ""

    return re.sub(r"\s+", normalize_space, without_sizing).strip()


def _has_severe_issue(candidate: RecognitionCandidate) -> bool:
    severe_markers = (
        "括号不配对",
        "缺少反斜杠",
        "重复运算符",
        "环境开始与结束不匹配",
        r"\left 与 \right",
        "重复关系符",
        "异常连续重复",
        "异常重复片段",
        "输出异常",
    )
    return any(
        marker in issue for issue in candidate.issues for marker in severe_markers
    )
