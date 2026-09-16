from __future__ import annotations

if __name__ == "__main__":
    import multiprocessing

    from formulasnip.runtime import configure_runtime

    configure_runtime()
    # PyInstaller dispatches model subprocesses here before importing Qt or
    # creating any application windows.
    multiprocessing.freeze_support()

    from formulasnip.app import main

    raise SystemExit(main())
