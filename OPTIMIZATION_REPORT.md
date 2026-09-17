# FormulaSnip 速度与准确度优化报告

调研与本机验证日期：2026-09-15。

## 结论先行

不能通过“把多个开源项目代码全部混在一起”直接得到更准确的模型。不同项目使用不同网络、词表、输入尺寸和运行时；真正融合它们的网络能力需要重新训练和统一数据，而不是简单拼接。

应用层可以可靠集成各自优势：

```text
智能模式
  ├─ 普通公式：RapidLaTeXOCR（轻量 ONNX、启动后直接识别）
  └─ 困难公式：调用默认安装的 MathCraft OCR 复核
         ├─ 质量检查选择较干净的候选
         └─ 两个结果都保留，允许用户切换
```

当前产品默认同时安装 Rapid 与 MathCraft OCR 0.3.1 CPU，使智能复核和精确模式开箱可用。MathCraft 公式模型约 103.8 MiB，由上游运行时首次使用时下载；智能模式只在风险条件命中时运行 MathCraft，并非每次都运行两个模型。

## 项目热度与维护历史

Star 只能说明关注度，不能说明特定公式上的准确率。下表同时使用仓库介绍、提交/发布节奏、开放 Issue/PR 和代表性历史问题判断工程成熟度。

| 项目 | Star / Fork 快照 | 最近活动 | Issue/PR 信号 | 对 FormulaSnip 的判断 |
|---|---:|---|---|---|
| [RapidLaTeXOCR](https://github.com/RapidAI/RapidLaTeXOCR) | 386 / 39 | 最新 release 与 main commit：2024-11-03 | 开放 issue 2、PR 0；样本太小，无法证明维护稳健 | ONNXRuntime、依赖相对轻，是当前默认快速后端；维护新鲜度和权重许可需关注 |
| [LaTeX-OCR / pix2tex](https://github.com/lukas-blecher/LaTeX-OCR) | 16,566 / 1,313 | 最新 release：2023-04-13；main：2025-01-18 | 开放 issue 142、PR 17 | 公式 OCR 专属社区最大，但 PyTorch 依赖重，Windows 安装和符号准确问题仍存在 |
| [UniMERNet](https://github.com/opendatalab/UniMERNet) | 500 / 46 | 最新 release：2024-12-26；main：2025-09-28 | 开放 issue 36、PR 2 | 覆盖复杂、截图与手写公式，许可链清晰；权重和 CPU 成本不适合默认桌面包 |
| [MathCraft OCR](https://github.com/SakuraMathcraft/LaTeXSnipper) | 当前集成 0.3.1 | ONNX-only 公式/文档 OCR 运行时 | 模型清单带 SHA-256，支持显式 CPU provider 和独立缓存 | 公式 profile 只需约 103.8 MiB 权重，适合作为精确后端 |
| [Surya](https://github.com/datalab-to/surya) | 21,388 / 1,542 | v0.22.1：2026-07-20；main：2026-09 | 开放 issue 163、PR 35 | 当前是统一文档 VLM/server，非轻量单公式后端；运行方式和模型许可均不适合默认集成 |

代表性历史问题：

- pix2tex [#442](https://github.com/lukas-blecher/LaTeX-OCR/issues/442)：2026 年仍有 Windows GUI 的 DLL/typing.io 安装问题；
- pix2tex [#286](https://github.com/lukas-blecher/LaTeX-OCR/issues/286)：特定符号准确率问题；
- Rapid [#15](https://github.com/RapidAI/RapidLaTeXOCR/issues/15)：明确只支持推理、不包含训练能力；
- UniMERNet [#83](https://github.com/opendatalab/UniMERNet/issues/83)：GPU 复现实验问题仍开放；
- MathCraft 0.3.1 的公式 profile 只加载公式识别模型，运行时支持缓存检查、断点下载和 SHA-256 校验；
- Surya [#507](https://github.com/datalab-to/surya/issues/507)：字体/斜体输出质量问题仍开放。

## 模型、运行时和许可比较

| 模型 | 权重大小 | CPU 路径 | 主要优点 | 主要代价 |
|---|---:|---|---|---|
| RapidLaTeXOCR | 本机 169.78 MiB | ONNXRuntime | 默认包能承受；部署简单；当前双曲线样例完全正确 | 上游 512-token 解码存在极端慢路径；V2 已限制为 128；模型没有置信度；权重未单独声明许可 |
| pix2tex | 约 115.93 MiB | PyTorch | 社区最大；训练与 GUI 资料多 | PyTorch/transformers/timm 依赖重；与 Rapid 同属 LaTeX-OCR 系谱，组合后的互补性有限 |
| UniMERNet tiny | 约 410 MiB | PyTorch CPU | Apache-2.0 权重；复杂、截图、手写覆盖更强 | 尚未计 PyTorch 就占 410 MiB；官方同表 CPU 参考约 8.29 秒 |
| MathCraft formula-rec | 本机约 103.8 MiB | ONNX Runtime CPU | 公式专用；六张真实样例覆盖偏导、梯度和复杂分式 | 首次使用需联网下载；warm CPU 实测约 0.8–3.5 秒 |
| Surya / Texify | 数百 MB + PyTorch/VLM | server / PyTorch | 页面级能力强、项目活跃 | 不符合单公式范围；Texify 权重含非商业/相同方式共享限制 |

许可事实需要分开看代码与模型：

- MathCraft OCR 0.3.1 代码包为 GPL-3.0-only，与 FormulaSnip 的项目许可证兼容；模型权重不进入发行包；
- UniMERNet 代码和官方权重卡为 Apache-2.0；
- Rapid 仓库为 MIT，但 PyPI 元数据写 Apache-2.0，自动下载权重未见单独许可；
- pix2tex 代码为 MIT，checkpoint 未见单独许可；
- Surya 代码为 Apache-2.0，但模型权重使用带商业条件的 OpenRAIL-M；关联 Texify 权重更不适合商业默认包。

## 本机实测，而不是只看榜单

测试机为当前 Windows/Python 3.12 环境，以下数字只用于同机 PoC，不代表所有电脑。

### RapidLaTeXOCR

- 双曲线：warm 约 1.3–1.5 秒，输出完全正确；
- 特殊字体积分：约 1.3–2.0 秒，但把 `e` 和 `dx` 误识别；
- 灰度、自动对比度、阈值、锐化和放大均未修正该积分；
- 将困难积分缩小到 0.65 倍后触发退化的 512-token 输出，耗时约 59.6 秒。

这说明 Rapid 的首要速度优化是限制异常解码长度、删除多余图片转码，而不是无条件尝试多种滤镜。

### MathCraft OCR 0.3.1 formula-rec

- 公式模型缓存约 103.8 MiB；
- 六张真实截图均正确或仅有样式命令差异，其中两张 PDE 正确输出 `\partial` 与 `\nabla`；
- warm CPU 单图约 0.8–3.5 秒；
- 通过可复用 spawn 子进程运行，GUI 与原生推理崩溃隔离，截图通过共享内存传输。

MathCraft 不无条件覆盖 Rapid。普通干净公式仍走 Rapid 快路径；复杂结构、图像风险、不可预览或明显质量问题才触发复核。两个内容不同但均无明显质量缺陷的候选默认采用精确引擎，同时向用户显示分歧并保留两者。

## 为什么不默认加图片增强

Rapid、pix2tex、UniMERNet 和 MathCraft 都有各自的训练/推理预处理。Rapid 已经执行：

- 前景裁边与极性判断；
- 尺寸限制、宽度预测和 32 倍数 padding；
- 灰度化与训练分布对应的均值/方差归一化。

再次全局二值化、去噪、锐化、放大或紧裁边，可能抹掉小数点、上下标、细分数线和积分上下限。第二版只做图像质量诊断；只有明确低对比度、噪声或倾斜且在真实样本消融中获益时，才增加一个针对性候选。

## 第二版集成策略

1. **快速模式**：只运行 Rapid；直接传 NumPy RGB，减少一次 PNG 编码/解码；限制最坏解码长度并拒绝明显退化输出。
2. **精确模式**：直接使用默认安装的 MathCraft OCR CPU。
3. **智能模式**：先运行 Rapid；当公式含积分、求和、乘积、极限、偏导/梯度、重音导数混淆、多重分式、矩阵或多行环境，或图像/输出质量命中风险时，再运行 MathCraft。
4. **结果选择**：优先排除不配对括号、裸 `frac`/`sqrt`、重复运算符、异常长度和明显重复片段；没有明显质量差异且内容不同时采用 MathCraft，同时保留 Rapid 候选并显示分歧警告。能否预览不参与准确率排序。
5. **数据闭环**：用许可明确的合成公式和用户主动提供的失败样本建立冻结测试集，报告字符串 exact、可渲染率、人工修正率、p50/p95 延迟和峰值内存。

质量规则只是风险判断，不是模型置信度。只有在真实论文公式集上验证后，才能声称总体准确率提高了多少。

真实 `auto` 联调中，普通干净公式保持 `auto-rapid` 快路径；复杂和风险公式触发 `auto-reviewed`，选择 MathCraft 并保留 Rapid/MathCraft 两个候选。由此确认路由行为可用，但六张图片仍不足以计算可靠的总体准确率提升。

## 下一步仍需验证

- 收集用户本次试用中识别错误的原图及正确 LaTeX；
- 至少形成 100–300 个涵盖分式、根式、积分、求和、矩阵、分段、上下标、希腊字母、低清晰度和长公式的冻结集；
- 扩充 MathCraft 与 Rapid 的冻结真实样本，持续检查 PDE、矩阵和多行环境；
- 在无 Python 的干净 Windows 环境验证打包后的 MathCraft spawn 子进程、首次模型下载与断网重试；
- 在公开/商业发布前取得 Rapid 权重再分发许可的明确证据。
