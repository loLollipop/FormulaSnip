# Third-party notices

FormulaSnip depends on third-party Python packages. Their licenses remain with
their respective authors and are not replaced by FormulaSnip's GPL-3.0-only
license. FormulaSnip's own source code is licensed under GPL-3.0-only;
third-party components retain their own licenses, copyright notices, and terms.
The Windows package keeps dependency metadata and bundled license files under
`_internal\\*.dist-info`. `pyproject.toml` and `uv.lock` are included beside the
application so the exact declared and resolved dependency sets can be audited.
Additional license texts that are absent from upstream wheels are preserved in
`THIRD_PARTY_LICENSES`.

## Windows installer

- The Setup package is built with Inno Setup. Its license is included at
  `THIRD_PARTY_LICENSES/inno-setup-LICENSE.txt`. Source: https://jrsoftware.org/isinfo.php
- The Simplified Chinese installer messages are maintained by Zhenghan Yang
  (Kira) and distributed under the MIT License. The license is included at
  `THIRD_PARTY_LICENSES/inno-chinese-translation-LICENSE.txt`. Source:
  https://github.com/kira-96/Inno-Setup-Chinese-Simplified-Translation

## User interface and conversion libraries

- PySide6 Essentials and Shiboken6 are distributed by Qt under a choice of
  LGPL-3.0-only, GPL-2.0-only, or GPL-3.0-only. FormulaSnip uses the
  GPL-3.0-only option. Source: https://code.qt.io/cgit/pyside/pyside-setup.git/
- latex2mathml 3.81.1 is MIT licensed. Its license text is included at
  `THIRD_PARTY_LICENSES/latex2mathml-LICENSE.txt` because the upstream wheel
  does not contain that file. Source: https://github.com/roniemartinez/latex2mathml
- `latex2mathml/unimathsymbols.txt` is copyright 2011 Günter Milde and is
  licensed under LPPL-1.3-or-later. Its original header remains intact and an
  additional notice is included at
  `THIRD_PARTY_LICENSES/unimathsymbols-NOTICE.txt`.

## Recognition backends

- RapidLaTeXOCR: repository code is published under MIT. The PyPI metadata for
  version 0.0.9 reports Apache-2.0. Its automatically downloaded model files do
  not currently include a separately verified redistribution license in this
  project. FormulaSnip does not claim redistribution rights for those weights.
  Source: https://github.com/RapidAI/RapidLaTeXOCR
- PaddleOCR / PP-FormulaNet-S: PaddleOCR code and the official Hugging Face
  model card report Apache-2.0. Its dependencies are installed by default and
  its model is downloaded by Paddle's own runtime on first use.
  Sources: https://github.com/PaddlePaddle/PaddleOCR and
  https://huggingface.co/PaddlePaddle/PP-FormulaNet-S
The Windows release intentionally excludes separately cached Paddle model files
and removes Rapid model weights from the packaged Python distribution. Each
upstream component downloads its model on first use. Before redistributing a
release that embeds model files, generate a complete dependency and model SBOM,
include every required license text, and obtain clarification for model files
whose redistribution terms are not explicit.
