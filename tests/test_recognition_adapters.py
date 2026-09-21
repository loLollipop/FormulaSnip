from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from PIL import Image

from formulasnip.exceptions import RecognitionError
from formulasnip.recognition import mathcraft_backend
from formulasnip.recognition.mathcraft_backend import _InProcessMathCraftBackend


@dataclass
class FakeResult:
    text: str


class FakeRuntime:
    def __init__(self, *, provider_preference: str, text: str = r"\frac{x}{y}") -> None:
        assert provider_preference == "cpu"
        self.text = text
        self.images: list[Image.Image] = []
        self.warmups: list[str] = []

    def recognize_formula(self, image: Image.Image) -> FakeResult:
        self.images.append(image)
        return FakeResult(self.text)

    def warmup(self, profile: str) -> None:
        self.warmups.append(profile)


def test_mathcraft_uses_injected_cpu_runtime_without_package_or_download(
    monkeypatch: Any,
) -> None:
    runtimes: list[FakeRuntime] = []

    def factory(**kwargs: Any) -> FakeRuntime:
        runtime = FakeRuntime(**kwargs, text=r"  \frac{x}{y}  ")
        runtimes.append(runtime)
        return runtime

    backend = _InProcessMathCraftBackend(runtime_factory=factory)
    monkeypatch.setattr(backend, "is_available", lambda: False)
    result = backend.recognize(Image.new("L", (30, 20), "white"))

    assert result.latex == r"\frac{x}{y}"
    assert runtimes[0].images[0].mode == "RGB"


@pytest.mark.parametrize("formula", ("", "   ", r"\alpha+x" * 130))
def test_mathcraft_rejects_empty_or_fatal_output(formula: str) -> None:
    backend = _InProcessMathCraftBackend(
        runtime_factory=lambda **kwargs: FakeRuntime(**kwargs, text=formula)
    )

    with pytest.raises(RecognitionError, match="没有返回公式|输出异常"):
        backend.recognize(Image.new("RGB", (30, 20), "white"))


@pytest.mark.parametrize(
    "formula",
    (
        r"\begin{pmatrix}0&0&0&0\\0&0&0&0\\0&0&0&0\\0&0&0&0\end{pmatrix}",
        r"\frac{x}{y}+\frac{x}{y}+\frac{x}{y}+\frac{x}{y}",
        r"\text{a a a a a a a a}",
        r"\frac{x}{y",
    ),
)
def test_mathcraft_keeps_nonfatal_output(formula: str) -> None:
    backend = _InProcessMathCraftBackend(
        runtime_factory=lambda **kwargs: FakeRuntime(**kwargs, text=formula)
    )
    assert backend.recognize(Image.new("RGB", (30, 20), "white")).latex == formula


def test_mathcraft_warmup_loads_once_and_uses_formula_profile() -> None:
    runtimes: list[FakeRuntime] = []

    def factory(**kwargs: Any) -> FakeRuntime:
        runtime = FakeRuntime(**kwargs)
        runtimes.append(runtime)
        return runtime

    backend = _InProcessMathCraftBackend(runtime_factory=factory)
    backend.warmup()
    backend.warmup()

    assert len(runtimes) == 1
    assert runtimes[0].warmups == ["formula"]
    assert len(runtimes[0].images) == 1
    assert runtimes[0].images[0].mode == "RGB"
    assert runtimes[0].images[0].size == (48, 24)


def test_bundled_model_verification_detects_same_size_corruption(
    tmp_path: Path,
) -> None:
    content = b"valid model"
    model_dir = tmp_path / "models" / "mathcraft-formula-rec"
    model_dir.mkdir(parents=True)
    model_path = model_dir / "model.onnx"
    model_path.write_bytes(content)
    lock_path = tmp_path / "MODEL_ASSETS.json"
    lock_path.write_text(
        json.dumps(
            {
                "model_id": "mathcraft-formula-rec",
                "files": [
                    {
                        "path": "model.onnx",
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        mathcraft_backend._verify_bundled_model_root(
            tmp_path / "models", lock_path, cache_path=tmp_path / "verification.json"
        )
        is None
    )
    model_path.write_bytes(b"broken mode")
    assert "hash mismatch" in str(
        mathcraft_backend._verify_bundled_model_root(
            tmp_path / "models", lock_path, cache_path=tmp_path / "verification.json"
        )
    )


def _model_bundle(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    content = b"valid model"
    root = tmp_path / "models"
    model_path = root / "mathcraft-formula-rec" / "model.onnx"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(content)
    lock_path = tmp_path / "MODEL_ASSETS.json"
    lock_path.write_text(
        json.dumps(
            {
                "model_id": "mathcraft-formula-rec",
                "files": [
                    {
                        "path": "model.onnx",
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root, lock_path, model_path, tmp_path / "verification.json"


def test_bundled_model_verification_cache_hit_still_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lock_path, model_path, cache_path = _model_bundle(tmp_path)
    assert mathcraft_backend._verify_bundled_model_root(
        root, lock_path, cache_path=cache_path
    ) is None
    original = mathcraft_backend._sha256_file
    hashed: list[Path] = []
    monkeypatch.setattr(mathcraft_backend, "_sha256_file",
                        lambda path: hashed.append(path) or original(path))
    assert mathcraft_backend._verify_bundled_model_root(
        root, lock_path, cache_path=cache_path
    ) is None
    assert hashed == [model_path]


def test_same_size_corruption_with_forged_cache_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from formulasnip.update import installed_model_bundle_identity

    root, lock_path, model_path, cache_path = _model_bundle(tmp_path)
    assert mathcraft_backend._verify_bundled_model_root(
        root, lock_path, cache_path=cache_path
    ) is None
    model_path.write_bytes(b"!" * model_path.stat().st_size)
    forged = json.loads(cache_path.read_text(encoding="utf-8"))
    forged["files"]["model.onnx"] = mathcraft_backend._model_file_identity(model_path)
    cache_path.write_text(json.dumps(forged), encoding="utf-8")
    assert "hash mismatch" in str(mathcraft_backend._verify_bundled_model_root(
        root, lock_path, cache_path=cache_path
    ))
    monkeypatch.setattr(mathcraft_backend, "_model_verification_cache_path", lambda: cache_path)
    assert installed_model_bundle_identity(lock_path=lock_path, bundled_root=root) is None


def test_bundled_model_replaced_during_hash_fails_without_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, lock_path, model_path, cache_path = _model_bundle(tmp_path)
    original_hash = mathcraft_backend._sha256_file

    def replace_during_hash(path: Path) -> str:
        digest = original_hash(path)
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(b"other model")
        replacement.replace(path)
        return digest

    monkeypatch.setattr(mathcraft_backend, "_sha256_file", replace_during_hash)
    problem = mathcraft_backend._verify_bundled_model_root(
        root, lock_path, cache_path=cache_path
    )

    assert "changed during verification" in str(problem)
    assert model_path.read_bytes() == b"other model"
    assert not cache_path.exists()

@pytest.mark.parametrize("change", ["metadata", "lock", "invalid-cache"])
def test_bundled_model_verification_cache_changes_force_rehash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    root, lock_path, model_path, cache_path = _model_bundle(tmp_path)
    assert mathcraft_backend._verify_bundled_model_root(
        root, lock_path, cache_path=cache_path
    ) is None
    if change == "metadata":
        stat = model_path.stat()
        os.utime(
            model_path,
            ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000),
        )
    elif change == "lock":
        lock_path.write_text(lock_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    else:
        cache_path.write_text("not json", encoding="utf-8")

    calls: list[Path] = []
    original = mathcraft_backend._sha256_file

    def record(path: Path) -> str:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(mathcraft_backend, "_sha256_file", record)
    assert mathcraft_backend._verify_bundled_model_root(
        root, lock_path, cache_path=cache_path
    ) is None
    assert calls == [model_path]


def test_bundled_model_verification_rejects_non_object_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "MODEL_ASSETS.json"
    lock_path.write_text("[]", encoding="utf-8")

    assert (
        mathcraft_backend._verify_bundled_model_root(tmp_path / "models", lock_path)
        == "model lock root is not an object"
    )


def test_corrupt_bundle_is_disabled_without_removing_user_cache(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    user_cache = tmp_path / "user-cache"
    user_cache.mkdir()
    marker = user_cache / "existing-model"
    marker.write_text("keep", encoding="utf-8")
    disabled_bundle = tmp_path / "MODEL_ASSETS.json"
    disabled_bundle.write_text("{}", encoding="utf-8")
    options: dict[str, Any] = {}

    class Runtime:
        def __init__(self, **kwargs: Any) -> None:
            options.update(kwargs)

    fake_mathcraft = ModuleType("mathcraft_ocr")
    fake_mathcraft.MathCraftRuntime = Runtime  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mathcraft_ocr", fake_mathcraft)
    monkeypatch.setattr(mathcraft_backend, "configure_runtime", lambda: None)
    monkeypatch.setattr(_InProcessMathCraftBackend, "is_available", lambda _cls: True)
    monkeypatch.setattr(
        mathcraft_backend,
        "_bundled_runtime_configuration",
        lambda: (disabled_bundle, "hash mismatch"),
    )

    backend = _InProcessMathCraftBackend()
    backend._load_runtime()

    assert options["bundled_models_dir"] == disabled_bundle
    assert marker.read_text(encoding="utf-8") == "keep"


def test_frozen_bundle_ignores_environment_override(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    frozen_root = tmp_path / "frozen"
    expected_root = frozen_root / "MathCraft" / "models"
    hostile_root = tmp_path / "override"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(frozen_root), raising=False)
    monkeypatch.setenv("MATHCRAFT_BUNDLED_MODELS_DIR", str(hostile_root))
    monkeypatch.setattr(mathcraft_backend, "_model_lock_path", lambda: tmp_path / "lock")
    verified: list[Path] = []

    def verify(root: Path, _lock: Path) -> None:
        verified.append(root)
        return None

    monkeypatch.setattr(mathcraft_backend, "_verify_bundled_model_root", verify)

    selected, problem = mathcraft_backend._bundled_runtime_configuration()

    assert selected == expected_root
    assert problem is None
    assert verified == [expected_root]
