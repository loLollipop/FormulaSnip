# 隐私与网络行为

本地 OCR 和 MathJax 预览在本机运行。应用仅识别用户框选区域，不把截图或 LaTeX 写入临时文件；图片在识别任务结束后释放，最近结果在当前会话内保留以便恢复。用户点击复制后，LaTeX / MathML 写入系统剪贴板，剪贴板历史和其他软件的读取由操作系统与用户管理。

AI 辅助默认关闭。用户配置并启用后，当前选区会重新编码为 PNG 并发往配置地址的 `/chat/completions`，附带固定提示、模型与请求参数及 Bearer API Key；当前生产路径不发送本地 OCR 候选、用户名、路径或日志。获取模型会请求 `/models`，连接测试也会联网。`store: false` 不是第三方不保留数据的保证，具体费用和保留规则由服务商决定。远程服务要求 HTTPS，明文 HTTP 仅用于字面回环地址；请求不跟随重定向。

自动检查更新默认开启，启动约 1.5 秒后和运行期间按 **12 小时节流**检查，连续重启遵循已保存的检查时间；失败或配置无法写入时可能在下次启动重试。在“设置中心 → 应用与引擎 → 自动检查更新”关闭；手动“检查更新”仍会立即联网。请求地址是 `https://github.com/loLollipop/FormulaSnip/releases/latest/download/FormulaSnip-update-v2.json`，回退到同目录 `FormulaSnip-update.json`，再回退到 `https://api.github.com/repos/loLollipop/FormulaSnip/releases/latest`。受限重定向/下载可能访问 `release-assets.githubusercontent.com`、`objects.githubusercontent.com`。GitHub 可看到 IP、请求时间、URL 与 `FormulaSnip-Updater` User-Agent，更新请求不上传截图、LaTeX 或 API Key。安装版确认后下载与安装，便携版/源码版打开 Release 页面。

Windows 发行包内置 MathCraft 公式模型，可离线首次识别。源码模式未提供内置模型，或内置模型损坏被禁用时，MathCraft 可能使用已有用户缓存或从上游模型源下载；源与固定发行模型信息见 `MODEL_ASSETS.json`。这与更新检查开关独立。

设置通常位于 `HKCU\Software\FormulaSnip\FormulaSnip`；API Key 保存在 Windows Credential Manager 的 `FormulaSnip/CompatibleAI`，绑定到规范化 API 地址，不写普通设置。设置页“删除 Key”可移除凭据。日志位于 `%LOCALAPPDATA%\FormulaSnip\logs`，每个日志最多 1 MB 加两个备份，仅记录事件、异常类型与脱敏调用位置。模型校验诊断记录位于 `%LOCALAPPDATA%\FormulaSnip\model-verification.json`；下载包位于 Qt `CacheLocation/updates`，失败的 `.part` 会清理，旧下载包尽力清理。

卸载默认保留凭据、设置、日志和缓存以便重装。彻底移除前可在设置中删除 Key，或在 Windows 凭据管理器移除上述目标；退出应用后自行备份并删除 FormulaSnip 专属设置/缓存。MathCraft 用户缓存可能由其他程序共用，请不要直接递归删除。自定义 Logo 只保存原文件路径，导入/恢复默认不会删除原图片。
