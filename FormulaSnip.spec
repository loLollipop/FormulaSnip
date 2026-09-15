# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata


project_root = Path(SPECPATH)

datas = [
    (str(project_root / "formulasnip" / "assets"), "formulasnip/assets"),
    (
        str(project_root / "formulasnip" / "recognition" / "rapid_config.yaml"),
        "formulasnip/recognition",
    ),
    (str(project_root / "LICENSE"), "."),
    (str(project_root / "README.md"), "."),
    (str(project_root / "THIRD_PARTY_NOTICES.md"), "."),
    (str(project_root / "THIRD_PARTY_LICENSES"), "THIRD_PARTY_LICENSES"),
    (str(project_root / "pyproject.toml"), "."),
    (str(project_root / "uv.lock"), "."),
]
binaries = []
hiddenimports = ["PySide6.QtSvgWidgets"]

# Preserve the metadata and license files for the shipped dependency graph.
# Recursive collection also supports libraries (notably PaddleX) that query
# package versions at runtime.  The dictionary removes duplicates introduced
# by overlapping dependency trees.
metadata = {}
for distribution_name in (
    "formulasnip",
    "PySide6_Essentials",
    "shiboken6",
    "Pillow",
    "latex2mathml",
    "matplotlib",
    "rapid-latex-ocr",
    "requests",
    "paddleocr",
    "paddlepaddle",
    "paddlex",
    "tokenizers",
    "ftfy",
    "onnxruntime",
    "opencv-contrib-python",
    "opencv-python",
    "pypdfium2",
    "pandas",
):
    for source, destination in copy_metadata(distribution_name, recursive=True):
        metadata[destination] = source
datas.extend((source, destination) for destination, source in metadata.items())


# collect_all() imports every package while discovering hidden modules.  Paddle's
# optional compiler/TensorRT and PaddleX's training/serving trees are not part of
# FormulaSnip's CPU inference path; some of them also crash PyInstaller's isolated
# collector on Windows.  Keep discovery on the two production backends only.
_EXCLUDED_SUBMODULE_PREFIXES = {
    "paddle": (
        "paddle.dataset",
        "paddle.distributed",
        "paddle.hapi",
        "paddle.incubate",
        "paddle.jit",
        "paddle.optimizer",
        "paddle.profiler",
        "paddle.quantization",
        "paddle.tensorrt",
    ),
    "paddleocr": (
        "paddleocr._api_client",
        "paddleocr._cli",
        "paddleocr._doc2md",
        "paddleocr._pipelines",
    ),
    "paddlex": (
        "paddlex.inference.serving",
        "paddlex.modules",
        "paddlex.repo_apis",
        "paddlex.repo_manager",
    ),
}


def production_submodule(package_name: str):
    excluded_prefixes = _EXCLUDED_SUBMODULE_PREFIXES.get(package_name, ())

    def include(module_name: str) -> bool:
        return not any(
            module_name == prefix or module_name.startswith(f"{prefix}.")
            for prefix in excluded_prefixes
        )

    return include


def is_rapid_model_file(source: str) -> bool:
    normalized = source.replace("\\", "/").lower()
    return "/rapid_latex_ocr/models/" in normalized


for package_name in (
    "rapid_latex_ocr",
    "latex2mathml",
    "paddleocr",
    "paddlex",
    "paddle",
    "onnxruntime",
    "matplotlib",
):
    package_datas, package_binaries, package_hiddenimports = collect_all(
        package_name,
        include_py_files=False,
        filter_submodules=production_submodule(package_name),
    )
    if package_name == "rapid_latex_ocr":
        package_datas = [
            item for item in package_datas if not is_rapid_model_file(item[0])
        ]
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)


analysis = Analysis(
    [str(project_root / "formulasnip" / "__main__.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2"],
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
