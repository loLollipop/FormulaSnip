# Notes: FormulaSnip

## Environment
- OS: Windows
- Python: 3.12.3
- uv: 0.10.9
- Installed in the final combined test environment: PySide6-Essentials, RapidLaTeXOCR,
  ONNX Runtime, PaddleOCR, PaddlePaddle, Pillow, pytest and Ruff.

## Product Scope
- Input: pasted image, image file, drag-and-drop or user-selected screen region.
- Recognition: one cropped mathematical formula only.
- Output: editable LaTeX, rendered preview, clipboard export, Word insertion.
- Out of scope: paragraph OCR, page layout, tables, full-document parsing.

## Architecture Notes
- `formulasnip/ui/`: desktop window and widgets.
- `formulasnip/recognition/`: backend protocol, backend discovery, local adapters.
- `formulasnip/integrations/`: clipboard and Word integration.
- `formulasnip/core/`: application state and validation helpers.
- Keep model imports lazy so the app starts even before optional model packages are installed.

## Backend Decision
- Default: `rapid-latex-ocr==0.0.9`.
  - Python metadata supports 3.12 (`>=3.6,<3.13`).
  - Uses ONNX Runtime CPU provider.
  - API: `from rapid_latex_ocr import LaTeXOCR`; call returns `(latex, elapsed_seconds)`.
  - Model files download on first backend initialization; UI must keep this work off the main thread and explain the first-run delay.
  - Upstream metadata omits the imported `requests` package; FormulaSnip declares it explicitly in the `rapid` extra.
- UniMERNet remains a later accuracy backend because model/config management is heavier.

## Size Decision
- The first synced environment with the `PySide6` meta-package occupied about 1,152 MiB.
- `PySide6` pulled the unused Addons bundle; FormulaSnip only needs QtCore, QtGui and QtWidgets.
- Base dependency changed to `PySide6-Essentials` to reduce the eventual installer substantially.
- Downloaded RapidLaTeXOCR model files occupy about 171 MiB.

## Real Inference Results
- Official/reference-style hyperbola formula recognized exactly on CPU in about 2.7–2.8 seconds after warm model download:
  - Expected/output: `{\\frac{x^{2}}{a^{2}}}-{\\frac{y^{2}}{b^{2}}}=1`
- A Matplotlib-rendered integral using a different glyph style was not exact (`e` and `dx` were confused), so v1 deliberately keeps the LaTeX editor and visual confirmation step.
- Final re-run on the hyperbola example completed in 2.60 seconds with the exact expected LaTeX.

## Final Review and Verification
- Independent review found and regression-tested Word rollback, LaTeX control-word boundaries, image preflight, screenshot close lifecycle, and MathML clipboard MIME handling.
- Microsoft documentation was rechecked: `OMaths.Add(range)` returns a `Range`; the supported call chain remains `returned_range.OMaths(1).BuildUp()`.
- `uv run python -m pytest`: 18 passed.
- `uv run ruff check .`: all checks passed.
- `uv run python scripts\\render_preview.py`: Windows UI preview regenerated successfully.
- Final `.venv` footprint including the downloaded Rapid model: about 720.8 MiB.

## V2 Final Verification

- `uv sync --extra rapid --extra paddle --extra dev` completed successfully in one shared
  environment.
- Combined `.venv`: 1,278.8 MiB; external PP-FormulaNet-S model cache: 227.4 MiB;
  installed total: about 1,506.2 MiB / 1.47 GiB. This is about 785.4 MiB more than the
  Rapid-only environment.
- Real `auto` run on `examples/hyperbola_formula.png`: selected Rapid and stayed on the
  fast path (`auto-rapid`), about 2.94 seconds for that cold process.
- Real `auto` run on `examples/sample_formula.png`: triggered Paddle review, selected the
  semantically better Paddle candidate and retained both predictions (`auto-reviewed`),
  about 15.23 seconds including first Paddle initialization.
- `uv run python -m pytest`: 35 passed.
- `uv run ruff check .`: all checks passed.
- `uv build`: source distribution and wheel built successfully.
- Wheel inspection confirmed both `dist-info/licenses/LICENSE` and
  `formulasnip/recognition/rapid_config.yaml`; the source distribution contains both too.
- `uv run python scripts\\render_preview.py`: V2 preview now shows only the adopted result
  as a scalable SVG electronic formula, keeps alternative candidates in the selector, and
  opens MathML source in a separate viewer. Both screenshots were visually inspected.

## Floating Workflow

- The default entry point now creates a persistent `FloatingFormulaAssistant` instead of
  opening the full editor immediately.
- The always-on-top orb supports click-to-capture, drag thresholds, screen-bound clamping,
  edge snapping, busy/result states, and a right-click editor/quit menu.
- A successful crop always starts `auto` recognition in the existing worker and shared
  backend manager. The compact panel appears only after recognition and shows one adopted
  SVG electronic formula with LaTeX/MathML copy actions.
- The compact panel also offers recapture and full-editor actions. Opening the full editor
  reuses the current image, result, and warmed model manager.
- Duplicate capture requests are gated; a successful new crop invalidates the old result,
  while cancelling the overlay preserves it.
- `uv run python -m pytest`: 39 passed after the floating workflow changes.
- `uv run ruff check .`: all checks passed.
- `uv run python scripts\\render_floating_preview.py`: the real Qt orb and result panel
  were rendered into `artifacts/formulasnip_floating.png` and visually inspected on a
  light background for contrast.

## V3 Interaction Decision

- Startup uses one settings window with recognition mode, orb color, result-panel theme,
  tutorial access, and a primary action that enters floating mode.
- The tutorial is four short pages: click the orb, drag to select a formula, verify the
  electronic preview, then copy LaTeX or MathML and paste into Word/MathType.
- The daily workflow exposes only the floating orb and adopted-result panel. The full
  editor, alternative selector, image import, and direct Word insertion are not migrated.
- Successful explicit copy hides the result panel; conversion or clipboard failure keeps
  it visible. The screenshot overlay is lighter and uses a high-contrast custom crosshair.
- pix2tex is removed from the shipped backend list and dependency extras. Rapid remains the
  fast/default backend and PP-FormulaNet-S remains the optional accuracy reviewer.

## V2 Optimization Findings

### RapidLaTeXOCR preprocessing
- Upstream already performs foreground bounding-box crop, polarity normalization, min/max sizing to 32–672 by 32–192, learned width selection, padding to multiples of 32, grayscale conversion and mean/std normalization.
- Therefore global external grayscale, threshold, upscale or sharpen is not a safe default; it duplicates the model's evaluation pipeline and can shift input away from its training distribution.
- A local six-variant probe confirmed the risk: the clean hyperbola stayed correct under all variants, but the difficult integral stayed wrong under original/autocontrast/threshold/upscale/sharpen.
- Downscaling the difficult integral produced a degenerate 512-token output and about 59.6 seconds latency. This exposes a worst-case decoder path when EOS is not generated; V2 needs a token/latency guard rather than unconditional multi-pass preprocessing.
- The default path should preserve original pixels and only run lightweight diagnostics. Targeted preprocessing should be opt-in or only attempted when a diagnosed defect is present, with the baseline result retained if outputs disagree.

### Candidate routing direction
- Fast default: RapidLaTeXOCR, one original-image pass, cached model, direct NumPy input to remove an unnecessary PNG encode/decode.
- Accurate optional candidate: prioritize PP-FormulaNet-S for empirical testing. Official published model size is about 224 MB and its architecture is positioned for fast inference; actual Windows runtime/dependency footprint must still be measured.
- Larger PP-FormulaNet variants and UniMERNet should not be default CPU paths because model/runtime sizes and latency threaten the 0.8 GB product target.
- Adaptive mode should use deterministic risk signals (edge clipping, low contrast, extreme aspect ratio, syntax/render failure, excessively long output, result disagreement) to recommend or invoke an accurate backend; these are risk indicators, not calibrated confidence.

### Repository and issue history snapshot (2026-09-15)
- RapidLaTeXOCR: 386 stars / 39 forks, 2 open issues, latest release and main commit 2024-11-03. Small and deployable, but its maintenance signal and issue sample are limited.
- LaTeX-OCR/pix2tex: 16,566 stars / 1,313 forks, 142 open issues and 17 PRs; latest release 2023-04-13, latest main commit 2025-01-18. It has the largest formula-specific community, but open Windows GUI dependency issue #442 and symbol accuracy issue #286 show that popularity is not a deployment or accuracy guarantee.
- UniMERNet: 500 stars / 46 forks, 36 open issues; latest release 2024-12-26, latest main commit 2025-09-28. Issue #83 records an unresolved GPU reproduction problem; official weights/runtime remain too large for the default package.
- PaddleOCR: 89,574 stars / 11,336 forks, active v3.7.0 release on 2026-06-11 and main activity in 2026-07. It has the strongest maintenance signal, but is a large general OCR suite. CPU memory regression #15866 was eventually closed after a long lifecycle, so runtime isolation and version pinning remain important.
- Surya: 21,388 stars / 1,542 forks and active 2026 releases, but current architecture is a unified document VLM/server rather than a lightweight single-formula recognizer; its model license has commercial thresholds and output-quality issue #507 remains open.

### Model size and license comparison
- Rapid weights: 169.78 MiB locally; ONNXRuntime CPU; code license metadata conflicts between repository MIT and PyPI Apache-2.0, and weights have no separate license statement.
- pix2tex weights: about 115.93 MiB, but PyTorch/transformers/timm runtime is heavy and the checkpoint license is not separately stated.
- UniMERNet tiny/small/base weights: about 410 MiB / 773 MiB / 1.21 GiB before PyTorch; code and model cards are Apache-2.0.
- PP-FormulaNet-S: about 224 MB model, Apache-2.0 code and weight card; plus-S is about 248 MB and has better official Chinese BLEU. PP-FormulaNet-L is about 695 MB before runtime and cannot fit the default package.
- Surya/Texify is unsuitable for the default: PyTorch/VLM runtime plus restrictive model licensing; Texify model output is Markdown+LaTeX rather than the required pure single-formula path.

### Local PP-FormulaNet-S probe
- A clean isolated Python 3.12 CPU environment required `paddleocr`, `paddlepaddle`, plus two dependencies not pulled into the tested minimal path (`tokenizers` and `ftfy`).
- Unpacked isolated runtime packages measured about 730.1 MiB; the downloaded PP-FormulaNet-S files measured about 227.4 MiB. Combining this with the Qt desktop stack would exceed the 0.8 GB default target, so Paddle must remain an optional accuracy pack.
- Model initialization took about 9.6 seconds. Warm predictions were about 0.76 seconds on both examples.
- Hyperbola prediction was malformed (`frac` missing a backslash and `--`), while Rapid was exact.
- Difficult integral prediction was semantically correct (`e^{-x^2}\,d x`), while Rapid confused `e` and `dx`.
- These two counterexamples justify a hybrid strategy: Rapid fast baseline, Paddle optional complex-formula candidate, deterministic output linting, and retaining the baseline when Paddle produces malformed LaTeX.

## Word Decision
- First version connects only to an already-running Word instance.
- Validate active document, read-only state, and protection state before writing.
- Insert a duplicate of the current selection range, call `OMaths.Add`, then `BuildUp`.
- Do not promise arbitrary LaTeX compatibility; Word supports its own UnicodeMath/LaTeX subsets and syntax differences.

## Sources
- RapidLaTeXOCR: https://github.com/RapidAI/RapidLaTeXOCR
- pix2tex: https://github.com/lukas-blecher/LaTeX-OCR
- UniMERNet: https://github.com/opendatalab/UniMERNet
- Microsoft Word OMaths.Add: https://learn.microsoft.com/en-us/office/vba/api/word.omaths.add
- MathType equation exchange: https://docs.wiris.com/en_US/using-mathtype/copying-and-exchanging-equations
