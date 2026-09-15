# FormulaSnip

FormulaSnip 是一个面向 Windows 论文写作场景的本地公式识别原型。它只处理用户截取的单个公式，不包含正文 OCR、表格或整页版面识别。

> 当前交付是可运行的 V4 源码原型，还不是双击安装的 EXE。默认快速环境实测约 720.8 MiB；同时安装可选精确包后约 1.47 GiB。

默认启动先显示完整设置中心，可查看四步使用教程；点击“开始识别公式”后进入悬浮模式：

![FormulaSnip 深色设置中心](artifacts/formulasnip_settings_center_dark.png)

![FormulaSnip 悬浮球外观设置](artifacts/formulasnip_appearance_live_preview.png)

![FormulaSnip 使用教程](artifacts/formulasnip_quick_start.png)

![FormulaSnip 悬浮模式](artifacts/formulasnip_floating_result_dark.png)

当前支持：

- 可拖动、置顶并自动贴边的 `fx` 悬浮球；
- 点击悬浮球直接框选公式，完成后自动识别并展开轻量结果面板；
- 结果面板只显示最终采用的 SVG 电子公式，可直接复制 LaTeX 或 MathML，复制成功后自动收起；
- 右键悬浮球可打开设置或退出，结果面板也可重新截图；
- 简洁设置中心只保留常规、识别、悬浮球和使用方法四个页面；
- 顶部单按钮即时切换整个软件的深色/浅色主题；
- 悬浮球主体保持统一中性色，圆环支持推荐颜色和系统颜色盘；中心默认显示 `fx`，也可上传图片替换并恢复默认；
- 智能、快速和精确三种识别路径；
- 后台可比较 Rapid 与 PP-FormulaNet-S 的候选，但界面只呈现最终采用结果；
- 用 SVG 矢量排版成电子公式，放大仍保持清晰；
- 复制 LaTeX 或带 MathML MIME 的 MathML；
- 通过剪贴板粘贴到 Word、MathType 或其他支持 LaTeX/MathML 的编辑器。

## 安装与启动

默认快速版只安装 RapidLaTeXOCR：

```powershell
uv sync --extra rapid
uv run python -m formulasnip
```

需要智能复核和精确模式时，再安装 Paddle 精确包：

```powershell
uv sync --extra rapid --extra paddle
uv run python -m formulasnip
```

开发环境可在命令后增加 `--extra dev`。Rapid 与 Paddle 都会在第一次使用时联网下载模型，下载完成后可以离线识别。

## 三种识别路径

- **智能模式（推荐）**：先运行 Rapid；遇到积分、求和、极限、矩阵、低质量图片或疑似异常 LaTeX 时，再调用 PP-FormulaNet-S 复核并显示最终采用结果。
- **快速模式**：在设置中选择 RapidLaTeXOCR，只运行轻量 ONNX 后端。
- **精确模式**：在设置中选择 PP-FormulaNet-S，直接运行可选 Paddle 后端。它不保证每个公式都比 Rapid 正确，因此仍需人工校对。

智能路由使用的是确定性风险规则，不是模型置信度，也不会把多个模型的神经网络直接拼接。普通、清晰公式不会因为安装了精确包就同时运行两个模型。

## 体积与速度实测

测试环境为本机 Windows、Python 3.12：

| 配置 | 安装后占用 | 运行特征 |
|---|---:|---|
| Rapid 默认快速版 | 约 720.8 MiB，含约 170.7 MiB Rapid 模型 | warm 通常约 1–2 秒 |
| Rapid + Paddle 精确包 | 约 1,506 MiB（1.47 GiB） | 额外增加约 785 MiB |
| PP-FormulaNet-S 模型 | 上表已包含；模型单独约 227.4 MiB | 首次初始化约 9.6 秒，warm 约 0.67–0.76 秒 |

这些是安装后的目录占用，不是尚未制作的压缩安装包大小。不同 Python/依赖版本会略有变化。

## 基本使用

1. 启动后在设置中心选择识别模式、圆环颜色和 Logo；需要时打开左侧“快速上手”。
2. 点击“开始识别公式”，设置面板收起，只保留悬浮球。
3. 左键点击悬浮球并框选单个公式；Esc 可以取消，遮罩下使用高对比十字光标。
4. 识别完成后，悬浮球旁展开带白边的电子公式结果。
5. 核对后复制 LaTeX 或 MathML；复制成功后结果面板自动收起，可直接到 Word/MathType 粘贴。
6. 右键悬浮球可以重新打开设置或退出软件。

FormulaSnip 通过 LaTeX/MathML 剪贴板与 Word、MathType 交换公式，不调用 MathType 私有接口，也不直接修改 Word 文档。

## 基准与开发命令

```powershell
uv run python -m pytest
uv run ruff check .
uv run python scripts\benchmark_recognition.py --backend rapid --runs 3 --output artifacts\benchmark-rapid.json
uv run python scripts\benchmark_recognition.py --backend auto --runs 3 --output artifacts\benchmark-auto.json
```

`benchmarks/manifest.json` 会校验样本路径、SHA-256、来源和许可证。当前仅有两张 CC0 合成样本，用于验证基准框架和回归路径，不能据此宣称总体准确率提高了某个百分比。

## 当前边界

- 截图功能截取鼠标所在屏幕，不自动寻找整页中的公式。
- 本地预览使用 Matplotlib MathText 生成 SVG 矢量公式，不覆盖全部 LaTeX 宏；预览失败不影响复制结果。
- 质量规则可发现括号不配对、裸 `frac/sqrt`、重复运算符、异常长度和重复片段，但无法判断所有“语法正确、数学含义错误”的结果。
- Rapid 权重未见单独的再分发许可说明；公开或商业安装包必须先完成权重授权与第三方许可证核验。
- 尚未在真实 Word/MathType、多种 Office 版本和异 DPI 多显示器环境中完成兼容性验收。

项目调研、Star/Issue 历史、模型比较和本机实测见 [OPTIMIZATION_REPORT.md](OPTIMIZATION_REPORT.md)，交付范围见 [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)。
