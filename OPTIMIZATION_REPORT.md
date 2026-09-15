# FormulaSnip 速度与准确度优化报告

调研与本机验证日期：2026-09-15。

## 结论先行

不能通过“把多个开源项目代码全部混在一起”直接得到更准确的模型。不同项目使用不同网络、词表、输入尺寸和运行时；真正融合它们的网络能力需要重新训练和统一数据，而不是简单拼接。

应用层可以可靠集成各自优势：

```text
智能模式
  ├─ 普通公式：RapidLaTeXOCR（轻量 ONNX、启动后直接识别）
  └─ 困难公式：可选 PP-FormulaNet-S 复核
         ├─ 质量检查选择较干净的候选
         └─ 两个结果都保留，允许用户切换
```

默认安装继续保留 Rapid，才能维持约 0.8 GB。Paddle 作为用户按需安装的精确包；本机将两者装入同一环境后，依赖目录与两个模型合计约 1.47 GiB，不能随默认包分发。

## 项目热度与维护历史

Star 只能说明关注度，不能说明特定公式上的准确率。下表同时使用仓库介绍、提交/发布节奏、开放 Issue/PR 和代表性历史问题判断工程成熟度。

| 项目 | Star / Fork 快照 | 最近活动 | Issue/PR 信号 | 对 FormulaSnip 的判断 |
|---|---:|---|---|---|
| [RapidLaTeXOCR](https://github.com/RapidAI/RapidLaTeXOCR) | 386 / 39 | 最新 release 与 main commit：2024-11-03 | 开放 issue 2、PR 0；样本太小，无法证明维护稳健 | ONNXRuntime、依赖相对轻，是当前默认快速后端；维护新鲜度和权重许可需关注 |
| [LaTeX-OCR / pix2tex](https://github.com/lukas-blecher/LaTeX-OCR) | 16,566 / 1,313 | 最新 release：2023-04-13；main：2025-01-18 | 开放 issue 142、PR 17 | 公式 OCR 专属社区最大，但 PyTorch 依赖重，Windows 安装和符号准确问题仍存在 |
| [UniMERNet](https://github.com/opendatalab/UniMERNet) | 500 / 46 | 最新 release：2024-12-26；main：2025-09-28 | 开放 issue 36、PR 2 | 覆盖复杂、截图与手写公式，许可链清晰；权重和 CPU 成本不适合默认桌面包 |
| [PaddleOCR / PP-FormulaNet](https://github.com/PaddlePaddle/PaddleOCR) | 89,574 / 11,336 | v3.7.0：2026-06-11；main：2026-07 | 开放 issue 151、PR 80 | 维护和硬件部署生态最强；只能抽取单公式模块，不能把整套页面 OCR 流水线塞进来 |
| [Surya](https://github.com/datalab-to/surya) | 21,388 / 1,542 | v0.22.1：2026-07-20；main：2026-09 | 开放 issue 163、PR 35 | 当前是统一文档 VLM/server，非轻量单公式后端；运行方式和模型许可均不适合默认集成 |

代表性历史问题：

- pix2tex [#442](https://github.com/lukas-blecher/LaTeX-OCR/issues/442)：2026 年仍有 Windows GUI 的 DLL/typing.io 安装问题；
- pix2tex [#286](https://github.com/lukas-blecher/LaTeX-OCR/issues/286)：特定符号准确率问题；
- Rapid [#15](https://github.com/RapidAI/RapidLaTeXOCR/issues/15)：明确只支持推理、不包含训练能力；
- UniMERNet [#83](https://github.com/opendatalab/UniMERNet/issues/83)：GPU 复现实验问题仍开放；
- PaddleOCR [#15866](https://github.com/PaddlePaddle/PaddleOCR/issues/15866)：CPU 内存泄漏回归最终关闭，但处理周期较长；
- Surya [#507](https://github.com/datalab-to/surya/issues/507)：字体/斜体输出质量问题仍开放。

## 模型、运行时和许可比较

| 模型 | 权重大小 | CPU 路径 | 主要优点 | 主要代价 |
|---|---:|---|---|---|
| RapidLaTeXOCR | 本机 169.78 MiB | ONNXRuntime | 默认包能承受；部署简单；当前双曲线样例完全正确 | 上游 512-token 解码存在极端慢路径；V2 已限制为 128；模型没有置信度；权重未单独声明许可 |
| pix2tex | 约 115.93 MiB | PyTorch | 社区最大；训练与 GUI 资料多 | PyTorch/transformers/timm 依赖重；与 Rapid 同属 LaTeX-OCR 系谱，组合后的互补性有限 |
| UniMERNet tiny | 约 410 MiB | PyTorch CPU | Apache-2.0 权重；复杂、截图、手写覆盖更强 | 尚未计 PyTorch 就占 410 MiB；官方同表 CPU 参考约 8.29 秒 |
| PP-FormulaNet-S | 官方约 224 MB；本机 227.4 MiB | Paddle CPU | 公式专用；官方有 CPU 路径；复杂积分本机结果优于 Rapid | Paddle 独立运行包本机约 730 MiB；首次启动慢；最小依赖漏带 tokenizers/ftfy |
| PP-FormulaNet-plus-S | 约 248 MB | Paddle CPU | 官方中英文 BLEU 比原 S 更好，中文公式值得后续比较 | 同样引入完整 Paddle 运行时；尚未本机验证 |
| PP-FormulaNet-L | 约 695 MB | Paddle CPU | 官方英文 BLEU 高于 S，定位更精确 | 单权重已接近预算，CPU 官方参考约 3.13 秒，不能内置 |
| Surya / Texify | 数百 MB + PyTorch/VLM | server / PyTorch | 页面级能力强、项目活跃 | 不符合单公式范围；Texify 权重含非商业/相同方式共享限制 |

许可事实需要分开看代码与模型：

- PaddleOCR 代码和 PP-FormulaNet 权重卡均为 Apache-2.0，当前候选中最清晰；
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

### PP-FormulaNet-S

- 隔离运行环境约 730.1 MiB，模型约 227.4 MiB；
- 模型初始化约 9.6 秒；
- warm 单图约 0.76 秒；
- 积分识别出正确的 `e^{-x^2}` 与 `d x`，优于 Rapid；
- 双曲线却输出裸 `frac{...}` 和重复减号 `--`，弱于 Rapid。

将 Rapid、Paddle、Qt 和开发依赖装入同一项目环境后，`.venv` 实测为 1,278.8 MiB；PP-S 模型缓存在环境外另占 227.4 MiB，总计约 1,506.2 MiB（1.47 GiB）。相对 720.8 MiB 的 Rapid 默认环境，精确能力增加约 785.4 MiB。

因此 PP-S 不能无条件覆盖 Rapid。两者确实具有互补错误，这正适合“快速基线 + 困难时复核 + 质量规则选择”的应用层融合。

## 为什么不默认加图片增强

Rapid、pix2tex、UniMERNet 和 PP-FormulaNet 都有各自的训练/推理预处理。Rapid 已经执行：

- 前景裁边与极性判断；
- 尺寸限制、宽度预测和 32 倍数 padding；
- 灰度化与训练分布对应的均值/方差归一化。

再次全局二值化、去噪、锐化、放大或紧裁边，可能抹掉小数点、上下标、细分数线和积分上下限。第二版只做图像质量诊断；只有明确低对比度、噪声或倾斜且在真实样本消融中获益时，才增加一个针对性候选。

## 第二版集成策略

1. **快速模式**：只运行 Rapid；直接传 NumPy RGB，减少一次 PNG 编码/解码；限制最坏解码长度并拒绝明显退化输出。
2. **精确模式**：用户安装可选 Paddle 精确包后，直接使用 PP-FormulaNet-S。
3. **智能模式**：先运行 Rapid；当公式含积分、求和、乘积、极限、矩阵/分段结构，或图像/输出质量命中风险时，再运行 PP-S。
4. **结果选择**：优先排除不配对括号、裸 `frac`/`sqrt`、重复运算符、异常长度和明显重复片段；同分的复杂公式优先 PP-S，同时保留 Rapid 候选供用户切换。
5. **数据闭环**：用许可明确的合成公式和用户主动提供的失败样本建立冻结测试集，报告字符串 exact、可渲染率、人工修正率、p50/p95 延迟和峰值内存。

质量规则只是风险判断，不是模型置信度。只有在真实论文公式集上验证后，才能声称总体准确率提高了多少。

真实 `auto` 联调中，双曲线保持 `auto-rapid` 快路径；积分触发 `auto-reviewed`，选择 PP-S 并保留 Rapid/PP-S 两个候选。由此确认路由行为可用，但这两张图片仍不足以计算可靠的总体准确率提升。

## 下一步仍需验证

- 收集用户本次试用中识别错误的原图及正确 LaTeX；
- 至少形成 100–300 个涵盖分式、根式、积分、求和、矩阵、分段、上下标、希腊字母、低清晰度和长公式的冻结集；
- 对 PP-FormulaNet-S 与 plus-S 做同机 head-to-head；
- 验证可选 Paddle 依赖在打包后的独立子进程中运行，避免 DLL/内存影响主界面；
- 在公开/商业发布前取得 Rapid 权重再分发许可的明确证据。
