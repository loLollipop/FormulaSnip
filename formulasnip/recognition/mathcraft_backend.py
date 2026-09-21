from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Callable
from contextlib import suppress
from importlib.util import find_spec
from pathlib import Path
from threading import Event
from time import perf_counter
from typing import Any

from PIL import Image, ImageDraw

from formulasnip.core.latex import normalize_latex
from formulasnip.domain import RecognitionResult
from formulasnip.exceptions import BackendUnavailableError, RecognitionError
from formulasnip.recognition.base import RecognitionBackend
from formulasnip.recognition.mathcraft_worker import MathCraftWorkerClient
from formulasnip.recognition.quality import has_fatal_output_issue
from formulasnip.runtime import configure_runtime

_FORMULA_MODEL_ID = "mathcraft-formula-rec"
_MODEL_VERIFICATION_CACHE_SCHEMA = 2


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_lock_path() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "MODEL_ASSETS.json"
    return Path(__file__).resolve().parents[2] / "MODEL_ASSETS.json"


def _model_verification_cache_path() -> Path:
    local_data = os.environ.get("LOCALAPPDATA")
    if local_data:
        return Path(local_data) / "FormulaSnip" / "model-verification.json"
    return Path.home() / ".formulasnip" / "model-verification.json"


def _write_verification_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _model_file_identity(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
    }


def _verify_bundled_model_root(
    root: Path,
    lock_path: Path,
    *,
    cache_path: Path | None = None,
) -> str | None:
    """Return a diagnostic when the immutable bundled formula model is damaged."""

    try:
        lock_bytes = lock_path.read_bytes()
        lock = json.loads(lock_bytes)
        if not isinstance(lock, dict):
            return "model lock root is not an object"
        if lock.get("model_id") != _FORMULA_MODEL_ID:
            return "model lock has an unexpected model id"
        files = lock["files"]
        if not isinstance(files, list) or not files:
            return "model lock has no files"
        model_root = root.resolve()
        model_dir = model_root / _FORMULA_MODEL_ID
        expected = {str(item["path"]): item for item in files}
        actual_paths = tuple(path for path in model_dir.rglob("*") if path.is_file())
        actual = {path.relative_to(model_dir).as_posix() for path in actual_paths}
        if actual != set(expected):
            return "bundled model file set differs from the release lock"
        metadata: dict[str, dict[str, int]] = {}
        for relative, item in expected.items():
            file_path = model_dir / relative
            identity = _model_file_identity(file_path)
            if identity["size"] != int(item["size"]):
                return f"bundled model size mismatch: {relative}"
            metadata[relative] = identity

        verification_cache = cache_path or _model_verification_cache_path()
        cache_binding: dict[str, Any] = {
            "schema_version": _MODEL_VERIFICATION_CACHE_SCHEMA,
            "model_id": _FORMULA_MODEL_ID,
            "model_root": str(model_dir.resolve()),
            "lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
            "files": metadata,
        }
        for relative, item in expected.items():
            file_path = model_dir / relative
            if _sha256_file(file_path).casefold() != str(item["sha256"]).casefold():
                return f"bundled model hash mismatch: {relative}"
            if _model_file_identity(file_path) != metadata[relative]:
                return f"bundled model changed during verification: {relative}"
        # Diagnostic record only: user-writable metadata never substitutes for
        # hashing, including when selecting a lightweight update package.
        with suppress(OSError):
            _write_verification_cache(verification_cache, cache_binding)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return f"unable to verify bundled model: {exc}"
    return None


def _bundled_runtime_configuration() -> tuple[Path | None, str | None]:
    """Pin a verified bundle, or explicitly disable a damaged one for fallback."""

    from mathcraft_ocr.cache import bundled_models_dir

    frozen_root = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and frozen_root:
        # A release build must use the model shipped beside this executable.
        # Do not let a machine-wide environment override silently replace it.
        bundled_root = Path(frozen_root) / "MathCraft" / "models"
    else:
        bundled_root = bundled_models_dir()
        if bundled_root is None:
            return None, None
    lock_path = _model_lock_path()
    problem = _verify_bundled_model_root(bundled_root, lock_path)
    if problem is None:
        return bundled_root, None
    # Passing an existing file as the bundle root prevents MathCraft from
    # rediscovering the bad directory while leaving its user cache untouched.
    return lock_path, problem


class MathCraftBackend(RecognitionBackend):
    key = "mathcraft"
    display_name = "MathCraft OCR（CPU）"
    install_hint = "uv sync"

    def __init__(self, *, client: MathCraftWorkerClient | None = None) -> None:
        self._client = client or MathCraftWorkerClient()

    @classmethod
    def is_available(cls) -> bool:
        return find_spec("mathcraft_ocr") is not None

    def recognize(
        self,
        image: Image.Image,
        *,
        cancel_event: Event | None = None,
    ) -> RecognitionResult:
        started = perf_counter()
        result = self._client.recognize(image, cancel_event=cancel_event)
        return RecognitionResult(result.latex, self.display_name, perf_counter() - started)

    def warmup(self) -> None:
        self._client.warmup()

    def cancel_current(self) -> None:
        self._client.cancel_current()

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
        self._warmed_up = False
        self._bundled_model_problem: str | None = None

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
                bundled_dir, self._bundled_model_problem = (
                    _bundled_runtime_configuration()
                )
                runtime_options: dict[str, Any] = {"provider_preference": "cpu"}
                if bundled_dir is not None:
                    runtime_options["bundled_models_dir"] = bundled_dir
            else:
                runtime_factory = self._runtime_factory
                runtime_options = {"provider_preference": "cpu"}
            self._runtime = runtime_factory(**runtime_options)
        except Exception as exc:
            raise RecognitionError(self._runtime_failure_message("初始化失败")) from exc
        return self._runtime

    def _runtime_failure_message(self, action: str) -> str:
        if self._bundled_model_problem:
            return (
                f"MathCraft OCR {action}：内置模型校验失败，且用户模型缓存或"
                "自动下载的回退模型不可用。请检查网络，或重新安装以修复内置模型。"
                f"（{self._bundled_model_problem}）"
            )
        return (
            f"MathCraft OCR {action}。安装版请重新安装以修复内置模型；"
            "源码运行首次使用需要联网下载模型。"
        )

    def recognize(self, image: Image.Image) -> RecognitionResult:
        rgb = image.convert("RGB")
        started = perf_counter()
        try:
            result = self._load_runtime().recognize_formula(rgb)
            prediction = str(getattr(result, "text", ""))
        except (BackendUnavailableError, RecognitionError):
            raise
        except Exception as exc:
            if self._bundled_model_problem:
                raise RecognitionError(
                    self._runtime_failure_message("识别失败")
                ) from exc
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
        if self._warmed_up:
            return
        runtime = self._load_runtime()
        try:
            plan = runtime.warmup("formula")
            if plan is not None and not getattr(plan, "ready", True):
                raise RecognitionError(self._runtime_failure_message("预热失败"))
        except RecognitionError:
            raise
        except Exception as exc:
            raise RecognitionError(self._runtime_failure_message("预热失败")) from exc
        # MathCraft's lightweight warmup loads the network, but the first full
        # request still pays preprocessing, graph planning and decoder setup.
        # Run one tiny, deterministic probe during application startup so the
        # user's first screenshot reaches the already exercised inference path.
        probe = Image.new("RGB", (48, 24), "white")
        ImageDraw.Draw(probe).text((8, 4), "x", fill="black")
        try:
            runtime.recognize_formula(probe)
        except Exception as exc:
            raise RecognitionError(self._runtime_failure_message("预热失败")) from exc
        self._warmed_up = True
