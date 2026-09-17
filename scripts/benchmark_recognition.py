from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formulasnip.recognition.manager import BackendManager  # noqa: E402
from formulasnip.recognition.quality import assess_latex  # noqa: E402

DEFAULT_MANIFEST = ROOT / "benchmarks" / "manifest.json"


def load_manifest(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or not isinstance(document.get("samples"), list):
        raise ValueError("benchmark manifest schema_version 必须为 1，且 samples 必须为列表。")
    root = path.parent.resolve()
    samples: list[dict[str, Any]] = []
    for raw in document["samples"]:
        required = {"id", "path", "sha256", "license", "source", "expected"}
        if not isinstance(raw, dict) or not required.issubset(raw):
            raise ValueError("每个 benchmark 样本都必须记录路径、hash、许可、来源和 expected。")
        asset = (root / str(raw["path"])).resolve()
        if root not in asset.parents or not asset.is_file():
            raise ValueError(f"benchmark 资产路径无效：{raw['path']}")
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        if digest != raw["sha256"]:
            raise ValueError(f"benchmark 资产 hash 不匹配：{raw['id']}")
        if not str(raw["license"]).strip() or not str(raw["source"]).strip():
            raise ValueError(f"benchmark 样本缺少许可或来源：{raw['id']}")
        samples.append({**raw, "asset": asset})
    return samples


def normalized_latex(value: str) -> str:
    value = re.sub(r"\s+", "", value.strip())
    return value.replace(r"\left", "").replace(r"\right", "")


def run_benchmark(
    samples: list[dict[str, Any]], backend: str, runs: int, manager: BackendManager | None = None
) -> dict[str, Any]:
    if runs < 1:
        raise ValueError("runs 必须至少为 1。")
    recognizer = manager or BackendManager()
    results: list[dict[str, Any]] = []
    all_timings: list[float] = []
    for sample in samples:
        predictions: list[str] = []
        timings: list[float] = []
        issues: tuple[str, ...] = ()
        for _ in range(runs):
            if backend == "fake":
                started = perf_counter()
                prediction = str(sample["expected"])
                elapsed = perf_counter() - started
            else:
                with Image.open(sample["asset"]) as image:
                    result = recognizer.recognize(image.convert("RGB"), backend)
                prediction = result.latex
                elapsed = result.elapsed_seconds
            predictions.append(prediction)
            timings.append(elapsed)
            issues = assess_latex(prediction).issues
        exact = normalized_latex(predictions[-1]) == normalized_latex(str(sample["expected"]))
        all_timings.extend(timings)
        results.append(
            {
                "id": sample["id"],
                "prediction": predictions[-1],
                "normalized_exact": exact,
                "issues": list(issues),
                "timings_seconds": timings,
            }
        )
    return {
        "backend": backend,
        "runs": runs,
        "samples": results,
        "summary": {
            "sample_count": len(results),
            "normalized_exact_count": sum(item["normalized_exact"] for item in results),
            "normalized_exact_rate": (
                mean(item["normalized_exact"] for item in results) if results else 0.0
            ),
            "mean_seconds": mean(all_timings) if all_timings else 0.0,
            "median_seconds": median(all_timings) if all_timings else 0.0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the FormulaSnip recognition benchmark.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--backend", choices=("auto", "rapid", "mathcraft", "fake"), default="auto"
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark(load_manifest(args.manifest), args.backend, args.runs)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
