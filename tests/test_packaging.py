from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_collects_mathcraft_runtime_without_legacy_engine() -> None:
    spec = (ROOT / "FormulaSnip.spec").read_text(encoding="utf-8")

    for required in (
        "mathcraft_ocr",
        "onnxruntime",
        "rapidocr",
        "transformers",
        "tokenizers",
        "huggingface_hub",
        "safetensors",
    ):
        assert f'"{required}"' in spec
    assert "paddle" not in spec.lower()
    assert 'normalized.endswith(".onnx")' in spec
    assert '"/mathcraft_ocr/"' in spec
    assert '"/rapidocr/models/"' in spec


def test_installer_rejects_accidentally_packaged_onnx_weights() -> None:
    installer = (ROOT / "scripts" / "build_installer.ps1").read_text(encoding="utf-8")

    assert 'Filter "*.onnx"' in installer
    assert "mathcraft_ocr|rapidocr|onnxruntime" in installer
