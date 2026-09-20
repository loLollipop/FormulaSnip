from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_windows_build_checks_all_release_versions_before_pyinstaller() -> None:
    script = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")

    version_check = script.index("Version mismatch:")
    pyinstaller = script.index("uv run pyinstaller")
    assert version_check < pyinstaller
    assert "pyproject.toml=$appVersion" in script
    assert "formulasnip/__init__.py=$packageVersion" in script
    assert "installer/FormulaSnip.iss=$installerVersion" in script


def test_windows_build_smoke_checks_frozen_mathjax_preview() -> None:
    script = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")

    assert "uv run pyinstaller --noconfirm --clean FormulaSnip.spec" in script
    assert "matplotlib.backends.backend_svg" not in script
    assert '-ArgumentList "--smoke-preview"' in script
    assert ".WaitForExit(30000)" in script
    assert "prepare_bundled_model.py" in script
    assert '-ArgumentList "--smoke-model"' in script
    assert ".WaitForExit(120000)" in script


def test_standalone_installer_build_checks_all_release_versions_first() -> None:
    script = (ROOT / "scripts" / "build_installer.ps1").read_text(
        encoding="utf-8"
    )

    version_check = script.index("Version mismatch:")
    portable_check = script.index("Build the portable application first")
    assert version_check < portable_check
    assert "pyproject.toml=$appVersion" in script
    assert "formulasnip/__init__.py=$packageVersion" in script
    assert "installer/FormulaSnip.iss=$installerVersion" in script


def test_standalone_installer_uses_project_paths_for_model_verification() -> None:
    script = (ROOT / "scripts" / "build_installer.ps1").read_text(
        encoding="utf-8"
    )

    assert (
        '$prepareModelScript = Join-Path $projectRoot '
        '"scripts\\prepare_bundled_model.py"'
    ) in script
    assert "uv run --project $projectRoot python $prepareModelScript" in script
