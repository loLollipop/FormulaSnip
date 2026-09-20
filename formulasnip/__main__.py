from __future__ import annotations


def _run_preview_smoke_test() -> int:
    """Render one formula through the frozen WebEngine and offline MathJax."""

    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from formulasnip.ui.widgets import FormulaPreviewWidget

    app = QApplication.instance() or QApplication([])
    preview = FormulaPreviewWidget()
    if not preview.webengine_available:
        preview.close()
        return 2

    outcome: list[str] = []
    loop = QEventLoop()
    preview.rendered.connect(lambda _request, backend: (outcome.append(backend), loop.quit()))
    preview.failed.connect(lambda _request, _detail: (outcome.append("failed"), loop.quit()))
    QTimer.singleShot(15_000, loop.quit)
    preview.resize(480, 168)
    preview.show()
    preview.set_formula(
        r"f(x)=\begin{cases}x^2,&x\ge0\\-x,&x<0\end{cases}"
    )
    loop.exec()
    preview.close()
    app.processEvents()
    if outcome != ["mathjax"]:
        return 3
    return 0


def _run_model_smoke_test() -> int:
    """Load and exercise only the bundled formula model without network fallback."""

    import sys
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from mathcraft_ocr import MathCraftRuntime
    from PIL import Image, ImageDraw

    frozen_root = getattr(sys, "_MEIPASS", None)
    if not getattr(sys, "frozen", False) or not frozen_root:
        print("MathCraft model smoke test requires a frozen application.", flush=True)
        return 6
    bundled_models_dir = Path(frozen_root) / "MathCraft" / "models"
    expected_model_dir = bundled_models_dir / "mathcraft-formula-rec"
    print(f"MathCraft bundled model source: {expected_model_dir}", flush=True)

    with TemporaryDirectory(prefix="FormulaSnip-model-smoke-") as empty_cache:
        runtime = MathCraftRuntime(
            cache_dir=empty_cache,
            provider_preference="cpu",
            bundled_models_dir=bundled_models_dir,
            auto_download=False,
        )
        plan = runtime.warmup("formula")
        if not plan.ready:
            return 4
        selected = runtime.check_models(include_optional=False)[
            "mathcraft-formula-rec"
        ].model_dir
        if selected.resolve() != expected_model_dir.resolve():
            print(f"Unexpected MathCraft model source: {selected}", flush=True)
            return 6
        probe = Image.new("RGB", (48, 24), "white")
        ImageDraw.Draw(probe).text((8, 4), "x", fill="black")
        result = runtime.recognize_formula(probe)
        return 0 if str(result.text).strip() else 5


if __name__ == "__main__":
    import multiprocessing
    import sys

    from formulasnip.runtime import configure_runtime

    configure_runtime()
    # PyInstaller dispatches model subprocesses here before importing Qt or
    # creating any application windows.
    multiprocessing.freeze_support()

    if "--smoke-preview" in sys.argv[1:]:
        raise SystemExit(_run_preview_smoke_test())
    if "--smoke-model" in sys.argv[1:]:
        raise SystemExit(_run_model_smoke_test())

    from formulasnip.app import main

    raise SystemExit(main())
