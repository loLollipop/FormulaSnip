# FormulaSnip V4 交付摘要

## 产品目标

FormulaSnip 是一个只识别单个数学公式的 Windows 本地桌面原型，面向论文写作中的高频操作：

```text
启动设置/教程 → 点击悬浮球截图 → 本地识别 → 校对电子公式 → 复制到 Word/MathType
```

不做正文 OCR、表格、整页布局分析和批量 PDF 解析。用户主动框选单个公式，因此无需公式检测模型，安装体积和运行开销更可控。

## V4 已实现

- 1100×700 的极简设置中心：常规、识别、悬浮球和使用方法；
- 顶部单按钮即时切换全局深色/浅色主题，并同步作用于设置中心、菜单和结果面板；
- 悬浮球主体保持中性色，外圈支持推荐色与系统颜色盘任意选色；
- 中心默认显示 `fx` Logo，可上传 PNG/JPEG/WebP/BMP 替换并一键恢复默认；图片读取带格式、文件大小、边长和像素数校验；
- 悬浮球右键菜单固定从球体下方展开，贴近屏幕底部时会自动为菜单留出空间；
- 旧版悬浮球配色及结果主题设置可自动迁移，新增偏好仍兼容旧四字段位置参数；
- 单悬浮工作流：置顶悬浮球点击截图、后台自动识别、就近展开轻量结果面板；
- 悬浮球支持拖动、屏幕边界约束、自动贴边、忙碌态和右键菜单；
- 轻量面板只显示最终采用的 SVG 电子公式，以稳定边距控制预览尺寸，并提供 LaTeX/MathML 复制与重新截图；
- LaTeX 或 MathML 复制成功后自动收起结果面板，便于直接切回 Word/MathType 粘贴；
- 截图遮罩已调亮，并使用高对比自定义十字光标；
- RapidLaTeXOCR 快速后端：CPU/ONNX、懒加载和模型缓存，直接接收 RGB NumPy，减少一次 PNG 转码；
- PP-FormulaNet-S 可选精确后端：CPU/Paddle、懒加载，可单独选择；
- 智能模式：Rapid 优先，只有复杂结构、图片风险或输出风险命中时才调用 Paddle 复核；
- 候选选择：检查括号、裸命令、重复运算符、异常长度和重复片段；后台保留候选供下拉切换，界面只用 SVG 显示当前采用的电子公式；
- Rapid 解码上限从上游 512 缩到 128，原约 59.6 秒的退化样例现在约 3.5 秒即可拒绝；
- 可扩展 benchmark CLI、带 SHA-256/来源/许可校验的 manifest 和两张 CC0 合成样本；
- MathML 剪贴板同时写入纯文本和 `application/mathml+xml`；
- 完整编辑器、图片导入、Word 直写和 pix2tex 产品入口已从 V3 移除；
- 增加项目 MIT 许可证及第三方后端/权重说明。

## 选型依据

调研同时比较了仓库介绍、Star/Fork、发布与提交时间、开放 Issue/PR、代表性历史问题、模型大小、运行时和许可证：

- RapidLaTeXOCR 轻量且易部署，适合作为默认快速后端，但维护活跃度和模型权重许可仍需关注；
- pix2tex 社区最大，但 PyTorch 依赖、Windows 安装问题和与 Rapid 的模型同源性降低了集成收益；
- UniMERNet 对复杂和手写公式有吸引力，但 tiny 权重约 410 MiB，连同 PyTorch 不符合默认体积目标；
- PaddleOCR/PP-FormulaNet 维护最活跃，PP-FormulaNet-S 在困难积分样例上与 Rapid 形成互补，因此作为可选复核后端；
- Surya 已偏统一文档 VLM/server，体积、运行方式和模型许可不适合此单公式产品。

完整证据与链接见 [OPTIMIZATION_REPORT.md](OPTIMIZATION_REPORT.md)。

## 本机验证

- 默认 Rapid 环境及模型约 720.8 MiB；
- Rapid 与 Paddle 一起安装后，环境 1,278.8 MiB，Paddle 模型缓存 227.4 MiB，合计约 1,506 MiB（1.47 GiB）；
- 双曲线实测保留 Rapid 快路径，未无条件启动 Paddle；
- 积分实测触发 Paddle 复核，并保留 Rapid/Paddle 两个候选；
- PP-FormulaNet-S 初始化约 9.6 秒，warm 推理约 0.67–0.76 秒；
- 自动化测试、Ruff、wheel/sdist 打包与内容检查以本轮最终验证记录为准。

## 为什么精确包必须可选

Paddle 的额外成本主要来自约 376.8 MiB 的推理框架、相关依赖和 227.4 MiB 模型。实测在默认版基础上增加约 785 MiB，合并安装后达到约 1.47 GiB，无法继续称为约 0.8 GB 的轻量默认包。

安装精确包不会让普通公式每次都跑两个模型。智能模式只在风险条件命中时复核；用户也可以直接选择 Rapid 或 Paddle。

## 当前边界与下一步

- 当前两张合成 benchmark 只证明路由与回归机制可运行，不足以量化总体准确率提升；
- 下一步最有价值的输入是用户本次试用失败的原图，以及人工确认的正确 LaTeX；
- 应扩充到 100–300 个真实使用分布样本，再报告严格 exact、渲染等价、人工修正率、p50/p95 延迟和升级率；
- 公开或商业安装包前，仍需确认 Rapid 模型权重的再分发授权并生成完整依赖清单；
- Word/MathType 剪贴板交换、异 DPI 多显示器和无 Python 干净电脑上的 EXE 尚待实机验收。

## V4 验证

- `uv run python -m pytest`：52 passed；
- `uv run ruff check .`：通过；
- fake benchmark：2/2 normalized exact；
- wheel 与 sdist 构建成功，wheel 不包含完整编辑器、pix2tex 适配器、pix2tex extra 或 pywin32 依赖；
- 深色设置中心、浅色设置中心、悬浮球外观、快速上手和悬浮结果五张真实 Qt 预览已重新生成并人工检查。
