from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from formulasnip.__main__ import _run_model_smoke_test


def test_model_smoke_uses_only_frozen_bundled_resources(
    monkeypatch: Any,
    tmp_path: Path,
    capsys: Any,
) -> None:
    frozen_root = tmp_path / "frozen"
    expected_model = (
        frozen_root / "MathCraft" / "models" / "mathcraft-formula-rec"
    )
    captured: dict[str, Any] = {}

    class FakeRuntime:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def warmup(self, profile: str) -> SimpleNamespace:
            assert profile == "formula"
            return SimpleNamespace(ready=True)

        def check_models(self, *, include_optional: bool) -> dict[str, Any]:
            assert not include_optional
            return {
                "mathcraft-formula-rec": SimpleNamespace(model_dir=expected_model)
            }

        def recognize_formula(self, _image: Any) -> SimpleNamespace:
            return SimpleNamespace(text="x")

    fake_mathcraft = ModuleType("mathcraft_ocr")
    fake_mathcraft.MathCraftRuntime = FakeRuntime  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mathcraft_ocr", fake_mathcraft)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(frozen_root), raising=False)
    monkeypatch.setenv("MATHCRAFT_BUNDLED_MODELS_DIR", str(tmp_path / "hostile"))

    assert _run_model_smoke_test() == 0
    assert captured["bundled_models_dir"] == frozen_root / "MathCraft" / "models"
    assert captured["auto_download"] is False
    assert str(expected_model) in capsys.readouterr().out
