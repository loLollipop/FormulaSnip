# Third-party notices

FormulaSnip depends on third-party Python packages. Their licenses remain with
their respective authors and are not replaced by FormulaSnip's GPL-3.0-only
license. FormulaSnip's own source code is licensed under GPL-3.0-only;
third-party components retain their own licenses, copyright notices, and terms.
The Windows package keeps dependency metadata and bundled license files under
`_internal\*.dist-info`. `pyproject.toml` and `uv.lock` are included beside the
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

- PySide6 Essentials, PySide6 Addons, and Shiboken6 are distributed by Qt under a choice of
  LGPL-3.0-only, GPL-2.0-only, or GPL-3.0-only. FormulaSnip uses the
  GPL-3.0-only option. Source: https://code.qt.io/cgit/pyside/pyside-setup.git/
- MathJax 3.2.2 is Apache-2.0 licensed. FormulaSnip vendors the self-contained
  `tex-svg-full.js` component for fully offline formula preview; its license is
  included at `THIRD_PARTY_LICENSES/mathjax-3.2.2-LICENSE.txt`. Source:
  https://github.com/mathjax/MathJax
- latex2mathml 3.81.1 is MIT licensed. Its license text is included at
  `THIRD_PARTY_LICENSES/latex2mathml-LICENSE.txt` because the upstream wheel
  does not contain that file. Source: https://github.com/roniemartinez/latex2mathml
- `latex2mathml/unimathsymbols.txt` is copyright 2011 Günter Milde and is
  licensed under LPPL-1.3-or-later. Its original header remains intact and an
  additional notice is included at
  `THIRD_PARTY_LICENSES/unimathsymbols-NOTICE.txt`.
- Requests is Apache-2.0 licensed and is used for update checks and optional
  OpenAI-compatible formula-correction requests. Source: https://github.com/psf/requests

## Recognition backend

- MathCraft OCR 0.3.1 is GPL-3.0-only. The wheel includes the complete license
  text in its distribution metadata; it is the same license version included
  in FormulaSnip's root `LICENSE`. FormulaSnip uses only its ONNX CPU formula
  profile. Source: https://github.com/SakuraMathcraft/LaTeXSnipper
- The MathCraft formula-recognition model v1 is distributed under GPL-3.0-only
  by SakuraMathcraft. Windows packages include its eight pinned runtime files
  for offline first use. `MODEL_ASSETS.json` records the release URL, archive
  digest, file sizes, and per-file SHA-256 values. The applicable GPL-3.0-only
  license text is the root `LICENSE`. Source:
  https://github.com/SakuraMathcraft/MathCraft-Models
