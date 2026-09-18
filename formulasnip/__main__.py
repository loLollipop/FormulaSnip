from __future__ import annotations


def _run_preview_smoke_test() -> int:
    """Exercise the frozen SVG renderer without starting the desktop UI."""

    from formulasnip.core.preview import render_formula_svg

    formula = (
        r"\rho c _ { \mathrm { p } } \, "
        r"\frac { \partial T } { \partial t } = "
        r"\nabla \cdot ( k \nabla T ) + Q _ { \mathrm { v } }"
    )
    try:
        svg = render_formula_svg(formula)
    except Exception:
        return 2
    return 0 if b"<svg" in svg else 3


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
