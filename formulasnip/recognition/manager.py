from __future__ import annotations

from threading import Lock
from time import perf_counter

from PIL import Image

from formulasnip.core.preview import is_formula_previewable
from formulasnip.domain import RecognitionCandidate, RecognitionResult
from formulasnip.exceptions import BackendUnavailableError, RecognitionError
from formulasnip.recognition.base import RecognitionBackend
from formulasnip.recognition.paddle_backend import PaddleFormulaBackend
from formulasnip.recognition.quality import assess_latex, diagnose_image, has_complex_structure
from formulasnip.recognition.rapid_backend import RapidLatexBackend

_BACKEND_TYPES: tuple[type[RecognitionBackend], ...] = (
    RapidLatexBackend,
    PaddleFormulaBackend,
)


def backend_summaries() -> list[tuple[str, str, bool]]:
    return [
        (backend.key, backend.display_name, backend.is_available()) for backend in _BACKEND_TYPES
    ]


class BackendManager:
    """Resolve, cache and serialize access to local formula recognizers."""

    def __init__(self) -> None:
        self._instances: dict[str, RecognitionBackend] = {}
        self._lock = Lock()

    def recognize(self, image: Image.Image, selected_key: str = "auto") -> RecognitionResult:
        with self._lock:
            if selected_key != "auto":
                return _with_quality_warning(self._get_backend(selected_key).recognize(image))
            return self._recognize_auto(image)

    def warmup(self, key: str) -> None:
        """Warm one backend while sharing its instance and serialization lock."""

        with self._lock:
            self._get_backend(key).warmup()

    def _recognize_auto(self, image: Image.Image) -> RecognitionResult:
        started = perf_counter()
        if not RapidLatexBackend.is_available():
            for key in ("paddle",):
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
            for key in ("paddle",):
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
        should_review = bool(
            rapid_candidate.issues
            or image_risks
            or complex_formula
            or not rapid_candidate.previewable
        )
        if not should_review or not PaddleFormulaBackend.is_available():
            warnings = list(_candidate_warnings(rapid_candidate, image_risks))
            if should_review and not PaddleFormulaBackend.is_available():
                if rapid_candidate.previewable:
                    warnings.append(
                        "检测到复核条件，但 PP-FormulaNet-S 未安装，保留 Rapid 结果。"
                    )
                else:
                    warnings.append(
                        "Rapid 结果无法预览，且 PP-FormulaNet-S 未安装；"
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
            paddle_result = self._get_backend("paddle").recognize(image)
        except (BackendUnavailableError, RecognitionError) as exc:
            warning = f"PP-FormulaNet-S 复核失败，已保留 Rapid 结果：{exc}"
            return RecognitionResult(
                rapid_result.latex,
                rapid_result.backend_name,
                perf_counter() - started,
                "auto-review-fallback",
                _candidate_warnings(rapid_candidate, (*image_risks, warning)),
                (rapid_candidate,),
            )

        paddle_candidate = _candidate(paddle_result)
        candidates = (rapid_candidate, paddle_candidate)
        winner = _choose_candidate(candidates, prefer_paddle_on_tie=complex_formula)
        no_preview = not any(candidate.previewable for candidate in candidates)
        if no_preview:
            warning = (
                "两个引擎均未生成可预览候选；已按质量评分保留"
                f" {winner.backend} 结果，请在结果框中修改 LaTeX。"
            )
            strategy = "auto-reviewed-no-preview"
        else:
            warning = (
                f"智能模式已用 PP-FormulaNet-S 复核，选择 {winner.backend}；"
                "请与原公式核对采用结果。"
            )
            strategy = "auto-reviewed"
        return RecognitionResult(
            winner.latex,
            winner.backend,
            perf_counter() - started,
            strategy,
            _candidate_warnings(winner, (*image_risks, warning)),
            candidates,
        )

    def _get_backend(self, selected_key: str) -> RecognitionBackend:
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
    candidates: tuple[RecognitionCandidate, ...], *, prefer_paddle_on_tie: bool
) -> RecognitionCandidate:
    rapid, paddle = candidates
    if rapid.previewable != paddle.previewable:
        return rapid if rapid.previewable else paddle
    rapid_score = assess_latex(rapid.latex).score
    paddle_score = assess_latex(paddle.latex).score
    if paddle_score > rapid_score:
        return paddle
    if paddle_score < rapid_score:
        return rapid
    if len(paddle.issues) < len(rapid.issues):
        return paddle
    if len(paddle.issues) > len(rapid.issues):
        return rapid
    return paddle if prefer_paddle_on_tie else rapid
