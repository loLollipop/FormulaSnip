# Security

请优先通过 GitHub 的 [私密漏洞报告入口](https://github.com/loLollipop/FormulaSnip/security/advisories/new)联系维护者。该入口是否启用由仓库维护者控制；如不可用，请创建不含利用细节、凭据或用户内容的 Issue 请求私密联系方式。不要在公开 Issue 上传 API Key、截图或原始日志。请提供版本、操作系统和脱敏复现步骤；目前不承诺固定响应时限。

本地识别使用独立 MathCraft 子进程和锁定的 ONNX 模型；每次模型可信性判断均核对文件集合、大小与完整 SHA-256。用户可写的校验记录仅用于诊断。完整性检查不能抵御具有同一用户写权限的程序同时修改应用和模型锁。

更新使用固定 GitHub Release 地址、HTTPS、大小与 SHA-256 校验，安装前需要用户确认。**目前没有独立更新签名或固定发布者 Authenticode 信任链**；哈希用于检测损坏，不能抵御 Release 权限被接管后清单与安装包同时替换。当前社区发行版明确保留这一风险，并仅通过本仓库的官方 GitHub Release 分发；后续计划引入 Authenticode 或独立清单签名。仓库不包含发布私钥或占位签名。

MathCraft 0.3.1 精确约束 Transformers 4.55.4，已知 advisories 和许可证人工门禁见 [第三方说明](THIRD_PARTY_NOTICES.md)及 [发布清单](RELEASE_CHECKLIST.md)。本轮没有跨越上游约束升级 Transformers，也不将当前路径不可达视为全库无漏洞。

隐私、联网和本地保留说明见 [PRIVACY.md](PRIVACY.md)。Windows 单实例限制用于避免重复加载资源；它不是本地权限隔离。
