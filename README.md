<p align="center">
  <img src="https://raw.githubusercontent.com/loLollipop/FormulaSnip/main/formulasnip/assets/formulasnip.png" width="108" height="108" alt="FormulaSnip logo">
</p>

<h1 align="center">FormulaSnip</h1>

<p align="center"><strong>Turn formula screenshots into editable LaTeX and MathML.</strong></p>

<p align="center">
  <a href="https://github.com/loLollipop/FormulaSnip/releases/latest"><img src="https://img.shields.io/github/v/release/loLollipop/FormulaSnip?style=flat-square&amp;label=Release" alt="Latest release"></a>
  <a href="https://github.com/loLollipop/FormulaSnip/stargazers"><img src="https://img.shields.io/github/stars/loLollipop/FormulaSnip?style=flat-square&amp;label=Stars&amp;color=FFD700" alt="GitHub stars"></a>
  <a href="https://github.com/loLollipop/FormulaSnip/releases"><img src="https://img.shields.io/github/downloads/loLollipop/FormulaSnip/total?style=flat-square&amp;label=Downloads" alt="GitHub downloads"></a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D4?style=flat-square&amp;logo=windows11&amp;logoColor=white" alt="Windows 10 and 11">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/loLollipop/FormulaSnip?style=flat-square&amp;label=License" alt="GPL-3.0 license"></a>
</p>

<p align="center">
  <a href="https://github.com/loLollipop/FormulaSnip/releases/latest"><strong>Download</strong></a>
  · <a href="#download-and-get-started">Quick Start</a>
  · <a href="https://github.com/loLollipop/FormulaSnip/blob/main/README.zh-CN.md">简体中文</a>
  · <a href="https://github.com/loLollipop/FormulaSnip/issues">Report an Issue</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/loLollipop/FormulaSnip/main/artifacts/formulasnip_settings_center_dark.png" width="860" alt="FormulaSnip settings center">
</p>

FormulaSnip is a focused Windows formula-recognition tool for papers, notes, and technical documents. Click the floating orb, select one formula on screen, review the rendered preview, and copy the result into Word, MathType, LaTeX editors, or other math-aware applications.

FormulaSnip recognizes **individual mathematical formulas**. It is not a full-page document, table, or general-purpose text OCR application.

English · [简体中文](https://github.com/loLollipop/FormulaSnip/blob/main/README.zh-CN.md)

---

## What You Can Do

| Feature | What it offers |
| --- | --- |
| 📸 **Capture formulas** | Click the floating orb and drag over any formula visible on screen |
| 🧠 **Recognize locally** | Run the bundled MathCraft OCR CPU model without uploading screenshots by default |
| ✏️ **Review and edit** | Compare an offline rendered preview with the source and edit LaTeX before copying |
| 📋 **Copy for writing** | Copy LaTeX or MathML for Word, MathType, Markdown, and LaTeX workflows |
| ✨ **Enhance with AI** | Optionally run an OpenAI-compatible vision model alongside local recognition |
| 🎨 **Personalize** | Choose light or dark mode, four interface accents, orb-ring colors, and a custom orb logo |
| 🔄 **Stay current** | Check for releases in the app; installed builds can apply verified updates with visible progress |

---

## Download and Get Started

1. **Install FormulaSnip.** Download the Setup package from [Releases](https://github.com/loLollipop/FormulaSnip/releases/latest), run it, and create shortcuts when prompted.
2. **Start recognition.** Open FormulaSnip and select **Start Recognition** to leave the floating orb on screen.
3. **Capture and copy.** Left-click the orb, drag over one formula, review the result, then copy LaTeX or MathML.

> [!IMPORTANT]
> The official Windows Setup and portable ZIP include the Python runtime, application dependencies, and the pinned MathCraft formula model. No separate Python installation or first-use model download is required.

| Package | Use case |
| --- | --- |
| `FormulaSnip-v*-windows-x64-setup.exe` | **Recommended.** Installer, shortcuts, uninstaller, and in-app automatic updates |
| `FormulaSnip-v*-windows-x64.zip` | Portable use; extract the entire archive before running `FormulaSnip.exe` |

**System requirement:** Windows 10 or Windows 11, x64.

> [!NOTE]
> Current releases are not Authenticode-signed. Windows SmartScreen may show a warning. Download FormulaSnip only from this repository's official Releases page.

---

## Workflow

### 1. Capture a formula

Left-click the floating orb and drag around a single formula. Press `Esc` or right-click to cancel the capture.

<p align="center">
  <img src="https://raw.githubusercontent.com/loLollipop/FormulaSnip/main/artifacts/formulasnip_snip_overlay.png" width="760" alt="FormulaSnip screenshot selection">
</p>

### 2. Review the rendered formula

FormulaSnip renders an offline MathJax preview instead of showing a magnified screenshot. You can edit the recognized LaTeX and immediately check the updated typesetting.

<p align="center">
  <img src="https://raw.githubusercontent.com/loLollipop/FormulaSnip/main/artifacts/formulasnip_floating_result_dark.png" width="620" alt="FormulaSnip rendered formula preview and copy actions">
</p>

### 3. Copy into your editor

| Destination | Recommended output |
| --- | --- |
| Microsoft Word or MathType | **MathML** — paste into a formula-editing area |
| LaTeX editor or Markdown | **LaTeX** — paste into the appropriate math environment |

After a successful copy, the result panel closes automatically so you can return directly to your document.

> [!TIP]
> Formula OCR is not infallible. Always compare complex fractions, matrices, integrals, partial derivatives, and tightly spaced subscripts with the source before pasting.

---

## Optional AI Assistance

AI assistance is disabled by default. Open **Settings → Recognition**, enable **AI Assistance**, enter an OpenAI-compatible API URL and API key, retrieve and select a model, test the connection, and save the configuration.

- FormulaSnip retrieves the provider's available models and lets you test the connection.
- Local MathCraft OCR and the remote vision model run independently in parallel.
- If their results genuinely differ, the result panel lets you switch between them.
- If the AI request fails, the local result remains available.
- The API key is stored in Windows Credential Manager, not in the ordinary settings store.

The configured provider receives the selected formula image and may charge for or retain requests according to its own policy. See [Privacy](PRIVACY.md) before enabling this feature.

---

## Interface and Appearance

<p align="center">
  <img src="https://raw.githubusercontent.com/loLollipop/FormulaSnip/main/artifacts/formulasnip_appearance_live_preview.png" width="49%" alt="FormulaSnip appearance settings">
  <img src="https://raw.githubusercontent.com/loLollipop/FormulaSnip/main/artifacts/formulasnip_recognition_engine.png" width="49%" alt="FormulaSnip local and optional AI recognition settings">
</p>

- The settings center, result panel, and update dialog share the selected interface accent.
- Light and dark modes are independent of the accent color.
- The floating-orb ring and center logo can be customized separately.
- The system tray provides quick access to capture, settings, updates, and exit.

---

## Build from Source

Source development requires Python `>=3.10,<3.13` and [uv](https://docs.astral.sh/uv/):

```powershell
git clone https://github.com/loLollipop/FormulaSnip.git
cd FormulaSnip
uv sync --extra dev
uv run python -m formulasnip
```

Run the test and lint suites:

```powershell
uv run pytest -q
uv run ruff check .
```

Build the Windows portable package and Setup installer with [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```powershell
.\scripts\build_windows.ps1
```

The release build downloads and verifies the pinned MathCraft model when the build cache does not already contain a valid copy.

---

## Privacy and Security

- Local OCR and formula preview run on the user's computer.
- Formula images are not written to temporary files by the normal recognition path.
- Recognition stays local unless AI assistance is enabled. Automatic update checks are enabled by default and contact GitHub; they can be disabled in Settings. Optional AI assistance contacts only the configured provider.
- Update packages are checked by size and SHA-256 before installation.

Read [Privacy](PRIVACY.md), [Security](SECURITY.md), and [Third-party Notices](THIRD_PARTY_NOTICES.md) for the complete behavior and current release limitations.

---

## Contributing

Bug reports and pull requests are welcome. For recognition issues, please attach the original formula image and the expected LaTeX while removing any private information.

- [Open an issue](https://github.com/loLollipop/FormulaSnip/issues)
- [View releases](https://github.com/loLollipop/FormulaSnip/releases)
- [Report a vulnerability privately](https://github.com/loLollipop/FormulaSnip/security/advisories/new)

---

## Acknowledgements

- [MathCraft OCR](https://github.com/SakuraMathcraft/LaTeXSnipper) and [MathCraft Models](https://github.com/SakuraMathcraft/MathCraft-Models) provide the local formula-recognition foundation.
- [PySide6](https://doc.qt.io/qtforpython-6/) powers the Windows desktop interface.
- [MathJax](https://www.mathjax.org/) provides the offline electronic formula preview.
- [latex2mathml](https://github.com/roniemartinez/latex2mathml) provides MathML conversion.

---

## License

FormulaSnip is licensed under [GPL-3.0-only](LICENSE). Third-party components and model files retain their respective licenses; see [Third-party Notices](THIRD_PARTY_NOTICES.md).
