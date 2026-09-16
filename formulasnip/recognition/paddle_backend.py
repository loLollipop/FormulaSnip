from __future__ import annotations

import re
from importlib.util import find_spec
from time import perf_counter
from typing import Any

import numpy as np
from PIL import Image

from formulasnip.core.latex import normalize_latex
from formulasnip.domain import RecognitionResult
from formulasnip.exceptions import BackendUnavailableError, RecognitionError
from formulasnip.recognition.base import RecognitionBackend
from formulasnip.recognition.quality import has_fatal_output_issue

_STYLE_COMMAND = re.compile(r"\\(?:textstyle|displaystyle|scriptstyle|scriptscriptstyle)\b\s*")


class PaddleFormulaBackend(RecognitionBackend):
    key = "paddle"
    display_name = "PP-FormulaNet-S（CPU）"
    install_hint = "uv sync"

    def __init__(self) -> None:
        self._model: Any | None = None

    @classmethod
    def is_available(cls) -> bool:
        return find_spec("paddleocr") is not None and find_spec("paddle") is not None

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        if not self.is_available():
            raise BackendUnavailableError(
                "尚未安装 PP-FormulaNet-S。请在项目目录运行：uv sync"
            )
        try:
            from paddleocr import FormulaRecognition

            self._model = FormulaRecognition(model_name="PP-FormulaNet-S", device="cpu")
        except Exception as exc:
            raise RecognitionError(
                "PP-FormulaNet-S 初始化失败。第一次使用需要联网下载模型；"
                "请确认默认依赖已完整安装。"
            ) from exc
        return self._model

    def recognize(self, image: Image.Image) -> RecognitionResult:
        array = np.ascontiguousarray(np.asarray(image.convert("RGB"), dtype=np.uint8))
        started = perf_counter()
        try:
            results = list(self._load_model().predict(input=array, batch_size=1))
            if not results:
                raise RecognitionError("PP-FormulaNet-S 没有返回识别结果。")
            prediction = _extract_formula(results[0])
        except (BackendUnavailableError, RecognitionError):
            raise
        except Exception as exc:
            raise RecognitionError(f"PP-FormulaNet-S 识别失败：{exc}") from exc
        elapsed = perf_counter() - started
        latex = normalize_latex(_STYLE_COMMAND.sub("", prediction)).strip()
        if not latex:
            raise RecognitionError("模型没有返回公式，请调整截图范围后重试。")
        if has_fatal_output_issue(latex):
            raise RecognitionError(
                "PP-FormulaNet-S 输出异常过长，请缩小截图范围或改用智能模式。"
            )
        return RecognitionResult(latex, self.display_name, elapsed)


def _extract_formula(result: Any) -> str:
    payload = getattr(result, "json", result)
    if callable(payload):
        payload = payload()
    if isinstance(payload, dict):
        if "res" in payload and isinstance(payload["res"], dict):
            value = payload["res"].get("rec_formula")
        else:
            value = payload.get("rec_formula")
        if value is not None:
            return str(value)
    raise RecognitionError("PP-FormulaNet-S 返回了无法解析的结果格式。")
