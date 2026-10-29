# V12：固定 NLI 方法的独立复现

**已完成并审计。** 两套准确率均提高 5.56 pp，三类召回率均不下降；挑战集单侧 p=0.015625，未达本轮 alpha=0.0125，因此保留为主检验未通过。见 [完整结果](RESULTS.md) 和 [审计](audit.json)。

V11 已完成并经审计：基础集 A27/NLI 为 113/120、119/120；挑战集为 56/83、66/83。所有幅度限制通过，但挑战集单侧组置换 p=0.03125，未通过事前 alpha=0.025，故未宣称整个目标已完成。该失败的主检验保留原样。

本轮不是更换提示词后再次测试同一批题。**NLI、A27 的模型、提示词、Schema、参数与 V11 完全一致**；不根据 V11 确认题修改方法，也不重新挑选候选。只做更大独立样本的复现。

## 冻结样本与统计规则

- 新开发样本 306 题：basic 180 题/21 个完整组，challenge 126 题/20 个完整组。
- 排除全部旧 pilot、V5/V7/V8/V9 以及 V11 确认组。
- 每套每种机制按固定输入 hash 选择最多 3 个完整新组；challenge 的 SETCLOSE 只余 2 个，取这两个，其他机制各取 3 个。这个可用组数限制在任何 V12 请求之前检查、写入清单，不按 gold 或正确率选组。
- 主指标仍为 challenge 对同期 A27 的准确率增益至少 5 pp；单侧精确组置换检验 **p≤0.0125**。
- 幅度限制不变：basic accuracy/macro-F1 各下降≤2 pp，challenge macro-F1 不下降，两套每类 recall 下降≤5 pp。
- 前一次 alpha=0.025，本次=0.0125，累计=0.0375；若需要后续新的独立确认，下一次最多=0.00625。不在本轮确认题上重新选择方法，不将两轮拼接后当作新的主检验。

精确检验使用整数卷积枚举组差值正负号分布，结果与直接逐组符号翻转完全相同，避免枚举大量零差值组；该实现已经与独立暴力枚举做单元核对。

模型仍为获准的内网 `qwen38-27b`，`chat_template_kwargs.enable_thinking=false`。只有开发集 claim/evidence 出站；测试集不读取，权重不训练，模型输入没有机制或题目专用规则。认证不落盘，所有产物在仓库内。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -B -m ab_factcheck.server_replication_v12 prepare
.venv\Scripts\python.exe -B -u -m ab_factcheck.server_replication_v12 run
```

运行状态：`outputs/server_v12/pipeline.json`；完成后统计在 `assessment.json`，逐题结果在 `predictions.csv`。成功响应不可重抽，不确定传输保留 inflight 并停止。
