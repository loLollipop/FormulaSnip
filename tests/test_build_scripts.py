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


def test_windows_build_checks_svg_backend_in_clean_pyz_manifest() -> None:
    script = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")

    assert "uv run pyinstaller --noconfirm --clean FormulaSnip.spec" in script
    assert '"build\\FormulaSnip\\PYZ-00.toc"' in script
    assert '.Contains("matplotlib.backends.backend_svg")' in script
    assert '-ArgumentList "--smoke-preview"' in script
    assert ".WaitForExit(30000)" in script


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
