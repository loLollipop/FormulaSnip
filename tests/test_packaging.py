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
    assert "rapid_latex_ocr" not in spec
    assert "rapid-latex-ocr" not in spec


def test_pyinstaller_collects_webengine_and_not_legacy_preview_renderer() -> None:
    spec = (ROOT / "FormulaSnip.spec").read_text(encoding="utf-8")

    assert '"PySide6.QtWebEngineCore"' in spec
    assert '"PySide6.QtWebEngineWidgets"' in spec
    assert '"PySide6_Addons"' in spec
    assert '"matplotlib.backends.backend_svg"' not in spec
    assert 'excludes=["tkinter", "matplotlib"' in spec


def test_wheel_includes_third_party_notices_and_licenses() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '[tool.hatch.build.targets.wheel.shared-data]' in project
    assert '"THIRD_PARTY_NOTICES.md" = "share/formulasnip/THIRD_PARTY_NOTICES.md"' in project
    assert '"THIRD_PARTY_LICENSES" = "share/formulasnip/THIRD_PARTY_LICENSES"' in project


def test_installer_rejects_accidentally_packaged_onnx_weights() -> None:
    installer = (ROOT / "scripts" / "build_installer.ps1").read_text(encoding="utf-8")

    assert 'Filter "*.onnx"' in installer
    assert "mathcraft_ocr|rapidocr|onnxruntime" in installer
    assert '_internal\\rapid_latex_ocr' in installer
    assert "retired RapidLaTeXOCR backend" in installer


def test_update_manifest_requires_nonempty_release_notes() -> None:
    installer = (ROOT / "scripts" / "build_installer.ps1").read_text(encoding="utf-8")
    notes = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8").strip()

    assert notes
    assert len(notes) <= 4_000
    assert 'Join-Path $projectRoot "RELEASE_NOTES.md"' in installer
    assert 'notes = $releaseNotes' in installer
    assert 'notes = ""' not in installer


def test_upgrade_removes_only_the_retired_rapidlatex_backend() -> None:
    installer = (ROOT / "installer" / "FormulaSnip.iss").read_text(encoding="utf-8")

    assert 'Name: "{app}\\_internal\\rapid_latex_ocr"' in installer
    assert 'Name: "{app}\\_internal\\rapid_latex_ocr-*.dist-info"' in installer
    assert 'Name: "{app}\\_internal\\formulasnip\\recognition\\rapid_config.yaml"' in installer
    assert 'Name: "{app}\\_internal\\rapidocr"' not in installer
