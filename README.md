# FormulaSnip

<p align="center">
  <img src="formulasnip/assets/formulasnip.png" width="88" alt="FormulaSnip Logo">
</p>

<p align="center">
  面向 Windows 论文写作的公式截图识别工具
</p>

<p align="center">
  <a href="https://github.com/loLollipop/FormulaSnip/releases/latest"><img src="https://img.shields.io/github/v/release/loLollipop/FormulaSnip?label=Release" alt="GitHub Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0-blue.svg" alt="GPL-3.0 License"></a>
  <img src="https://img.shields.io/badge/Platform-Windows%20x64-0078D4" alt="Windows x64">
</p>

FormulaSnip 可以通过悬浮球框选屏幕中的单个公式，将其识别为可编辑的电子公式，并复制为 **LaTeX** 或 **MathML**，方便粘贴到 Word、MathType 及其他公式编辑器。

## 功能

- 点击悬浮球，框选并识别公式；
- 内置 RapidLaTeXOCR 与 PP-FormulaNet-S 双识别引擎；
- 提供智能、快速、精确三种识别模式；
- 显示 SVG 电子公式预览，方便识别后校对；
- 一键复制 LaTeX 或 MathML，复制后自动收起结果面板；
- 支持深色与浅色主题、自定义悬浮球圆环颜色和中心 Logo；
- 安装版支持在应用内检查并安装更新。

## 界面预览

![FormulaSnip 设置中心](artifacts/formulasnip_settings_center_dark.png)

![FormulaSnip 识别结果](artifacts/formulasnip_floating_result_dark.png)

## 安装

前往 [GitHub Releases](https://github.com/loLollipop/FormulaSnip/releases/latest) 下载最新版本：

- `FormulaSnip-v0.2.1-windows-x64-setup.exe`：安装版，提供安装向导、桌面快捷方式和卸载入口；
- `FormulaSnip-v0.2.1-windows-x64.zip`：便携版，解压后运行 `FormulaSnip.exe`。

首次使用识别引擎时需要联网下载模型，下载完成后即可离线识别。当前安装包尚未进行代码签名，Windows SmartScreen 可能显示风险提示，请仅从本仓库下载。

## 使用方法

1. 启动 FormulaSnip，点击“开始识别”；
2. 左键点击悬浮球，框选需要识别的公式；
3. 在电子公式预览中核对识别结果；
4. 复制 LaTeX 或 MathML；
5. 粘贴到 Word、MathType 或其他公式编辑器。

右键悬浮球可以重新打开设置或退出软件，按 `Esc` 可以取消截图。

## 识别模式

| 模式 | 说明 |
|---|---|
| 智能 | 默认模式，先快速识别，复杂公式或疑似异常结果再由第二引擎复核 |
| 快速 | 使用 RapidLaTeXOCR，适合清晰、结构简单的公式 |
| 精确 | 使用 PP-FormulaNet-S，适合复杂公式 |

公式识别无法保证完全正确，请在粘贴前核对电子公式预览。

## 从源码运行

需要 Python 3.10–3.12 和 [uv](https://docs.astral.sh/uv/)：

```powershell
uv sync
uv run python -m formulasnip
```

## 开源协议

FormulaSnip 采用 [GPL-3.0-only](LICENSE) 协议开源。第三方依赖与模型遵循各自的许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
