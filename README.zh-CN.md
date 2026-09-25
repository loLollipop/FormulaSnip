<p align="center">
  <img src="https://raw.githubusercontent.com/loLollipop/FormulaSnip/main/formulasnip/assets/formulasnip.png" width="108" height="108" alt="FormulaSnip 标志">
</p>

<h1 align="center">FormulaSnip</h1>

<p align="center"><strong>框选公式截图，获得可编辑的 LaTeX 与 MathML。</strong></p>

<p align="center">
  <a href="https://github.com/loLollipop/FormulaSnip/releases/latest"><img src="https://img.shields.io/github/v/release/loLollipop/FormulaSnip?style=flat-square&amp;label=Release" alt="最新版本"></a>
  <a href="https://github.com/loLollipop/FormulaSnip/stargazers"><img src="https://img.shields.io/github/stars/loLollipop/FormulaSnip?style=flat-square&amp;label=Stars&amp;color=FFD700" alt="GitHub Stars"></a>
  <a href="https://github.com/loLollipop/FormulaSnip/releases"><img src="https://img.shields.io/github/downloads/loLollipop/FormulaSnip/total?style=flat-square&amp;label=Downloads" alt="GitHub 下载量"></a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D4?style=flat-square&amp;logo=windows11&amp;logoColor=white" alt="Windows 10 和 11">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/loLollipop/FormulaSnip?style=flat-square&amp;label=License" alt="GPL-3.0 协议"></a>
</p>

<p align="center">
  <a href="https://github.com/loLollipop/FormulaSnip/releases/latest"><strong>下载软件</strong></a>
  · <a href="#下载与开始使用">快速开始</a>
  · <a href="https://github.com/loLollipop/FormulaSnip/blob/main/README.md">English</a>
  · <a href="https://github.com/loLollipop/FormulaSnip/issues">问题反馈</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/loLollipop/FormulaSnip/main/artifacts/formulasnip_settings_center_dark.png" width="860" alt="FormulaSnip 设置中心">
</p>

FormulaSnip 是一款面向 Windows 论文、笔记与技术文档写作场景的公式识别工具。点击悬浮球，框选屏幕上的单个公式，核对渲染后的公式预览，然后把结果复制到 Word、MathType、LaTeX 编辑器或其他支持数学公式的软件中。

FormulaSnip 专注于识别**单个数学公式**，不用于整页文档、表格或通用文字 OCR。

[English](https://github.com/loLollipop/FormulaSnip/blob/main/README.md) · 简体中文

---

## 可以做什么

| 功能 | 说明 |
| --- | --- |
| 📸 **截图识别** | 点击悬浮球，拖动框选屏幕上任意位置的公式 |
| 🧠 **本地运行** | 使用内置的 MathCraft OCR CPU 模型，默认不上传截图 |
| ✏️ **校对编辑** | 对照离线渲染的公式预览，在复制前直接修改 LaTeX |
| 📋 **论文写作输出** | 复制 LaTeX 或 MathML，用于 Word、MathType、Markdown 与 LaTeX |
| ✨ **AI 辅助** | 可选接入 OpenAI 兼容视觉模型，与本地识别并行运行 |
| 🎨 **个性化外观** | 支持深浅模式、四套界面主题色、圆环颜色和自定义悬浮球 Logo |
| 🔄 **软件更新** | 在客户端检查新版本；安装版可通过可视进度下载并安装校验后的更新 |

---

## 下载与开始使用

1. **安装 FormulaSnip。** 前往 [Releases](https://github.com/loLollipop/FormulaSnip/releases/latest) 下载 Setup 安装包，运行安装并按需创建快捷方式。
2. **开始识别。** 打开 FormulaSnip，点击“开始识别”，桌面上会保留一个悬浮球。
3. **框选并复制。** 左键点击悬浮球，拖动框住一个公式，核对结果后复制 LaTeX 或 MathML。

> [!IMPORTANT]
> 官方 Windows Setup 和便携 ZIP 已内置 Python 运行时、应用依赖和锁定版本的 MathCraft 公式模型，不需要单独安装 Python，也不需要在首次识别时下载模型。

| 安装包 | 适用场景 |
| --- | --- |
| `FormulaSnip-v*-windows-x64-setup.exe` | **推荐。** 提供安装向导、快捷方式、卸载入口和客户端自动更新 |
| `FormulaSnip-v*-windows-x64.zip` | 便携使用；完整解压后运行 `FormulaSnip.exe` |

**系统要求：** Windows 10 或 Windows 11，x64。

> [!NOTE]
> 当前版本尚未进行 Authenticode 代码签名，Windows SmartScreen 可能显示风险提示。请只从本仓库的官方 Releases 页面下载 FormulaSnip。

---

## 使用流程

### 1. 框选公式

左键点击悬浮球，拖动鼠标框住一个公式。截图时可按 `Esc` 或点击鼠标右键取消。

<p align="center">
  <img src="https://raw.githubusercontent.com/loLollipop/FormulaSnip/main/artifacts/formulasnip_snip_overlay.png" width="760" alt="FormulaSnip 公式截图界面">
</p>

### 2. 核对渲染结果

FormulaSnip 使用离线 MathJax 渲染电子公式，不会只显示放大的截图。你可以直接修改识别出的 LaTeX，并立即核对更新后的排版。

<p align="center">
  <img src="https://raw.githubusercontent.com/loLollipop/FormulaSnip/main/artifacts/formulasnip_floating_result_dark.png" width="620" alt="FormulaSnip 公式渲染预览与复制操作">
</p>

### 3. 粘贴到编辑器

| 粘贴目标 | 建议格式 |
| --- | --- |
| Microsoft Word 或 MathType | **MathML**——在公式编辑区域粘贴 |
| LaTeX 编辑器或 Markdown | **LaTeX**——粘贴到对应的数学环境 |

复制成功后，结果面板会自动关闭，可以直接回到论文或文档中粘贴。

> [!TIP]
> 公式 OCR 无法保证完全正确。复杂分式、矩阵、积分、偏导数和紧密上下标应在粘贴前与原图认真核对。

---

## 可选 AI 辅助

AI 辅助默认关闭。打开“设置 → 识别”，启用“AI 辅助识别”，填写 OpenAI 兼容 API 地址和 API Key，拉取并选择模型，测试连接后保存配置。

- FormulaSnip 可以拉取服务端模型列表并测试连接。
- 本地 MathCraft OCR 与远程视觉模型相互独立、并行识别。
- 两种结果确实不一致时，可在结果面板中切换对照。
- AI 请求失败时，仍会保留本地识别结果。
- API Key 保存在 Windows 凭据管理器中，不写入普通设置文件。

配置的服务商会收到本次框选的公式图片，并可能根据其政策收费或保留请求。启用前请阅读[隐私说明](PRIVACY.md)。

---

## 界面与外观

<p align="center">
  <img src="https://raw.githubusercontent.com/loLollipop/FormulaSnip/main/artifacts/formulasnip_appearance_live_preview.png" width="49%" alt="FormulaSnip 外观设置">
  <img src="https://raw.githubusercontent.com/loLollipop/FormulaSnip/main/artifacts/formulasnip_recognition_engine.png" width="49%" alt="FormulaSnip 本地识别与可选 AI 设置">
</p>

- 设置中心、识别结果和更新弹窗会使用所选界面主题色。
- 浅色与深色模式可以独立于主题色切换。
- 悬浮球圆环颜色和中心 Logo 可单独设置。
- 系统托盘可快速开始截图、打开设置、检查更新或退出软件。

---

## 从源码运行

源码开发需要 Python `>=3.10,<3.13` 和 [uv](https://docs.astral.sh/uv/)：

```powershell
git clone https://github.com/loLollipop/FormulaSnip.git
cd FormulaSnip
uv sync --extra dev
uv run python -m formulasnip
```

运行测试与代码检查：

```powershell
uv run pytest -q
uv run ruff check .
```

使用 [Inno Setup 6](https://jrsoftware.org/isinfo.php) 构建 Windows 便携包与 Setup 安装包：

```powershell
.\scripts\build_windows.ps1
```

如果构建缓存中没有校验通过的模型，发行构建会下载并验证锁定版本的 MathCraft 模型。

---

## 隐私与安全

- 本地 OCR 和电子公式预览在用户电脑上运行。
- 正常识别流程不会把公式截图写入临时文件。
- 未启用 AI 辅助时，公式识别保持本地运行。自动检查更新默认开启并连接 GitHub，可在设置中关闭；可选 AI 辅助只连接用户配置的服务商。
- 更新安装包会在安装前校验大小和 SHA-256。

完整行为和当前发行限制请查看[隐私说明](PRIVACY.md)、[安全说明](SECURITY.md)与[第三方说明](THIRD_PARTY_NOTICES.md)。

---

## 参与项目

欢迎提交 Issue 或 Pull Request。反馈识别问题时，请附上原始公式图片和预期 LaTeX，并移除其中的隐私信息。

- [提交问题](https://github.com/loLollipop/FormulaSnip/issues)
- [查看发行版本](https://github.com/loLollipop/FormulaSnip/releases)
- [私密报告安全漏洞](https://github.com/loLollipop/FormulaSnip/security/advisories/new)

---

## 致谢

- [MathCraft OCR](https://github.com/SakuraMathcraft/LaTeXSnipper) 与 [MathCraft Models](https://github.com/SakuraMathcraft/MathCraft-Models) 提供本地公式识别基础。
- [PySide6](https://doc.qt.io/qtforpython-6/) 提供 Windows 桌面界面支持。
- [MathJax](https://www.mathjax.org/) 提供离线电子公式预览。
- [latex2mathml](https://github.com/roniemartinez/latex2mathml) 提供 MathML 转换。

---

## 开源协议

FormulaSnip 采用 [GPL-3.0-only](LICENSE) 协议开源。第三方组件与模型文件保留各自的许可证，详见[第三方说明](THIRD_PARTY_NOTICES.md)。
