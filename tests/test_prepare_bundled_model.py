from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "prepare_bundled_model_strict_destination",
        ROOT / "scripts" / "prepare_bundled_model.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = _load_builder()


def test_model_preparation_rejects_allowed_root_itself(monkeypatch: Any) -> None:
    allowed_root = ROOT / "build" / "bundled-models"

    def unsafe_download_started(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("preparation continued for the allowed root")

    monkeypatch.setattr(BUILDER, "_download_archive", unsafe_download_started)
    with pytest.raises(BUILDER.ModelBundleError, match="strict child"):
        BUILDER.prepare_model_bundle(
            allowed_root,
            {"model_id": "model", "files": []},
        )
