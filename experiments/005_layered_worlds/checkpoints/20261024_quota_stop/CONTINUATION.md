# 用户授权使用剩余免费额度：r2 续跑

用户在 2026-10-24 明确要求继续使用现有免费额度，直到免费额度耗尽。
因此，r1 的本地 180000 token / 800 请求提前停止线不再控制这次续跑。
Groq 免费账户的服务端限额是停止依据；账本继续完整记录历史请求与未知失败预留，
不清零，也不把本地滚动 24 小时统计声称为服务端实际日余额。

新身份为 `layered_worlds_qwen38_27b_v5_r2_free`，策略冻结在
`configs/continuation_worlds_v5_free.json`。原 r1 的配置、代码、响应和报告保持原样。
本轮提示词、Schema、四调用顺序、模型、解码参数、样本清单、gold 和输出预算均未改变。

已收到的 22 个 r1 响应按请求、参数、原始记录哈希和依赖核验后复用。
新记录包含 `reused_from` 来源路径、文件哈希、原节点哈希和新增请求数 0。
导入不会修改原始响应或把语义失败替换为新答案。费用报告把复用 token 与新发生 token 分开。

仍执行分钟节流，仍服从服务端响应头和 Retry-After；429/5xx 最多两次有界重试。
长配额重置、协议失败、响应不明或终止型 HTTP 错误会保存进度并停止。
单次执行最多 1000 个新 HTTP 尝试，完成冻结实验后停止，不为消耗额度而发送额外请求。
请求的 UTF-8 字节保守预留只用于记账及节流，不能假称实际 token 数。

不修改账号套餐、支付设置、API 端点、模型或系统代理。既有 Free Plan 授权仍然是前提；
没有账单读取接口，因此不把一次成功响应或免费参考表当作独立零费用证明。

```powershell
.\.venv\Scripts\python.exe -m ab_factcheck.worlds_v5_continuation continue --env-local --free-plan-confirmed
.\.venv\Scripts\python.exe -m ab_factcheck.worlds_v5_continuation report --phase smoke
.\.venv\Scripts\python.exe -m ab_factcheck.worlds_v5_continuation report --phase fresh
.\.venv\Scripts\python.exe scripts/audit_worlds_v5_continuation.py --output experiments/005_layered_worlds/continuation_audit.json
```

`continue` 先完成剩余真实 smoke，再运行相同冻结清单上的 A27 与 V5。
已完成答案复用，未完成请求从原位置继续。任何协议失败不会静默重生成。

Groq 的[限流说明](https://console.groq.com/docs/rate-limits)列出免费参考上限，
指出限额按组织共享、任一种限额触顶即可返回 429。响应头中的 requests 对应 RPD、
tokens 对应 TPM，不提供 TPD 余额。当前策略以服务端实际响应为准。
