# Third-party notices

FormulaSnip depends on third-party Python packages. Their licenses remain with
their respective authors and are not replaced by FormulaSnip's MIT license.

## Recognition backends

- RapidLaTeXOCR: repository code is published under MIT. The PyPI metadata for
  version 0.0.9 reports Apache-2.0. Its automatically downloaded model files do
  not currently include a separately verified redistribution license in this
  project. FormulaSnip does not claim redistribution rights for those weights.
  Source: https://github.com/RapidAI/RapidLaTeXOCR
- PaddleOCR / PP-FormulaNet-S: PaddleOCR code and the official Hugging Face
  model card report Apache-2.0. The Paddle accuracy pack is optional and its
  model is downloaded by Paddle's own runtime.
  Sources: https://github.com/PaddlePaddle/PaddleOCR and
  https://huggingface.co/PaddlePaddle/PP-FormulaNet-S
Before distributing an installer, generate a complete dependency and model
SBOM, include every required license text, and obtain clarification for model
files whose redistribution terms are not explicit.
