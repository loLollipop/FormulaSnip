from __future__ import annotations

from collections.abc import Callable
from importlib.util import find_spec
from time import perf_counter
from typing import Any

from PIL import Image

from formulasnip.core.latex import normalize_latex
from formulasnip.domain import RecognitionResult
from formulasnip.exceptions import BackendUnavailableError, RecognitionError
from formulasnip.recognition.base import RecognitionBackend
from formulasnip.recognition.mathcraft_worker import MathCraftWorkerClient
from formulasnip.recognition.quality import has_fatal_output_issue
from formulasnip.runtime import configure_runtime


class MathCraftBackend(RecognitionBackend):
    key = "mathcraft"
    display_name = "MathCraft OCR（CPU）"
    install_hint = "uv sync"

    def __init__(self, *, client: MathCraftWorkerClient | None = None) -> None:
        self._client = client or MathCraftWorkerClient()

    @classmethod
    def is_available(cls) -> bool:
        return find_spec("mathcraft_ocr") is not None

    def recognize(self, image: Image.Image) -> RecognitionResult:
        started = perf_counter()
        result = self._client.recognize(image)
        return RecognitionResult(result.latex, self.display_name, perf_counter() - started)

    def warmup(self) -> None:
        self._client.warmup()

    def close(self) -> None:
        self._client.close()


class _InProcessMathCraftBackend(RecognitionBackend):
    """Implementation used exclusively inside the spawned MathCraft worker."""

    key = MathCraftBackend.key
    display_name = MathCraftBackend.display_name
    install_hint = MathCraftBackend.install_hint

    def __init__(self, *, runtime_factory: Callable[..., Any] | None = None) -> None:
        self._runtime: Any | None = None
        self._runtime_factory = runtime_factory

    @classmethod
    def is_available(cls) -> bool:
        return find_spec("mathcraft_ocr") is not None

    def _load_runtime(self) -> Any:
        if self._runtime is not None:
            return self._runtime
        if self._runtime_factory is None and not self.is_available():
            raise BackendUnavailableError(
                "尚未安装 MathCraft OCR。请在项目目录运行：uv sync"
            )
        try:
            configure_runtime()
            if self._runtime_factory is None:
                from mathcraft_ocr import MathCraftRuntime

                runtime_factory = MathCraftRuntime
            else:
                runtime_factory = self._runtime_factory
            self._runtime = runtime_factory(provider_preference="cpu")
        except Exception as exc:
            raise RecognitionError(
                "MathCraft OCR 初始化失败。第一次使用需要联网下载模型；"
                "下载完成后可以完全离线运行。"
            ) from exc
        return self._runtime

    def recognize(self, image: Image.Image) -> RecognitionResult:
        rgb = image.convert("RGB")
        started = perf_counter()
        try:
            result = self._load_runtime().recognize_formula(rgb)
            prediction = str(getattr(result, "text", ""))
        except (BackendUnavailableError, RecognitionError):
            raise
        except Exception as exc:
            raise RecognitionError(f"MathCraft OCR 识别失败：{exc}") from exc
        elapsed = perf_counter() - started
        latex = normalize_latex(prediction).strip()
        if not latex:
            raise RecognitionError("MathCraft OCR 没有返回公式，请调整截图范围后重试。")
        if has_fatal_output_issue(latex):
            raise RecognitionError(
                "MathCraft OCR 输出异常过长，请缩小截图范围后重试。"
            )
        return RecognitionResult(latex, self.display_name, elapsed)

    def warmup(self) -> None:
        self._load_runtime().warmup("formula")
