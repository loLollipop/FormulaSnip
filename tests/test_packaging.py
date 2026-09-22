import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_exact_version_license_manifest_and_critical_texts() -> None:
    directory = ROOT / "THIRD_PARTY_LICENSES"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    indexed = {item["component"]: item for item in manifest["components"]}
    for component, version in (("antlr4-python3-runtime", "4.9.3"),
                               ("rapidocr", "3.5.0"), ("tokenizers", "0.21.4")):
        item = indexed[component]
        assert item["version"] == version
        assert item["source_url"].startswith("https://")
        assert item["license"] and item["review_status"]
        text = (directory / item["file"]).read_bytes()
        assert hashlib.sha256(text).hexdigest() == item["text_sha256"]
        assert len(text) > 1000
    assert indexed["flatbuffers"]["review_status"] == "Needs Manual License Review"


@pytest.mark.parametrize("name", ["direct_url.json", "assets/__pycache__/a.pyc",
                                  ".env", ".git/config", "qtwebengine.debug.pak",
                                  "plugins/qmltooling/qmldbg_debugger.dll"])
def test_release_bundle_scanner_rejects_forbidden_resources(tmp_path: Path, name: str) -> None:
    from scripts.verify_release_bundle import verify_bundle

    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fixture")
    assert verify_bundle(tmp_path, ROOT)


def test_release_bundle_scanner_rejects_local_paths_and_empty_bundle(tmp_path: Path) -> None:
    from scripts.verify_release_bundle import verify_bundle

    assert verify_bundle(tmp_path, ROOT)
    sample = tmp_path / "metadata.txt"
    sample.write_text(str(ROOT), encoding="utf-8")
    assert verify_bundle(tmp_path, ROOT)
    sample.write_text("normal resource", encoding="utf-8")
    assert verify_bundle(tmp_path, ROOT) == []
    sample.write_bytes(str(ROOT).encode("utf-16-le"))
    assert verify_bundle(tmp_path, ROOT)


def test_release_zip_scanner_rejects_metadata(tmp_path: Path) -> None:
    import zipfile

    from scripts.verify_release_bundle import verify_bundle

    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("FormulaSnip/x.dist-info/direct_url.json", "{}")
    assert verify_bundle(archive, ROOT)


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
    assert '"/safetensors-0.8.0.dist-info/sboms/"' in spec
    assert "rapid-latex-ocr" not in spec
    assert '"MathCraft/models/mathcraft-formula-rec"' in spec
    assert 'project_root / "MODEL_ASSETS.json"' in spec
    assert 'copy_metadata("formulasnip", recursive=False)' in spec
    assert 'Path(project_metadata_source) / "METADATA"' in spec


def test_pyinstaller_excludes_transitively_collected_qml_plugins() -> None:
    spec = (ROOT / "FormulaSnip.spec").read_text(encoding="utf-8")

    assert 'normalized.startswith("pyside6/qml/")' in spec
    assert "not is_unused_qt_qml_file(item[0])" in spec
    assert "The UI uses Qt Widgets and QtWebEngine HTML rather than QML" in spec
    assert "analysis.datas = type(analysis.datas)" in spec
    assert "analysis.binaries = type(analysis.binaries)" in spec


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


def test_installer_requires_verified_bundled_formula_model() -> None:
    installer = (ROOT / "scripts" / "build_installer.ps1").read_text(encoding="utf-8")

    assert "prepare_bundled_model.py" in installer
    assert '"_internal\\MathCraft\\models\\mathcraft-formula-rec"' in installer
    assert "--verify-only" in installer
    assert '_internal\\rapid_latex_ocr' in installer
    assert "retired RapidLaTeXOCR backend" in installer


def test_model_asset_lock_pins_archive_files_and_license() -> None:
    lock = (ROOT / "MODEL_ASSETS.json").read_text(encoding="utf-8")

    assert '"model_id": "mathcraft-formula-rec"' in lock
    assert '"archive_sha256": "807dd2d1' in lock
    assert '"license": "GPL-3.0-only"' in lock
    assert lock.count('"path":') == 8


def test_update_manifest_requires_nonempty_release_notes() -> None:
    installer = (ROOT / "scripts" / "build_installer.ps1").read_text(encoding="utf-8")
    notes = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8").strip()

    assert notes
    assert len(notes) <= 4_000
    assert 'Join-Path $projectRoot "RELEASE_NOTES.md"' in installer
    assert 'notes = $releaseNotes' in installer
    assert 'notes = ""' not in installer


def test_full_and_lightweight_installers_handle_models_safely() -> None:
    installer = (ROOT / "installer" / "FormulaSnip.iss").read_text(encoding="utf-8")
    builder = (ROOT / "scripts" / "build_installer.ps1").read_text(encoding="utf-8")

    assert "#ifdef UpdatePackage" in installer
    assert 'OutputBaseFilename=FormulaSnip-v{#AppVersion}-windows-x64-update' in installer
    assert "_internal\\MathCraft\\models\\*" in installer
    assert "GetSHA256OfFile" in installer
    assert "ModelBundleEntries" in installer
    assert "FileSize64(ModelFilePath, ActualSize)" in installer
    assert "GetSHA256OfFile(ModelFilePath)" in installer
    assert "{param:DIR|}" in installer
    assert "RegisteredInstallPath" in installer
    assert "[InstallDelete]" in installer
    assert '#ifndef UpdatePackage\n; A full Setup owns the bundled model' in installer
    assert (
        'Name: "{app}\\_internal\\MathCraft\\models\\mathcraft-formula-rec"'
        in installer
    )
    assert "$packagedModelLockHash -ne $modelLockHash" in builder
    assert "/DModelBundleEntries=$modelBundleManifest" in builder
    assert "FormulaSnip-update.json" in builder
    assert "FormulaSnip-update-v2.json" in builder
    assert "schema_version = 1" in builder
    assert 'schema_version = 2' in builder
    assert 'model_bundle_sha256 = $modelLockHash' in builder
    assert 'update_asset = [ordered]@{' in builder


def test_upgrade_removes_only_the_retired_rapidlatex_backend() -> None:
    installer = (ROOT / "installer" / "FormulaSnip.iss").read_text(encoding="utf-8")

    assert 'Name: "{app}\\_internal\\rapid_latex_ocr"' in installer
    assert 'Name: "{app}\\_internal\\rapid_latex_ocr-*.dist-info"' in installer
    assert 'Name: "{app}\\_internal\\formulasnip\\recognition\\rapid_config.yaml"' in installer
    assert 'Name: "{app}\\_internal\\rapidocr"' not in installer
