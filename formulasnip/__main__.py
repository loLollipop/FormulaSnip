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

    from formulasnip.app import main

    raise SystemExit(main())
