# 第四轮：GroqCloud 27B 双世界对照实验

运行 `pilot_groq_qwen38_27b_nonthink_v4_r1`；基线 `codex/14b-nonthink-v3` / `a99a5d8`。

**状态：未完成，正式模型回答 0/294。** 技术门槛：{"technical": false, "smoke": false, "integration": false}。

复用第三轮冻结开发集：challenge 87题/14完整组，basic 60题/7完整组；同序ID及manifest哈希已核对。仅输入claim/evidence及原版A2/B2提示词；无C2示例、无test推理、无训练。

## 接口、配额与真实执行

请求固定模型 `qwen/qwen3.8-27b`，`reasoning_effort=none`、temperature=0、seed=42、stream=false、max_completion_tokens=1024；严格JSON Schema保留maxLength=320。API接受seed也不代表逐位确定性，是否实际生效不可独立证明。

已记录HTTP状态：`{"403": 1}`。已收到的usage记录合计token=0；保守预留/实际记账=1831。没有usage记录时实际用量未知；预留token不是服务端用量或账单。

用户已确认Free Plan。参考上限30 RPM、8000 TPM、1000 RPD、200000 TPD；本地采用25 RPM、7000 TPM、800次/滚动24h、180000 token/滚动24h。服务端响应头只显示RPD/TPM，不能证明免费套餐或剩余TPD；没有升级套餐、没有换模型、没有授权收费请求。

当HTTP 401/403/400出现时立即停止；429尊重Retry-After和reset，超过60秒则保存暂停；网络/5xx有限重试。预算在发请求前原子预留，成功后使用usage结算。单并发锁、逐题原子文件、固定指纹；未知中断留下inflight标记，禁止自动重复生成。

## 两组结果

所有完整实验统计按全部应测样本计分，无效/截断计错。未完成时不公布完整准确率；metrics.json另列已完成数量和严格完成下界，缺失项不能当作真实模型失败。

### challenge

| 模型/方法 | 正确/应测 | 准确率 | 宏F1 | S召回 | R召回 | NEI召回 | NEI→R | S→NEI | R→NEI |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A4 | 50/87 | 57.47% | 0.549 | 87.88% | 85.71% | 22.50% | 27 | 2 | 1 |
| B4 | 55/87 | 63.22% | 0.598 | 63.64% | 42.86% | 70.00% | 5 | 12 | 4 |
| A14 | 53/87 | 60.92% | 0.579 | 93.94% | 92.86% | 22.50% | 28 | 1 | 0 |
| B14 | 69/87 | 79.31% | 0.774 | 87.88% | 85.71% | 70.00% | 10 | 4 | 0 |
| A27 | 未完成（0/87已返回） | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| B27 | 未完成（0/87已返回） | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

### basic

| 模型/方法 | 正确/应测 | 准确率 | 宏F1 | S召回 | R召回 | NEI召回 | NEI→R | S→NEI | R→NEI |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A4 | 42/60 | 70.00% | 0.692 | 92.86% | 82.61% | 43.48% | 8 | 0 | 1 |
| B4 | 34/60 | 56.67% | 0.551 | 64.29% | 17.39% | 91.30% | 0 | 5 | 17 |
| A14 | 46/60 | 76.67% | 0.765 | 100.00% | 78.26% | 60.87% | 4 | 0 | 2 |
| B14 | 48/60 | 80.00% | 0.810 | 92.86% | 60.87% | 91.30% | 0 | 1 | 9 |
| A27 | 未完成（0/60已返回） | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| B27 | 未完成（0/60已返回） | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

## 验收问题与证据边界

1. **真正关闭thinking？** 请求显式none；只有成功返回后才能检查reasoning字段/think标记及reasoning_tokens。未收到回答时无法实测确认。缺少reasoning token字段仅表示未暴露，不能证明内部实现。
2. **结构化输出稳定？** 必须先通过无约束NOT_JSON对照、A/B独立Schema枚举哨兵、400字符对照与320上限约束，再通过6次独立虚构smoke。HTTP 200或合法JSON不足以通过。门槛结果见execution_audit.json；尚未通过不得宣称稳定。
3. **正确数、NEI提升与S/R误伤？** 完整结果见上表；未完成时无法回答。不得用历史14B数字代替27B结果。
4. **非法反例是否减少？** 预指定Salem、2026、124999/125000、only one的逐题对照见typical_errors.csv。固定18条语义复核见reason_consistency_review.csv；尚无27B输出的条目明确not_run。不能根据gold自动归因或修复。
5. **成本及免费额度？** costs.json按数据/方法记录真实usage和请求耗时，api_diagnostics.json另列技术请求和失败预算预留。未返回usage的请求，实际token与账单均未知；不能写成已验证零费用。
6. **与A组Q8_0严格比较还缺什么？** 需要相同模型版本/权重来源与可核对量化、相同数据顺序/提示词/Schema/解码预算/非思考设置，以及独立确认的运行环境和完整逐题记录。Groq不公开权重SHA、tokenizer/chat template及硬件，不能宣称与本地Q8_0严格受控等价。

4B/14B/27B属于不同模型代际、量化与后端；历史比较仅描述，不把差异归因于参数规模。14/7个group内样本相关，不假设逐题独立或宣称统计显著。basic冻结gold仍为pending审核，本轮不修改历史数据。

本地模型SHA、GPU卸载、DLL、/apply-template与精确预分词指标均N/A。API接受的请求参数、返回模型ID、服务端fingerprint和usage才是远程证据。

## 官方资料

[模型](https://console.groq.com/docs/model/qwen/qwen3.8-27b)、[API参数](https://console.groq.com/docs/api-reference)、[JSON Schema](https://console.groq.com/docs/structured-outputs)、[限速与响应头](https://console.groq.com/docs/rate-limits)。查询于2026-10-23，真实探针结果优先。
