from __future__ import annotations

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "prepare_bundled_model",
        ROOT / "scripts" / "prepare_bundled_model.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = _load_builder()


def _minimal_lock_document(*, model_id: str = "model") -> dict[str, object]:
    content = b"data"
    return {
        "schema_version": 1,
        "model_id": model_id,
        "model_version": "1",
        "source_url": "https://github.com/example/project/releases/download/v1/model.zip",
        "archive_size": 1,
        "archive_sha256": "0" * 64,
        "license": "MIT",
        "files": [
            {
                "path": "model.bin",
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }


def test_production_model_lock_is_complete() -> None:
    lock = BUILDER.load_model_lock(ROOT / "MODEL_ASSETS.json")

    assert lock["model_id"] == "mathcraft-formula-rec"
    assert lock["archive_size"] == 108_795_631
    assert len(lock["files"]) == 8
    assert {item["path"] for item in lock["files"]} >= {
        "encoder_model.onnx",
        "decoder_model.onnx",
        "tokenizer.json",
    }


def test_model_directory_verification_rejects_missing_extra_and_changed_files(
    tmp_path: Path,
) -> None:
    content = b"pinned model content"
    lock = {
        "files": [
            {
                "path": "model.onnx",
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ]
    }
    model_dir = tmp_path / "model"
    model_dir.mkdir()

    with pytest.raises(BUILDER.ModelBundleError, match="file set"):
        BUILDER.verify_model_directory(model_dir, lock)

    model_file = model_dir / "model.onnx"
    model_file.write_bytes(content)
    BUILDER.verify_model_directory(model_dir, lock)

    (model_dir / "unexpected.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(BUILDER.ModelBundleError, match="file set"):
        BUILDER.verify_model_directory(model_dir, lock)
    (model_dir / "unexpected.txt").unlink()

    model_file.write_bytes(b"changed model content")
    with pytest.raises(BUILDER.ModelBundleError, match="size mismatch"):
        BUILDER.verify_model_directory(model_dir, lock)


def test_model_preparation_refuses_destination_outside_build_staging(
    tmp_path: Path,
) -> None:
    lock = BUILDER.load_model_lock(ROOT / "MODEL_ASSETS.json")

    with pytest.raises(BUILDER.ModelBundleError, match="must stay below"):
        BUILDER.prepare_model_bundle(tmp_path / "model", lock)


@pytest.mark.parametrize(
    "model_id",
    ("../model", r"..\model", "/model", r"C:\model", "C:/model", "nested/model"),
)
def test_model_lock_rejects_nonportable_model_ids(
    tmp_path: Path,
    model_id: str,
) -> None:
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(
        json.dumps(_minimal_lock_document(model_id=model_id)),
        encoding="utf-8",
    )

    with pytest.raises(BUILDER.ModelBundleError, match="Model id"):
        BUILDER.load_model_lock(lock_path)


@pytest.mark.parametrize(
    "member",
    ("../escape", r"..\escape", "/escape", r"C:\escape", "C:/escape"),
)
def test_model_archive_rejects_nonportable_members(
    tmp_path: Path,
    member: str,
) -> None:
    archive_path = tmp_path / "model.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("model.bin", b"data")
        archive.writestr(member, b"bad")
    destination = tmp_path / "model"
    destination.mkdir()

    with pytest.raises(BUILDER.ModelBundleError, match="archive member"):
        BUILDER._extract_expected_files(
            archive_path,
            destination,
            _minimal_lock_document(),
        )


def test_model_archive_checks_locked_size_before_extraction(tmp_path: Path) -> None:
    archive_path = tmp_path / "model.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("model.bin", b"data beyond the locked size")
    destination = tmp_path / "model"
    destination.mkdir()

    with pytest.raises(BUILDER.ModelBundleError, match="entry size mismatch"):
        BUILDER._extract_expected_files(
            archive_path,
            destination,
            _minimal_lock_document(),
        )
    assert not (destination / "model.bin").exists()
