# FormulaSnip 正式开源发布前审计

审计日期：2026-09-21
审计对象：未发布的 `v0.2.11` 工作区
基线：`main` / `8f45dbe4d5e95a22ddc4963a9d0a5a34454f5678` + 13 个既有未提交修改
目标平台：Windows 10/11 x64
审计阶段：第一阶段，只审计，不修改业务代码、依赖、架构或 UI

> 本报告审计的是准备发布的 v0.2.11 源码和构建配置。`dist` 中现存的完整 Windows 产物仍是 v0.2.10，不能代表本次工作区；v0.2.11 修复完成后的最终 Setup、轻量更新包和 ZIP 必须重新构建并单独验收。

## Executive Summary

当前状态：**原始审计快照；修复后的放行状态以 `RELEASE_CHECKLIST.md` 为准**。

> 2026-09-21 修复说明：本报告用于保留首次审计证据，其中“当前”“缺失”等措辞描述的是审计当时的工作树。AUD-001 的 ANTLR 许可证缺口及本轮确认的代码级 P1 已修复，487 项测试、发行包卫生检查、冻结预览和离线模型 smoke test已通过。最终候选仍未进行 Authenticode 签名，Qt/Chromium、模型与完整冻结依赖的许可证义务，以及干净 Windows 安装/升级/卸载，仍属于人工发布门禁。不要把本报告单独当作最终放行结论。

没有发现真实 API Key、未经说明上传截图、可由远程输入触发的 SSRF、AI 重定向泄露 Authorization、预览脚本注入、任意命令执行或任意文件读写。基础识别流程、AI 失败回退、模型子进程隔离、图片/响应大小限制和更新下载校验已有较完整的防线，406 项自动化测试、Ruff 和 Python 编译检查均通过。

当前存在一个确定的发布阻断项：Windows 二进制会包含 ANTLR runtime，但仓库没有随二进制分发其 BSD 许可证文本；其他第三方组件和模型的再分发义务也仍需人工许可证复核。此外，模型哈希缓存、超长 LaTeX、配置持久化、多实例、Logo 内容类型、更新信任链和默认联网行为建议在发布前处理。

| Severity | 数量 |
| --- | ---: |
| Critical | 0 |
| High | 1 |
| Medium | 8 |
| Low | 9 |
| Informational | 0 |

## 审计范围与限制

已覆盖：

- 全部已跟踪 Python、PowerShell、Inno Setup、依赖锁、模型锁、README、许可证与测试代码；
- 当前工作树和全部 18 个可达 Git 提交的 Secret 特征扫描；
- 本地识别、AI、预览、配置、凭据、日志、缓存、更新、打包、卸载和权限数据流；
- 当前锁定环境的依赖漏洞扫描；
- 现有 v0.2.10 ZIP/冻结目录，用于验证当前构建方式会产生什么内容，不用于代替 v0.2.11 候选验收。

未覆盖：

- 干净 Windows 虚拟机中的 v0.2.11 安装、升级、卸载和 SmartScreen 行为；
- 真实 GPU 路径（当前产品使用 CPU ONNX）、多显示器/高 DPI、RAM/磁盘满、断电与长期运行；
- Qt/Chromium、ONNX Runtime 等第三方原生库的完整源码审计和模糊测试；
- 完整法律意见。许可证不明确处只标记 `Needs Manual License Review`；
- GitHub 账号、2FA、分支保护、Release 权限和发布密钥管理的服务端配置。

## 架构与数据流

### 技术栈

- Python 3.10–3.12；PySide6/Qt Widgets 与 Qt WebEngine；
- Pillow、latex2mathml、requests；
- MathCraft OCR 0.3.1、ONNX Runtime CPU；
- PyInstaller 便携目录与 Inno Setup 每用户安装器；
- QSettings、Windows Credential Manager、Windows 共享内存和 spawn 子进程。

### 本地识别

```text
用户点击悬浮球
→ QScreen 抓取当前屏幕
→ 用户框选并仅保留选区
→ QImage 在内存中转 PNG/Pillow RGB
→ RecognitionWorker
→ BackendManager 串行调度
→ 共享内存传入独立 MathCraft 子进程
→ ONNX CPU 推理
→ LaTeX 质量检查
→ 离线 MathJax 预览
→ 用户主动复制 LaTeX 或 MathML
```

正常本地路径不会把截图或 LaTeX 发送到网络，也不会把截图落盘。截图在 Qt 转换前和模型 worker 内均限制为 4,000,000 像素。

### 可选 AI 路径

```text
用户显式启用 AI 并保存 URL、Key、模型
→ 本地 OCR 与 AI 分支并行
→ 选区转为 RGB PNG Base64 data URL
→ POST <用户配置的 Base URL>/chat/completions
→ 返回 JSON LaTeX
→ 与本地结果比较
→ 不一致时要求用户显式选择
```

当前 UI 调用 `transcribe_formula()`，只发送本次框选图片、固定提示、模型名和请求参数，不发送本地 OCR 候选、文件名、路径、用户名、机器标识或软件日志。请求包含 `store: false`，但第三方实际保留策略仍由用户选择的服务商决定。

### 本地与远程边界

| 数据/操作 | 默认本地 | 可能联网的条件 | 远端 |
| --- | --- | --- | --- |
| 公式截图与本地 OCR | 是 | 启用并配置 AI 后识别 | 用户配置的兼容 API |
| 本地 OCR LaTeX | 是 | 当前生产 AI 路径不发送 | N/A |
| API Key | Windows Credential Manager | AI 请求时作为 Bearer header | 用户配置的兼容 API |
| 模型文件 | 安装版内置并校验 | 源码运行或内置模型损坏时 MathCraft 可能回退下载 | MathCraft 上游模型源 |
| 更新检查 | 否 | 每次 GUI 启动约 1.5 秒后及定时检查 | GitHub |
| 更新安装包 | 用户缓存 | 用户确认下载更新 | GitHub Release |
| 公式预览 | 是 | 不联网 | 本地 MathJax |

### 配置、缓存、临时数据与日志

| 类型 | 位置 | 内容 |
| --- | --- | --- |
| 设置 | 通常为 `HKCU\Software\FormulaSnip\FormulaSnip` | 主题、Logo 路径、AI URL/模型/开关、更新检查时间；不含 Key |
| API Key | Windows Credential Manager，target `FormulaSnip/CompatibleAI` | 版本化 JSON，Key 与规范化 Base URL 绑定 |
| 日志 | `%LOCALAPPDATA%\FormulaSnip\logs` | `application.log`、`mathcraft-worker.log`；1 MB × 当前文件与 2 个备份 |
| 模型验证缓存 | `%LOCALAPPDATA%\FormulaSnip\model-verification.json` | 模型路径、锁摘要和文件元数据 |
| 更新缓存 | Qt `CacheLocation/updates` | 已下载的 Setup/update EXE 与下载期 `.part` |
| 截图/识别图片 | 进程内存与共享内存 | 终态释放；应用自身不创建临时截图文件 |

## [AUD-001] 二进制第三方许可证材料不完整

Severity: High
Category: Open-source compliance / Supply chain
File: `FormulaSnip.spec`; `THIRD_PARTY_NOTICES.md`; `THIRD_PARTY_LICENSES/`
Line: `FormulaSnip.spec:52-78`; `THIRD_PARTY_NOTICES.md:7-11`
Affected Component: Windows ZIP、Setup、轻量更新包

### 问题描述

冻结程序实际包含 `antlr4-python3-runtime 4.9.3` 的 55 个模块，但仓库和随包许可证目录没有 ANTLR 对应的 BSD 许可证、版权和免责声明。现有 Notice 声称会在 `THIRD_PARTY_LICENSES` 补齐上游 wheel 缺失的文本，但该目录目前只有五份其他组件文本。RapidOCR、tokenizers、flatbuffers 等实际依赖的许可证/NOTICE 覆盖也尚未逐项证实。

### 触发方式

按当前 PyInstaller/Inno 配置构建并公开分发 ZIP 或安装包。

### 实际影响

确定违反 ANTLR BSD 二进制再分发所要求的许可证文本保留条件；其他组件可能还有未完成的归属义务。该问题无需攻击者即可发生。

### 是否可以实际利用

No。它是确定的发布合规问题，不是运行时漏洞。

### 修复建议

补入 ANTLR 4.9.3 的准确许可证文本和组件映射；对最终冻结依赖生成 SBOM/许可证清单，逐项补齐 RapidOCR、tokenizers、flatbuffers、Qt/Chromium 等所需 LICENSE/NOTICE。不要把复制 `.dist-info` 等同于许可证已完整覆盖。

### Verification

对最终 v0.2.11 ZIP 和两个 Setup 包解包，逐个冻结依赖核对许可证与 Notice；增加实际产物级测试，不只检查 spec 字符串。

## [AUD-002] 可写模型校验缓存可使完整 SHA-256 校验被跳过

Severity: Medium
Category: Model integrity
File: `formulasnip/recognition/mathcraft_backend.py`; `formulasnip/update.py`
Line: `mathcraft_backend.py:44-48,64-135`; `update.py:414-440`
Affected Component: 内置模型加载、轻量更新包选择

### 问题描述

模型验证缓存位于当前用户可写的 LocalAppData。只要缓存 JSON 与当前路径、锁摘要和文件元数据相等，代码就直接返回成功而不再计算模型 SHA-256。缓存没有 MAC 或签名；同一用户进程可以替换同尺寸模型、恢复可控时间字段并构造匹配缓存。

### 触发方式

首次验证产生缓存后，模型内容与缓存被同一用户上下文中的进程同步篡改，或发生保持比较元数据的同尺寸损坏。

### 实际影响

损坏或替换的 ONNX/配置文件可能被当作已验证模型加载；更新检查也可能错误选择只含程序文件的轻量更新包。安装目录本身为每用户可写，因此这不是跨权限边界，但与“完整模型哈希验证”的安全承诺不一致。

### 是否可以实际利用

Conditional。需要本机同一用户写权限；不能据此声称存在远程模型 RCE。

### 修复建议

模型是否可信、是否允许轻量更新的判断必须执行完整 SHA-256。缓存只能用于性能提示，不能作为跳过安全校验的决定依据；或把缓存绑定到由安装器维护的不可伪造证明。

### Verification

先生成缓存，再将一个模型文件替换为同尺寸内容并伪造匹配缓存；运行时和 `installed_model_bundle_identity()` 都必须报告 hash mismatch。

## [AUD-003] 超长手工 LaTeX 可阻塞 GUI 线程

Severity: Medium
Category: Resource exhaustion / UI stability
File: `formulasnip/ui/floating.py`; `formulasnip/recognition/quality.py`
Line: `floating.py:554-582,800-816,871-892`; `quality.py:298-320`
Affected Component: 结果编辑、质量检查、MathJax、MathML 复制

### 问题描述

结果编辑器没有字符上限。每次文本变化都会在 GUI 线程同步处理完整字符串；重复片段检测包含嵌套扫描，随后完整文本还会进入 MathJax 和 MathML 转换。

### 触发方式

完成一次识别后，在 LaTeX 编辑框粘贴数百 KB 至数 MB 的重复内容。

### 实际影响

实测 `assess_latex` 对 100 KB 约 0.6 秒、500 KB 约 3 秒，5 MB 探针超过 30 秒；叠加 Qt WebEngine 和转换会进一步增加 CPU/内存，造成应用假死。

### 是否可以实际利用

Conditional。需要本机用户粘贴或被诱导粘贴，不是无交互远程 DoS。

### 修复建议

编辑器设置 4–8 KiB 的硬上限；质量检查入口先做 O(1) 长度短路；超限内容不得进入 MathJax 或 MathML。把重复片段检测改为有界或线性算法。

### Verification

覆盖 900 字符、上限、上限 + 1 和多 MB 粘贴；事件循环哨兵应保持响应，超限内容不得触发预览/转换。

## [AUD-004] 配置损坏或不可写时仍显示“已保存”

Severity: Medium
Category: Configuration integrity
File: `formulasnip/ui/settings.py`
Line: `settings.py:233-314,1842-1885`
Affected Component: QSettings、AI 和外观配置

### 问题描述

`FloatingPreferences.load/save` 不检查 `QSettings.status()`；`sync()` 失败后调用者仍显示“配置已保存并生效”。损坏 INI 返回 `FormatError`，不可写目录返回 `AccessError`，当前代码均不可见。

### 触发方式

配置损坏、配置目录只读、磁盘满、权限异常或旧配置迁移写入失败。

### 实际影响

内存中的设置当次会话看似生效，重启后丢失；AI Key 本身仍在凭据管理器，但 URL、模型和启用绑定可能丢失，用户会被错误成功提示误导。

### 是否可以实际利用

No。通常是环境故障或数据损坏。

### 修复建议

`sync()` 后检查状态并返回/抛出专用错误；调用者只有在成功持久化后才能显示“已保存”。加载遇到 `FormatError` 时提示并提供显式备份与重建。

### Verification

测试损坏配置、只读目录、父路径为普通文件、模拟磁盘写失败和迁移失败；均不得显示成功，且应用仍可用安全默认值启动。

## [AUD-005] 缺少单实例约束会重复加载模型与 WebEngine

Severity: Medium
Category: Process lifecycle / Resource exhaustion
File: `formulasnip/app.py`; `formulasnip/recognition/mathcraft_worker.py`
Line: `app.py:51-64`; `mathcraft_worker.py:261-263`
Affected Component: 应用启动、模型预热、系统托盘

### 问题描述

每次启动都会创建完整 QApplication、MathJax WebEngine、托盘和独立 MathCraft 子进程；未发现 QLockFile、命名 mutex 或本地 IPC 单实例机制。

### 触发方式

用户在慢启动时重复双击，或多次运行 EXE。

### 实际影响

模型、ONNX Runtime 和 WebEngine 内存线性增长，低内存机器可能换页或 OOM；多个进程还会并发读写相同设置和模型缓存。

### 是否可以实际利用

Conditional。仅本机同一用户，主要是误操作和稳定性风险。

### 修复建议

在预热前建立每用户单实例锁；第二实例通过本地 IPC 激活第一实例或请求开始截图后退出；异常退出后的锁必须可恢复。

### Verification

并发启动两个安装版进程，确认只保留一个主进程和一个 MathCraft worker；第一实例崩溃后应能重新启动。

## [AUD-006] Logo 扩展名白名单可被内容嗅探绕过

Severity: Medium
Category: File parsing / Attack surface
File: `formulasnip/ui/settings.py`
Line: `settings.py:88-91,172-202,2191-2209`
Affected Component: 自定义悬浮球 Logo

### 问题描述

代码先按后缀允许 PNG/JPEG/WebP/BMP，随后又启用 `QImageReader.setDecideFormatFromContent(True)`。实测把 GIF、SVG 或 PDF 改名为 `.png` 后均可被读取；发行目录也包含对应 Qt 解码插件。

### 触发方式

用户主动选择一个扩展名伪装的 GIF/SVG/PDF 作为 Logo。

### 实际影响

实际原生解码攻击面超出 UI 声明；像素和边长限制不能完整约束 SVG/PDF 的节点或解析复杂度，保存后每次启动还会再次解析。没有证据证明当前 Qt 解码器存在可直接利用漏洞。

### 是否可以实际利用

Conditional。需要诱导用户选择文件；本次审计只证实类型绕过，不声称已实现代码执行。

### 修复建议

在读取前后核对 `reader.format()`，只允许 png/jpeg/webp/bmp，并要求扩展名与内容一致；在解码前拒绝 GIF、SVG、PDF。

### Verification

测试直接和改名后的 GIF/SVG/PDF、双扩展名、无扩展名、损坏头、Unicode 路径及全部允许格式。

## [AUD-007] 自动更新缺少独立于 GitHub 的签名信任链

Severity: Medium
Category: Update security
File: `formulasnip/update.py`; `scripts/build_installer.ps1`; `FormulaSnip.spec`
Line: `update.py:365-464,868-949`; `build_installer.ps1:190-245`; `FormulaSnip.spec:156-172`
Affected Component: 应用内更新

### 问题描述

安装包与包含其 SHA-256 的 manifest/GitHub metadata 来自同一个 GitHub Release 信任域。客户端校验 HTTPS、host、路径、大小和 SHA-256，但没有离线公钥签名或固定发布者 Authenticode 验证。当前 EXE/Setup 未签名，README 已披露。

### 触发方式

GitHub 仓库/Release 权限被接管，或系统信任的 TLS 代理/CA 同时替换清单和安装包，用户随后确认更新。

### 实际影响

攻击者可以提供相互匹配的恶意安装器与哈希，客户端会在当前用户权限下启动。普通网络 MITM 不能直接绕过现有 HTTPS 与 host 白名单。

### 是否可以实际利用

Conditional。需要发布控制面或本机 TLS 信任链失陷。

### 修复建议

优先采用独立离线密钥签名 manifest，并把验证公钥固化在客户端；或 Authenticode 签名并固定校验预期发布者/证书。签名私钥不应与 GitHub Release 写权限处于同一信任域。

### Verification

分别篡改清单、安装包、签名和证书发布者，均必须在 `startDetached` 前 fail closed。

## [AUD-008] 锁定的 Transformers 4.55.4 存在多条已知漏洞公告

Severity: Medium
Category: Dependency vulnerability
File: `uv.lock`; `pyproject.toml`
Line: `uv.lock:1345-1346`; `pyproject.toml:20`
Affected Component: MathCraft OCR 传递依赖

### 问题描述

`pip-audit` 对当前环境报告 Transformers 4.55.4 共 12 条已知漏洞记录，包括模型配置、checkpoint 反序列化和路径处理类公告。MathCraft 0.3.1 精确固定该版本。

### 触发方式

调用受影响的 Transformers 功能并处理攻击者控制的模型/配置/checkpoint。

### 实际影响

当前 FormulaSnip 路径禁用了 Torch/TF/Flax，只从发布锁定的本地目录加载 tokenizer/processor；冻结包没有 Torch，也未调用 Trainer、AutoModel 或 `save_pretrained()`，因此没有证明截图输入可到达公告中的 RCE/路径穿越。风险主要是保留了已知有缺陷的更大代码面和未来代码变化的回归风险。

### 是否可以实际利用

Conditional；当前可达性未证实。

### 修复建议

记录每条公告的可达性结论；与 MathCraft 上游协调兼容升级或精简冻结模块。不能直接越过 MathCraft 的精确版本约束盲目升级。

### Verification

升级后重新运行完整识别、冻结包 smoke test 和 `pip-audit`；同时确认最终 EXE 未包含无需使用的训练/checkpoint 模块。

## [AUD-009] 每次启动强制联网检查更新且无关闭项

Severity: Medium
Category: Privacy / Network behavior
File: `formulasnip/app.py`; `formulasnip/ui/floating.py`; `README.md`
Line: `app.py:51-60`; `floating.py:1195-1228`; `README.md:62-66`
Affected Component: 启动、更新检查、离线承诺

### 问题描述

GUI 每次启动约 1.5 秒后以 `force=True` 检查更新，从而绕过已有 12 小时间隔。设置中没有自动检查开关。README 说明安装版会检查更新，但没有关闭方式和完整网络字段说明。

### 触发方式

任何正常 GUI 启动，即使用户从未启用 AI。

### 实际影响

GitHub 可观察来源 IP、启动时间、URL 和 `FormulaSnip-Updater` UA；不会收到截图、LaTeX 或 API Key。行为使“本地识别”容易被误解为应用默认零网络，并增加离线/受限网络噪声。

### 是否可以实际利用

No。属于默认网络行为与隐私/预期一致性问题。

### 修复建议

提供“自动检查更新”开关或首次启动明确选择；默认检查应遵循 12 小时节流，不应使用 `force=True`；文档列出固定 endpoints、发送字段、频率和关闭方式。

### Verification

干净设置下抓包启动；默认关闭方案应为 0 请求，用户同意方案应只按设定间隔请求。连续重启不得每次联网。

## [AUD-010] GitHub API 回退响应无大小上限和绝对总时限

Severity: Low
Category: Network resource limit
File: `formulasnip/update.py`
Line: `update.py:703-733`
Affected Component: 更新检查 API 回退

### 问题描述

静态 manifest 使用有界流式读取；GitHub API 回退设置 `stream=True` 后直接 `response.json()`。30 秒 read timeout 是相邻读取超时，不是绝对请求截止时间，也没有响应字节上限。

### 触发方式

两个静态 manifest 都失败，随后受信上游或 TLS 代理返回超大或持续慢滴流 JSON。

### 实际影响

后台线程可能长期占用或因大响应增加内存。

### 是否可以实际利用

Conditional。需要受信上游或本机 TLS 信任链异常。

### 修复建议

复用 manifest 的有界流读取，并为整个 API 请求设置绝对 deadline。

### Verification

测试无 Content-Length 超大响应和每 29 秒发送少量字节的慢滴流。

## [AUD-011] DNS 阻塞时 AI 请求线程可能在取消后继续存活

Severity: Low
Category: Network cancellation / Resource leak
File: `formulasnip/recognition/openai_correction.py`
Line: `openai_correction.py:531-634`
Affected Component: AI 模型列表、连接测试、AI 识别

### 问题描述

AI 请求放在 daemon 线程并有总时限；socket tracker 能关闭已创建 socket，但 DNS 解析阶段尚无 socket。总时限返回后，解析线程可能继续存活并暂时保留请求闭包与 Key。

### 触发方式

用户配置的主机名 DNS 长期阻塞，并重复发起测试或识别。

### 实际影响

残留线程和内存可能累积，Key 在进程内存中的生命周期延长；未发现 Key 被写日志或发送到其他 host。

### 是否可以实际利用

Conditional。需要用户主动配置该地址或本机 DNS 故障。

### 修复建议

使用可取消/有 deadline 的解析方案或独立进程；至少限制同时存在的遗留请求数。

### Verification

持续阻塞解析并重复取消，线程数必须保持有界。

## [AUD-012] 两处日志绕过统一脱敏函数

Severity: Low
Category: Logging / Privacy
File: `formulasnip/ui/floating.py`; `formulasnip/diagnostics.py`
Line: `floating.py:1103-1111,1408-1426`; `diagnostics.py:23-31`
Affected Component: 预览预热、更新安装器启动

### 问题描述

预览预热使用 `logger.exception()` 写完整 traceback，安装器启动失败把 `str(exc)` 写入日志；其他异常统一使用只保留异常类型和文件名/行号/函数的 `log_exception()`。

### 触发方式

MathJax 预热异常或安装器校验/启动异常。

### 实际影响

日志可能出现完整用户路径和内部运行细节。未发现这些路径携带 API Key、截图或 LaTeX 的真实数据流。

### 是否可以实际利用

No。需先发生本地异常。

### 修复建议

两处均改用统一脱敏日志，UI 使用固定错误文案。

### Verification

注入带用户路径和秘密标记的异常，日志不得出现异常原文或绝对路径。

## [AUD-013] 当前构建方式会泄露本机构建路径并携带不必要调试资源

Severity: Low
Category: Packaging hygiene / Privacy
File: `FormulaSnip.spec`
Line: `FormulaSnip.spec:28-38,52-78`
Affected Component: 便携 ZIP、安装目录

### 问题描述

`copy_metadata("formulasnip")` 会复制 editable 安装的 `direct_url.json`。现有构建产物已证实包含本机项目绝对路径；递归复制 assets 还带入 `__pycache__`。Qt WebEngine 的 debug/devtools `.pak` 和 QML debugger 插件也进入发行包，其中单个 devtools debug pak 约 75.8 MB。

### 触发方式

在当前开发环境按现有 spec 构建 Windows 包。

### 实际影响

公开本机构建目录，扩大包体、攻击面和审计范围。没有证据表明这些资源自动开放远程调试端口。

### 是否可以实际利用

No。当前证实为信息泄露和构建卫生问题。

### 修复建议

不要复制项目 editable 的 `direct_url.json`；对 assets 和 Qt 资源采用允许清单，排除缓存、调试资源和无用插件；最终归档扫描个人绝对路径。

### Verification

解包 v0.2.11 ZIP/Setup，搜索 `.git`、`.env`、`direct_url.json`、`__pycache__`、项目绝对路径、debug pak 和 debugger 插件。

## [AUD-014] 卸载不会清除凭据、设置和更新缓存

Severity: Low
Category: Data lifecycle
File: `installer/FormulaSnip.iss`; `formulasnip/credentials.py`
Line: `FormulaSnip.iss:40-103`; `credentials.py:19-24,161-183`
Affected Component: 卸载、API Key、用户缓存

### 问题描述

安装器没有卸载清理钩子。卸载应用后，Windows Credential Manager 中的 AI Key、QSettings、日志、模型验证缓存和已下载更新包仍保留。

### 触发方式

配置过 AI 后通过 Windows 卸载 FormulaSnip。

### 实际影响

同一 Windows 用户后续仍可读取该凭据，缓存继续占用磁盘；不会因此向其他 Windows 用户公开。保留配置也可能是重装体验的有意选择，但当前没有明确说明或选择。

### 是否可以实际利用

Conditional。需要同一用户上下文或本机已具备相应访问权的程序。

### 修复建议

明确保留策略；卸载时提供“保留设置/彻底清除”的显式选择，或在文档说明手动删除方式。共享的 MathCraft 用户缓存不能盲目递归删除。

### Verification

分别执行保留卸载和彻底卸载，核对凭据、设置、日志与更新缓存的实际状态。

## [AUD-015] 无效 Logo 导入会清空原有有效配置

Severity: Low
Category: UI data loss
File: `formulasnip/ui/settings.py`
Line: `settings.py:2191-2209`
Affected Component: 外观设置

### 问题描述

选择损坏、超限或不支持的图片时，代码直接清空 `_logo_path` 并提示“已恢复默认 Logo”，随后保存配置，而不是保留原 Logo 并报告导入失败。

### 触发方式

已有自定义 Logo 后误选无效文件。

### 实际影响

原文件未删除，但配置引用丢失，用户需要重新选择。

### 是否可以实际利用

No。属于可恢复的本地设置丢失。

### 修复建议

验证失败时保留旧路径并显示错误；仅“恢复默认”按钮可以清空。

### Verification

配置有效 Logo 后依次选择损坏、超限和不支持文件，旧配置与预览应保持不变。

## [AUD-016] 截图转换的非 ValueError 异常会遗留忙状态

Severity: Low
Category: Error handling / UI state
File: `formulasnip/ui/floating.py`; `formulasnip/ui/image_conversion.py`
Line: `floating.py:1618-1640`; `image_conversion.py:18-31`
Affected Component: 截图转图、悬浮球状态

### 问题描述

悬浮球先进入 busy，转换只捕获 `ValueError`；字节复制、Pillow 解码/加载和 RGB 转换还可能抛出 `MemoryError` 或 `OSError`，这些路径不会调用 `_recognition_failed()` 收敛 UI。

### 触发方式

截图转换阶段内存不足或底层 PNG/Pillow 异常。

### 实际影响

悬浮球可能永久保持“识别中”且截图入口不可用，通常需重启。

### 是否可以实际利用

No。公开输入是屏幕截图，不是攻击者提供的文件；主要是低内存恢复问题。

### 修复建议

在转换边界映射 `OSError/MemoryError` 为固定用户错误，并用统一 finally/状态收敛确保 busy、图片和 pending 状态被清理。

### Verification

注入 `MemoryError` 和 `OSError`，确认 busy 清除、无 worker 遗留并可立即重新截图。

## [AUD-017] 两份项目说明与当前内置模型行为相矛盾

Severity: Low
Category: Documentation accuracy
File: `PROJECT_SUMMARY.md`; `OPTIMIZATION_REPORT.md`; `README.md`
Line: `PROJECT_SUMMARY.md:22,31`; `OPTIMIZATION_REPORT.md:17-18`; `README.md:62-66,116`
Affected Component: 开源文档、安装预期

### 问题描述

两份旧说明仍写“Windows 发行包不捆绑模型/首次使用下载模型”，而当前 README、spec、模型锁和安装器设计均要求发行包内置并校验模型。

### 触发方式

用户或贡献者阅读这些仓库文档。

### 实际影响

误导离线能力、包体、网络行为和测试预期；不会直接导致运行时安全问题。

### 是否可以实际利用

No。

### 修复建议

删除或更新陈旧说明，明确区分安装/便携发行包与源码运行的模型行为。

### Verification

全仓搜索“首次下载”“不捆绑模型”，所有说法必须与 v0.2.11 实际产物一致。

## [AUD-018] 缺少安全披露入口和完整网络/隐私说明

Severity: Low
Category: Open-source maintenance / Privacy documentation
File: repository root; `README.md`
Line: `README.md:62-85,118-130`
Affected Component: 开源维护、漏洞披露、隐私预期

### 问题描述

仓库没有 `SECURITY.md` 或独立隐私/网络行为说明。README 对 AI 图片上传和 Key 保存已有清楚说明，但没有完整描述更新 endpoints、启动频率、模型回退下载、日志/缓存保留、卸载残留和安全报告渠道。

### 触发方式

用户评估隐私或安全研究者尝试负责任披露。

### 实际影响

数据边界和维护承诺不易发现，可能造成错误隐私预期或安全报告公开泄露。

### 是否可以实际利用

No。属于发布资料缺口。

### 修复建议

新增简洁 `SECURITY.md` 和网络/隐私章节，列出数据、固定 endpoints、触发条件、关闭方式、保留位置和凭据删除/卸载行为。

### Verification

发布文档评审应覆盖截图、AI、更新、模型、剪贴板、日志、缓存、卸载和漏洞报告渠道。

## 已核实的安全控制与否定结论

- 当前仓库及全部 18 个可达 Git 提交未发现真实生产 API Key/token；命中项为测试用 `unit-test-token`、localhost TLS 测试私钥和查询参数测试数据。
- API Key 保存在 Windows Credential Manager，不进入 QSettings；凭据与规范化 Base URL 绑定，旧版未绑定裸 Key 不会用于新地址；删除配置调用 `CredDeleteW`。
- AI 只允许 HTTP/HTTPS；远程地址必须 HTTPS，字面 localhost/127.0.0.1/::1 可用 HTTP；禁止 userinfo、query、fragment 和非法端口。
- HTTPS 可指向私网/回环地址，但地址只能由本机用户主动配置，未发现远程输入控制路径，因此不报告为可被外部触发的 SSRF。
- AI 请求 `allow_redirects=False`，3xx 显式拒绝，Key 不会随重定向转发；TLS 验证未关闭。
- AI 有 5/10 秒 connect/read timeout、30 秒总时限、1 MiB 响应、4 MiB PNG、4 M 像素和 900 字符 LaTeX 上限；失败保留本地结果。
- MathJax 初始内容经 HTML escape，后续内容经 `json.dumps` 并写入 `textContent`；CSP、请求拦截、导航策略和禁用弹窗形成额外边界。未发现 XSS、`javascript:`/`file:` 导航或本地文件读取。
- 公式识别不支持打开 PNG/JPG/WEBP/BMP/GIF/SVG/PDF、拖拽文件或粘贴图片；主输入只有屏幕截图。因此这些文件格式作为“公式输入”的路径、MIME 欺骗、路径穿越和同目录读取均为 Not Applicable。Logo 是单独输入面，已在 AUD-006 记录。
- 模型使用 ONNX/JSON/tokenizer 文件，不使用 pickle 或 `torch.load`；发行模型由固定集合、大小和 SHA-256 锁约束。
- 未发现 `os.system`、`shell=True`、用户可控参数进入 shell、动态 `eval/exec` 或任意命令执行。
- UI 同时只允许一个识别任务；manager 串行化推理，信号按 worker 身份过滤；未发现旧结果覆盖新结果。共享内存在 finally 中 close/unlink，退出会终止模型 worker。
- 日志按 1 MB、2 个备份轮转；统一日志不记录异常消息、截图、LaTeX、Key 或完整路径。
- 安装器使用 `PrivilegesRequired=lowest`，写入每用户 LocalAppData 与 HKCU；不修改 PATH、不安装服务、不请求摄像头/麦克风。权限面为截屏、剪贴板写、网络、用户文件/注册表、Credential Manager 和 CPU/GPU runtime。

## 测试覆盖评估

现有 406 项测试对凭据、AI URL/重定向/异常响应、超时与取消、模型锁、worker 崩溃恢复、共享内存、预览编码、更新清单/下载校验、UI 状态和打包脚本已有较好覆盖。

仍缺少或不足：

- 超长手工 LaTeX 和 GUI 响应性；
- QSettings FormatError/AccessError 与磁盘满；
- 两个真实安装版进程并发启动；
- Logo 内容/扩展错配回归；
- 截图转换 MemoryError/OSError 的 UI 收敛；
- 模型缓存伪造后的完整性回归；
- 最终 v0.2.11 Setup/ZIP 的许可证、Secret、路径和资源允许清单测试；
- 干净 Windows 全新安装、v0.2.10 → v0.2.11 完整/轻量升级、卸载；
- 真实多显示器/高 DPI、长期循环识别、内存/句柄 soak、断网和第三方兼容 API。

## P0 — 发布前必须解决

- AUD-001：补齐确定缺失的 ANTLR 许可证，并完成最终依赖许可证清单人工复核。
- 修复后必须从唯一提交重新构建 v0.2.11 候选；当前 v0.2.10 产物不能作为验收依据。

## P1 — 强烈建议发布前解决

- AUD-002 至 AUD-009。
- AUD-012、AUD-013、AUD-016、AUD-017、AUD-018 都是低成本且直接影响正式开源发布质量的项目，建议一并关闭。

## P2 — 可以后续改进

- AUD-010、AUD-011、AUD-014、AUD-015。
- 在不延误安全修复的前提下继续完善更长时间的性能基准、SBOM 自动化和资源允许清单。

## Release Blockers

1. ANTLR 4.9.3 的二进制再分发许可证文本确定缺失。
2. Qt/PySide6/QtWebEngine、MathCraft 模型及 RapidOCR/tokenizers/flatbuffers 的最终许可证/NOTICE 覆盖尚未人工确认，标记为 `Needs Manual License Review`。
3. v0.2.11 最终候选尚未构建；所有源码修复完成前不得复用或重命名现有 v0.2.10 产物。

## Recommended Before Release

- 关闭所有 P1；尤其是模型缓存完整性、超长 LaTeX、配置写失败、Logo 内容类型和默认更新检查。
- 明确接受或解决“GitHub 是唯一更新信任根”的风险；若暂不签名，必须加强 GitHub 发布权限、2FA 和发布流程并在文档披露。
- 对 Transformers 公告形成书面可达性判断，与 MathCraft 上游确认可兼容版本。
- 清理构建路径、缓存与调试资源，并建立最终产物允许清单。
- 增加 SECURITY/网络隐私文档并修正陈旧模型说明。

## Can Be Improved Later

- 可取消 DNS 解析和更新 API 绝对 deadline；
- 卸载数据保留选择；
- 无效 Logo 导入体验；
- 完整 SBOM/许可证自动化、长时间 soak 与更多真实公式基准。

## Manual Verification Required

- 在无 Python 的干净 Windows 10/11 x64 机器执行全新 Setup 安装、启动、快捷方式、托盘、更新和卸载；
- 从 v0.2.10 分别执行 v0.2.11 完整包和轻量包升级，确认保留设置/模型、自动重启速度和失败回退；
- 实测完全断网本地识别、首次启动、内置模型缺失/损坏、更新服务器不可达；
- 实测 Word 与 MathType 的 LaTeX/MathML 粘贴、中文用户名和空格路径；
- 实测多显示器、不同 DPI、4K 屏幕、超宽公式、连续识别和长时间内存/句柄变化；
- 使用真实但可撤销的第三方兼容 API 测试 401/403/429/500、非 JSON、慢响应、取消和费用/数据披露；
- 解包最终 Setup、update EXE 和 ZIP，扫描 Secret、`.env`、`.git`、测试数据、绝对路径、缓存、debug 资源和许可证；
- 记录最终产物 SHA-256，并验证 GitHub Release 中 tag、manifest、文件名、大小和摘要一致；
- 人工确认 GPL-3.0-only、Qt/PySide6/Chromium、MathCraft 模型、Inno 翻译以及所有冻结依赖的再分发义务；
- 若采用签名，执行 `signtool verify /pa /all` 并测试错误发布者/错误签名拒绝。

## 自动化验证记录

| 检查 | 结果 |
| --- | --- |
| `uv run --locked ruff check .` | 通过 |
| `uv run --locked python -m compileall -q formulasnip tests scripts` | 通过 |
| `uv run --locked pytest -q` | 406 项全部通过，退出码 0 |
| `uv build --no-sources` | wheel 与 sdist 构建成功；审计临时产物已删除 |
| `pip-audit`（当前 `.venv`） | 仅 Transformers 4.55.4 命中 12 条记录；见 AUD-008 |
| 当前工作树 Secret 特征扫描 | 未发现生产 Secret；命中为测试数据 |
| 全部可达 Git 历史扫描 | 18 commits / 394 unique blobs；未发现生产 Secret |
| `git diff --check` | 通过；仅显示既有 LF/CRLF 提示 |
