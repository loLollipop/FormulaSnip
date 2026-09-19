# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    copy_metadata,
)


project_root = Path(SPECPATH)

datas = [
    (str(project_root / "formulasnip" / "assets"), "formulasnip/assets"),
    (str(project_root / "LICENSE"), "."),
    (str(project_root / "README.md"), "."),
    (str(project_root / "THIRD_PARTY_NOTICES.md"), "."),
    (str(project_root / "THIRD_PARTY_LICENSES"), "THIRD_PARTY_LICENSES"),
    (str(project_root / "pyproject.toml"), "."),
    (str(project_root / "uv.lock"), "."),
]
binaries = []
hiddenimports = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    # MathCraft loads these formula-profile classes through Transformers'
    # lazy module registry, which static analysis cannot see.
    "transformers.models.auto.tokenization_auto",
    "transformers.models.trocr.processing_trocr",
    "transformers.models.vit.image_processing_vit",
    "transformers.models.xlm_roberta.tokenization_xlm_roberta_fast",
    "transformers.tokenization_utils_fast",
]

# Preserve the metadata and license files for the shipped dependency graph.
# Recursive collection supports libraries that query package versions at
# runtime. The dictionary removes duplicates from overlapping dependency trees.
metadata = {}
for distribution_name in (
    "formulasnip",
    "PySide6_Addons",
    "PySide6_Essentials",
    "shiboken6",
    "Pillow",
    "latex2mathml",
    "requests",
    "mathcraft-ocr",
    "rapidocr",
    "transformers",
    "tokenizers",
    "huggingface-hub",
    "safetensors",
    "omegaconf",
    "PyYAML",
    "numpy",
    "onnxruntime",
    "opencv-python",
):
    for source, destination in copy_metadata(distribution_name, recursive=True):
        metadata[destination] = source
datas.extend((source, destination) for destination, source in metadata.items())


def is_downloadable_model_file(source: str) -> bool:
    """Keep runtime-downloaded OCR weights out of redistributed builds."""

    normalized = source.replace("\\", "/").lower()
    return normalized.endswith(".onnx") and any(
        path in normalized
        for path in (
            "/mathcraft_ocr/",
            "/rapidocr/models/",
            "/onnxruntime/datasets/",
        )
    )


for package_name in ("latex2mathml", "mathcraft_ocr"):
    package_datas, package_binaries, package_hiddenimports = collect_all(
        package_name,
        include_py_files=False,
    )
    package_datas = [
        item for item in package_datas if not is_downloadable_model_file(item[0])
    ]
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)

# Runtime dependencies already have PyInstaller hooks or are reached through
# MathCraft's static imports. Collect their non-Python resources and native
# libraries without pulling optional training, CLI, test, Torch, or GPU trees.
for package_name in (
    "rapidocr",
    "transformers",
    "tokenizers",
    "huggingface_hub",
    "safetensors",
    "omegaconf",
    "yaml",
    "cv2",
    "onnxruntime",
):
    package_datas = collect_data_files(package_name, include_py_files=False)
    package_datas = [
        item for item in package_datas if not is_downloadable_model_file(item[0])
    ]
    datas.extend(package_datas)
    binaries.extend(collect_dynamic_libs(package_name))


analysis = Analysis(
    [str(project_root / "formulasnip" / "__main__.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
    optimize=1,
)

# A tool-provided PATH can make PyInstaller pick up a third-party ICU build
# instead of Windows' system ICU shim.  That copy then requires a versioned
# data DLL and prevents QtCore from loading on another machine.  Qt on our
# supported Windows 10/11 targets uses the system shim, so omit accidental ICU
# binaries from the portable package.
_external_icu_names = {"icuuc.dll", "icudt78.dll"}
analysis.binaries = type(analysis.binaries)(
    item
    for item in analysis.binaries
    if Path(item[0]).name.lower() not in _external_icu_names
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="FormulaSnip",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "formulasnip" / "assets" / "formulasnip.ico"),
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FormulaSnip",
)
