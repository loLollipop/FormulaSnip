# FormulaSnip v0.2.13 Release Checklist

本清单针对 v0.2.13 候选版本。`[x]` 表示已有静态、自动化或产物验证证据；`[ ]` 表示仍需人工实机确认或属于已公开记录的残余风险。未完成的人工项不得被描述为“已验证”，但会在不影响自动化发布门禁时作为后续维护事项保留。

## Release Gate

- [ ] `RELEASE_AUDIT.md` 中 AUD-001 已关闭，ANTLR 许可证文本已进入仓库和所有二进制产物
- [ ] Qt/PySide6/QtWebEngine、MathCraft 模型及全部冻结依赖已完成 `Needs Manual License Review`
- [x] 本轮代码级 P1 项已修复，并经独立故障注入复核未再复现
- [x] 本清单与所有修复将一起提交到确定的 v0.2.13 release commit
- [ ] 从该 commit 重新构建完整 Setup、轻量 update EXE、ZIP、wheel、sdist 和两版 update manifest
- [ ] 当前候选版本、tag、文件名、大小和 SHA-256 与 v1/v2 manifest 一致
- [ ] 最终候选完成干净 Windows 安装/升级/卸载验收

## Secrets 与凭据

- [x] 当前源码未发现真实 API Key、Bearer token 或生产私钥
- [x] 全部可达 Git 历史未发现真实 API Key/token
- [x] 测试中的 token/localhost TLS 私钥已核验为夹具，不是生产凭据
- [x] API Key 不写入 QSettings，保存在 Windows Credential Manager
- [x] Key 与规范化 Base URL 绑定，旧版未绑定 Key 不会用于新 endpoint
- [x] 删除 AI Key 会调用 Windows `CredDeleteW`
- [x] AI 输入框使用密码显示并在操作后清空
- [x] 通用异常日志不会记录异常消息、Authorization、截图或 LaTeX
- [x] 两处绕过统一脱敏的日志已修复并有回归测试
- [x] 当前 Release 候选已再次扫描 `.env`、Secret、私钥、测试账号和个人服务器地址

## AI、网络与隐私

- [x] AI 辅助默认关闭，未配置 AI 时本地识别正常工作
- [x] AI 主路径只发送当前框选的重编码 PNG，不发送本地 OCR 候选、文件名或路径
- [x] README 已说明 AI 图片会发送到用户配置的第三方服务
- [x] 远程 AI endpoint 必须 HTTPS；HTTP 仅允许字面 loopback host
- [x] 非 HTTP/HTTPS、userinfo、query、fragment 和非法端口会被拒绝
- [x] AI 请求禁用重定向，3xx 不会转发 Authorization
- [x] TLS 证书验证未关闭
- [x] AI 有 connect/read timeout、30 秒总时限、1 MiB 响应上限和取消路径
- [x] AI 有 4 MiB PNG、4 M 像素和 900 字符 LaTeX 上限
- [x] 401/403/429/5xx、非 JSON、空 choices/content 和超长输出不会破坏本地结果
- [x] 本地识别模式不会发送截图或公式内容
- [x] 自动更新开关和 12 小时检查节流已实现并验证
- [ ] README/隐私说明列出所有联网条件、endpoints、字段、频率和关闭方法
- [x] DNS 长期阻塞时重复取消不会无限增加线程
- [x] GitHub API 回退具有响应上限和绝对总时限
- [ ] 使用真实第三方兼容 API 完成可撤销 Key 的端到端测试

## 输入、预览与输出

- [x] 公式输入面仅为屏幕截图；不支持文件导入、拖拽或图片剪贴板
- [x] 截图在 Qt 转换前限制为 4,000,000 像素，模型 worker 再次校验
- [x] 截图、裁剪图和 AI 上传图不写临时图片文件
- [x] MathJax 使用本地 vendored 资源并阻止网络请求
- [x] LaTeX 通过 HTML escape/JSON 编码和 `textContent` 进入预览
- [x] 预览导航、弹窗、远程 URL、对象和 frame 已限制
- [x] 剪贴板只在用户点击复制后写入 LaTeX/MathML
- [x] LaTeX 编辑器有硬字符上限，超限内容不进入质量检查、MathJax 或 MathML
- [x] 重复片段检查不会接收超过统一长度上限的输入
- [x] Logo 解码同时验证扩展名与真实格式，改名 GIF/SVG/PDF 会被拒绝
- [x] 无效 Logo 不会清空原有有效配置
- [x] 截图转换 `MemoryError/OSError` 会清理 busy/pending 状态并允许重试

## 本地模型与并发

- [x] 发行模型文件集合、大小和 SHA-256 由 `MODEL_ASSETS.json` 固定
- [x] 模型使用 ONNX/JSON/tokenizer，不使用 pickle 或 `torch.load`
- [x] MathCraft 在独立 spawn 子进程运行，原生崩溃不直接拖垮 GUI
- [x] 共享内存在 finally 中 close/unlink
- [x] 模型启动/识别有 180/120 秒超时，响应带 request ID
- [x] worker 崩溃、超时和取消后下一次识别可重建子进程
- [x] manager 串行化本地推理，旧 UI worker 结果按身份丢弃
- [x] UI 最多保留一张预热期间待识别图片
- [x] 模型可信性和轻量更新选择不再依赖可伪造的可写缓存
- [x] 同尺寸模型被修改并伪造缓存时仍会报告 SHA-256 不匹配
- [ ] 已实现每用户单实例，重复启动只激活现有进程
- [ ] 连续识别和取消的长时间 soak 不增加进程、线程、句柄或内存
- [ ] 完全断网且内置模型完好时本地识别正常工作
- [ ] 内置模型缺失/损坏时有明确错误和可恢复路径，不无限下载/等待

## 配置、日志与数据生命周期

- [x] AI URL/模型损坏时回到安全默认值并关闭 AI
- [x] 日志按 1 MB、2 个备份轮转
- [x] 更新 `.part` 文件在失败和取消后清理
- [x] 旧版本更新安装包会做最佳努力清理
- [x] `QSettings.status()` 的 `FormatError/AccessError` 被显式处理并 fail closed
- [x] 配置持久化失败时 UI 不显示“已保存并生效”
- [x] 配置损坏、权限/写入故障和 Qt 延迟刷新回归测试通过
- [ ] 极端持续同步故障下优先使用 `.protected` 恢复精确原件；`.recovery` 可能是 Qt 规范化副本，发布说明不得把两者混称为逐字节原件
- [ ] 卸载时明确提供保留或清除 Key、设置、日志和更新缓存的策略
- [ ] 卸载后的实际残留已在干净机器记录并与文档一致

## 依赖、许可证与供应链

- [x] `uv.lock` 中第三方依赖来自 PyPI HTTPS registry，包记录带 SHA-256
- [x] 构建使用 `uv sync --locked`
- [x] 当前冻结包未发现 Torch、matplotlib、pytest、coverage 或 ruff
- [x] 当前依赖漏洞扫描只命中 Transformers 4.55.4
- [ ] Transformers 公告已逐条完成可达性记录，并与 MathCraft 上游确认处理方案
- [x] ANTLR 4.9.3 BSD 许可证、版权和免责声明已随当前二进制候选分发
- [ ] RapidOCR、tokenizers、flatbuffers 等所有冻结依赖的 LICENSE/NOTICE 已逐项确认
- [ ] Qt/PySide6/QtWebEngine/Chromium 的许可证、credits 和对应源码义务已人工确认
- [ ] MathCraft 模型权重的再分发许可和修改所需形式已人工确认
- [ ] MathJax、latex2mathml、unimathsymbols、Inno Setup 与中文翻译文本已在最终包核对
- [ ] 最终源码交付方式满足 GPL 对应源码要求，不把不完整 sdist 当作唯一源码包
- [ ] 最终依赖生成并归档 SBOM/许可证清单

## 更新与发布真实性

- [x] 更新只接受固定 FormulaSnip GitHub 仓库、HTTPS、白名单 host/path/文件名
- [x] 更新重定向次数有限且不携带应用认证
- [x] 更新安装包有大小与 SHA-256 校验并拒绝降级
- [x] 安装器启动参数固定，不经过 shell 拼接
- [ ] 更新 manifest 具有独立离线签名，或安装器通过固定发布者 Authenticode 验证
- [ ] 若本次不建立 Ed25519 / Authenticode 信任链，维护者已明确记录接受 GitHub Release 权限域风险（哈希不是独立签名）
- [ ] GitHub Release 写权限、2FA、分支保护和发布凭据已人工核验
- [ ] `signtool verify /pa /all` 对最终 EXE、完整 Setup、轻量 update EXE 通过（若采用 Authenticode）
- [ ] 篡改 manifest、安装包、签名或发布者时客户端会 fail closed
- [ ] 最终 Release 页面记录所有产物 SHA-256

## 打包与安装

- [x] 安装器使用 `PrivilegesRequired=lowest`，按当前用户安装
- [x] 不修改 PATH、不安装系统服务、不请求摄像头或麦克风
- [x] 版本源不一致时构建脚本会失败
- [x] 构建脚本包含冻结预览和内置模型 smoke test
- [x] 项目 metadata 不再泄露本机构建路径
- [x] assets 不包含 `__pycache__`，发行包不包含已列入门禁的 debug/devtools 资源
- [x] 当前 ZIP/冻结目录不存在 `.env`、`.git`、测试图片、测试配置、构建缓存或个人绝对路径
- [ ] 在无 Python 的干净 Windows 10 x64 完成全新安装、运行和卸载
- [ ] 在无 Python 的干净 Windows 11 x64 完成全新安装、运行和卸载
- [ ] v0.2.12 → v0.2.13 完整 Setup 升级通过
- [ ] v0.2.12 → v0.2.13 轻量 update 升级通过
- [ ] 模型缺失/损坏时轻量更新拒绝并正确引导完整 Setup
- [ ] 安装/更新后自动重启时间和行为符合预期
- [ ] 便携 ZIP 解压到中文、空格和长路径后正常运行

## 功能与实机稳定性

- [x] v0.2.13 最终源码的 534 项 pytest 全部通过
- [x] Ruff 检查通过
- [x] Python compileall 通过
- [x] wheel 与 sdist 构建检查通过
- [ ] 多显示器、不同缩放比例和 4K 屏幕截图通过
- [ ] CPU 模式在最低目标硬件上工作正常
- [ ] 连续 100 次识别无明显内存/句柄增长
- [ ] 快速重复点击、取消、退出和模型仍在运行时不会卡死或残留后台进程
- [ ] 网络断开、DNS 失败、超时、429、500 和非 JSON 的 GUI 提示均可理解
- [ ] Word 与 MathType 的 LaTeX/MathML 粘贴实测通过
- [ ] 复杂公式结果与原图人工校对流程可用；不宣称 OCR 100% 准确

## 开源项目文档

- [x] 根目录存在 GPL-3.0-only `LICENSE`
- [x] README 有安装、使用、AI 隐私、未签名提示和源码构建说明
- [x] `PROJECT_SUMMARY.md` 与 `OPTIMIZATION_REPORT.md` 的模型说明已更新
- [x] 新增可发现的 `SECURITY.md` 和安全报告渠道
- [ ] README/隐私说明与最终自动更新、模型回退、缓存和卸载行为一致
- [x] Release Notes 只描述当前实际进入 v0.2.13 候选的变化
- [ ] Git 作者姓名/邮箱及仓库公开个人信息已由维护者确认可公开
