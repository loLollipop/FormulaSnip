from __future__ import annotations

import json
from pathlib import Path

import pytest

from formulasnip.domain import RecognitionResult
from scripts.benchmark_recognition import load_manifest, run_benchmark


def test_versioned_manifest_has_hash_license_and_stats() -> None:
    root = Path(__file__).resolve().parents[1]
    samples = load_manifest(root / "benchmarks" / "manifest.json")
    assert {sample["id"] for sample in samples} == {
        "synthetic_hyperbola",
        "synthetic_integral",
    }
    assert all(sample["license"] == "CC0-1.0" for sample in samples)

    class FakeManager:
        def __init__(self) -> None:
            self.predictions = [
                prediction
                for sample in samples
                for prediction in (sample["expected"], sample["expected"])
            ]

        def recognize(self, _image: object, _backend: str) -> RecognitionResult:
            return RecognitionResult(self.predictions.pop(0), "fake", 0.001)

    report = run_benchmark(samples, "auto", 2, FakeManager())  # type: ignore[arg-type]
    assert report["summary"]["normalized_exact_count"] == 2
    assert report["summary"]["normalized_exact_rate"] == 1.0
    assert all(len(sample["timings_seconds"]) == 2 for sample in report["samples"])


def test_manifest_rejects_hash_mismatch(tmp_path: Path) -> None:
    asset = tmp_path / "formula.png"
    asset.write_bytes(b"image")
    manifest = {
        "schema_version": 1,
        "samples": [
            {
                "id": "bad",
                "path": "formula.png",
                "sha256": "0" * 64,
                "license": "CC0-1.0",
                "source": "synthetic",
                "expected": "x",
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="hash"):
        load_manifest(path)
