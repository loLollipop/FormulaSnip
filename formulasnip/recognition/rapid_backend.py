from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from PIL import Image

from formulasnip.core.latex import normalize_latex
from formulasnip.domain import RecognitionResult
from formulasnip.exceptions import BackendUnavailableError, RecognitionError
from formulasnip.recognition.base import RecognitionBackend
from formulasnip.recognition.quality import has_fatal_output_issue

_CONFIG_PATH = Path(__file__).with_name("rapid_config.yaml")


class RapidLatexBackend(RecognitionBackend):
    key = "rapid"
    display_name = "RapidLaTeXOCR（CPU）"
    install_hint = "uv sync"

    def __init__(self) -> None:
        self._model: Any | None = None

    @classmethod
    def is_available(cls) -> bool:
        return find_spec("rapid_latex_ocr") is not None

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        if not self.is_available():
            raise BackendUnavailableError(
                f"尚未安装 {self.display_name}。请在项目目录运行：{self.install_hint}"
            )
        try:
            from rapid_latex_ocr import LaTeXOCR

            self._model = LaTeXOCR(config_path=_CONFIG_PATH)
        except Exception as exc:
            raise RecognitionError(
                "RapidLaTeXOCR 初始化失败。第一次使用需要联网下载模型，之后可以离线运行。"
            ) from exc
        return self._model

    def recognize(self, image: Image.Image) -> RecognitionResult:
        rgb_array = np.ascontiguousarray(np.asarray(image.convert("RGB"), dtype=np.uint8))
        started = perf_counter()
        try:
            prediction, model_elapsed = self._load_model()(rgb_array)
        except (BackendUnavailableError, RecognitionError):
            raise
        except Exception as exc:
            raise RecognitionError(f"RapidLaTeXOCR 识别失败：{exc}") from exc
        elapsed = max(float(model_elapsed), perf_counter() - started)
        latex = normalize_latex(str(prediction))
        if not latex:
            raise RecognitionError("模型没有返回公式，请调整截图范围后重试。")
        if has_fatal_output_issue(latex):
            raise RecognitionError(
                "RapidLaTeXOCR 输出异常过长或出现重复片段，请缩小截图范围或改用智能模式。"
            )
        return RecognitionResult(latex, self.display_name, elapsed)
