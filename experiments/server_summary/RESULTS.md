# 内网服务器实验总览

模型为服务器返回的 `qwen38-27b`，所有请求明确关闭思考。只使用开发输入，无 SFT/LoRA 或权重更新，无题目专用提示。各轮选法和完整组独立确认单独报告，不合并 p 值或事后放宽门槛。

| 轮次 | 固定方法 | 基础 A27 → 方法 | 挑战 A27 → 方法 | 挑战增益 | 组置换 p | 预定 alpha | 主标准及幅度限制 |
|---|---|---:|---:|---:|---:|---:|---|
| V11 | nli | 113/120 → 119/120 | 56/83 → 66/83 | +12.05 pp | 0.03125000 | 0.025 | 未通过 |
| V12 | nli | 164/180 → 174/180 | 85/126 → 92/126 | +5.56 pp | 0.01562500 | 0.0125 | 未通过 |
| V13 | nli | 109/120 → 116/120 | 134/236 → 161/236 | +11.44 pp | 0.00001240 | 0.00625 | 通过 |

V13 的挑战确认只覆盖六种剩余机制，SETCLOSE 没有未使用开发组。V11/V12 覆盖七种机制；下表分轮列出结果，不能把旧机制结果说成 V13 的新确认，也不能当作测试集结果。幅度限制不是总体统计非劣效证明。

## 挑战集分机制结果

| 轮次 | 机制 | 完整组数 | A27 | 方法 | 准确率差 |
|---|---|---:|---:|---:|---:|
| V11 | AMBIGREF | 2 | 7/10 | 6/10 | -10.00 pp |
| V11 | DENIAL | 2 | 10/16 | 10/16 | +0.00 pp |
| V11 | LOOKALIKE | 2 | 6/12 | 9/12 | +25.00 pp |
| V11 | PRESUP | 2 | 7/9 | 7/9 | +0.00 pp |
| V11 | SETCLOSE | 2 | 8/10 | 10/10 | +20.00 pp |
| V11 | TEMPSCOPE | 2 | 8/10 | 9/10 | +10.00 pp |
| V11 | UNIQUE | 2 | 10/16 | 15/16 | +31.25 pp |
| V12 | AMBIGREF | 3 | 9/15 | 9/15 | +0.00 pp |
| V12 | DENIAL | 3 | 16/24 | 18/24 | +8.33 pp |
| V12 | LOOKALIKE | 3 | 8/18 | 11/18 | +16.67 pp |
| V12 | PRESUP | 3 | 12/18 | 13/18 | +5.56 pp |
| V12 | SETCLOSE | 2 | 9/12 | 9/12 | +0.00 pp |
| V12 | TEMPSCOPE | 3 | 12/15 | 12/15 | +0.00 pp |
| V12 | UNIQUE | 3 | 19/24 | 20/24 | +4.17 pp |
| V13 | AMBIGREF | 5 | 16/25 | 18/25 | +8.00 pp |
| V13 | DENIAL | 8 | 41/64 | 43/64 | +3.12 pp |
| V13 | LOOKALIKE | 13 | 33/78 | 50/78 | +21.79 pp |
| V13 | PRESUP | 9 | 30/51 | 35/51 | +9.80 pp |
| V13 | TEMPSCOPE | 2 | 8/10 | 8/10 | +0.00 pp |
| V13 | UNIQUE | 1 | 6/8 | 7/8 | +12.50 pp |

## V14 旧开发组补充探索

直接矛盾概率、先简短依据再作正反二元判断均只在旧开发组上筛选。最好的 proof_pair 为基础 21/21、挑战 18/21；既有 NLI 为 21/21、17/21。未达到事前挑战至少多对 2 题的扩展标准，按规则停止；没有独立确认或显著性声明。V13 的固定 NLI 确认不因此换方法。

V11–V14 共 2,948 次正式模型响应、1,011,304 tokens（不含人工短文本能力探针）。成本按唯一原始响应去重，探索复用的响应不重复计费。

## 可复现材料

- 方法与逻辑对应：`docs/server_nli_method.md`。
- 可移植请求模板：`experiments/server_summary/recommended_method.json`。
- 原始请求与响应：`outputs/server_v11/records`、`outputs/server_v12/records`、`outputs/server_v13/records`、`outputs/server_v14/records`。
- 固定协议、结果、审计：`experiments/011_server_search`、`experiments/012_server_replication`、`experiments/013_binary_bilingual`、`experiments/014_semantic_binary`。
- 各轮审计脚本：`scripts/audit_server_v11.py`、`scripts/audit_server_v12.py`、`scripts/audit_server_v13.py`、`scripts/audit_server_v14.py`。
- API 端点与密钥读取约定：`docs/qwen38_server_api.md`；报告及缓存不保存密钥。
