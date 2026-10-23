# 第四轮 GroqCloud 27B

基线是 `codex/14b-nonthink-v3` 的 `a99a5d8`，工作分支为 `codex/groq-27b-v4`。
第三轮数据、提示词、报告和本地客户端均未修改；第四轮使用独立入口。

## 实际状态

2026-10-23 首个真实技术请求返回 HTTP 403 / Forbidden。程序立即停止，无自动重试。
技术探针尚未通过，6 次 smoke 未完成，正式实验 **0/294**。没有真实27B推理结果。
见 [详细报告](reports/pilot_groq_qwen38_27b_nonthink_v4_r1/pilot_report.md) 和
[脱敏诊断](reports/pilot_groq_qwen38_27b_nonthink_v4_r1/api_diagnostics.json)。

用户已确认 Free Plan，并授权从已有 `.env.local` 加载密钥。该文件仍为本地明文文件，
受到 `.gitignore` 与本地 Git exclude 双重排除，不纳入提交。默认从进程 `GROQ_API_KEY` 读取；
仅显式传入 `--env-local` 时读取本地文件，且拒绝已跟踪或未忽略的文件。

## 恢复顺序

先检查 Groq 项目模型权限、密钥和当前网络能否访问 Groq。403 响应未指出具体原因，
不能据此判定密钥无效、地区限制或模型不可用。不要把密钥发到聊天中。
免费套餐由用户确认；程序不能通过 API 限速头验证账户计费状态。

在仓库根目录 PowerShell 执行：

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ab_factcheck.groq_v4 doctor
.venv\Scripts\python.exe -m ab_factcheck.groq_v4 smoke --free-plan-confirmed --env-local
.venv\Scripts\python.exe -m ab_factcheck.groq_v4 integration --free-plan-confirmed --env-local
.venv\Scripts\python.exe -m ab_factcheck.groq_v4 run --free-plan-confirmed --env-local
.venv\Scripts\python.exe -m ab_factcheck.groq_v4 report
.venv\Scripts\python.exe -m ab_factcheck.groq_v4 audit
```

如果进程环境已有密钥，去掉 `--env-local`。`doctor` 只做离线验证，不调用本地模型、GPU或Groq。
预检严格检查 Schema 枚举/必填/额外字段/maxLength，先做对抗对照，再做3条虚构题×两组。
接入阶段固定 challenge 有序ID的前10条×两组，**不检查正确率来调参**；这20次属于正式运行，
后续跳过已保存的回答。正式剩余顺序为 challenge A/B，然后 basic A/B，各臂内部保持历史顺序。

`run` 重验已有技术门槛和 smoke 文件，不重复已有成功请求。任意推理配置、提示词或推理源码
变化都会导致指纹拒绝；必须建立新 run ID 并保留旧版本。当前失败的 r1 尚无成功回答，
仅修复账户/网络权限、不改配置或代码时可沿用 r1。

## 保护与限制

- 固定 HTTPS 域名及模型，无重定向、无自动模型替换、无套餐升级。
- 单并发；本地25 RPM、7000 TPM，800请求/180000 token滚动24小时预算。
- 请求前以UTF-8字节和输出上限保守预留，成功后以实际usage结算；不称预留值为真实token。
- 全阶段共用 `outputs/groq/quota.json`，重启不清空预算；不要删除账本来绕过保护。
- 429遵守Retry-After及重置时间；等待超过60秒保存暂停；网络/5xx最多2次重试。
- HTTP 400/401/403立即停止。400不得在同一正式run内悄悄降级Schema。
- Schema验证失败、错误答案、双IMPOSSIBLE均不会重生；双IMPOSSIBLE计INVALID_LOGIC。
- `.inflight` 表示请求曾发起但未有原子结果，可能已在服务端完成；自动续跑拒绝重复。
  应先检查进程和账本，不可直接删标记来挑答案。Groq未提供可保证恰好一次的客户端事务接口。
- 服务端返回的RPD/TPM会参与节流，API没有给出TPD剩余额度；同组织其他客户端用量只能依赖
  服务端429进一步约束。本地预算不能代替账户套餐及账单核查。
- 报告中的完整准确率只有在全部结果齐备时发布。部分结果保留全部应测分母及单独完成下界。
- 语义复核表预先固定每数据集每标签前三个ID，以及四个历史错误ID；它不是随机抽样。
  自动审计只复算结构和统计，不代替语义审查。

`outputs/` 中完整本地记录不提交；脱敏诊断、配置、哈希、统计和报告进入
`experiments/004_groq_27b/`。目前没有成功响应可供脱敏导出。完成后报告器可输出完整
`api_records.jsonl`，提交前仍须检查模型文本中的敏感信息。
