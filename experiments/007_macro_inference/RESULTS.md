# 第七轮结果：单次 NLI 判别在新开发组上同时提高两套准确率

2026-10-28。完成 334 次真实 Qwen-27B 非思考响应，共 114,089 token：探索 126 次、盲复核 6 次、确认对照 202 次。所有文件均保存在本仓库，未读取或发送封存测试集。

**当前推荐候选是单次 NLI 判别。** 在预先选定、与历史 pilot/V5 组隔离的 101 道新开发题上，基础集从 56/60 提高到 60/60，挑战集从 26/41 提高到 30/41。14 个分机制/场景组的准确率均未下降，7 组提高、7 组持平。不过挑战集 SUPPORTS、REFUTES 各误伤一题，因此不声称每项指标都严格提高。

## 方法与冻结边界

模型固定为 Groq `qwen/qwen3.8-27b`，显式 `reasoning_effort=none`、temperature=0、seed=42。把 Evidence/Claim 表述为 Premise/Hypothesis，让模型判断 ENTAILMENT / CONTRADICTION / NEUTRAL，再确定性映射为原三分类。

提示词仅定义通用的逻辑后承、矛盾和中立关系，见 [nli_system.txt](../../prompts/v7/nli_system.txt)。没有题目、机制、关键词专用规则，没有 few-shot 样例、训练、SFT、LoRA、外部检索、标签后处理或按题回退。每题一次模型调用。API 输入只有 claim/evidence 和固定模板；gold、group、mechanism、variant 等只用于本地评测。

对照逐字复用 A27 的 A2 模板和 Schema，与 NLI 按样本交错运行。NLI 输出上限 512 token，A27 为原来的 1024；全部正常 stop，无截断。NLI 的简短依据不设字符长度上限，A27 保留历史 reason 上限 320，因此本结果是完整输入/输出协议的比较，不能将收益单独归因于标签名称或某一句提示词。

## 独立开发确认结果

本批 basic 60 题/7 组，challenge 41 题/7 组。清单在查看探索汇总前就已保存于 [planned_confirmation.json](planned_confirmation.json)，实际运行清单与它完全一致。方法选择之后没有使用确认结果调整提示词、样本、标签或决策规则。

| 数据集 | 方法 | 正确/全部 | 准确率 | Macro-F1 | S 召回 | R 召回 | NEI 召回 |
|---|---|---:|---:|---:|---:|---:|---:|
| basic | 同批 A27 | 56/60 | 93.33% | 0.9332 | 94.74% | 94.44% | 91.30% |
| basic | NLI | 60/60 | **100.00%** | **1.0000** | 100.00% | 100.00% | 100.00% |
| challenge | 同批 A27 | 26/41 | 63.41% | 0.6276 | 100.00% | 100.00% | 31.82% |
| challenge | NLI | 30/41 | **73.17%** | **0.7034** | 92.86% | 80.00% | **59.09%** |

- basic：准确率 **+6.67 个百分点**，4 题错→对，0 题对→错；三类召回均提高。
- challenge：准确率 **+9.76 个百分点**，6 题错→对，2 题对→错。6 个改对均为 NEI，2 个误伤分别为 S→NEI、R→NEI。
- challenge 的 R 类只有 5 题，少对 1 题使召回从 100% 变为 80%；S 类为 14 题，少对 1 题使召回降至 92.86%。这两项下降不能省略。
- 缺失、无效响应均按错计；本次没有缺失或无效输出。未修改原 gold，也没有把模型依据当作重新标注。

逐题预测见 [confirm/predictions.csv](confirm/predictions.csv)，完整混淆矩阵、precision/recall/F1、组统计及配对 ID 见 [confirm/metrics.json](confirm/metrics.json)。

| 数据集/机制 | A27 正确 | NLI 正确 | 题数 |
|---|---:|---:|---:|
| basic/BOUND | 15 | 16 | 16 |
| basic/FUNCTIONAL | 3 | 4 | 4 |
| basic/IMPLICATIVE | 10 | 11 | 11 |
| basic/PLACE | 3 | 3 | 3 |
| basic/PLAN | 5 | 5 | 5 |
| basic/RELDATE | 5 | 6 | 6 |
| basic/TIMESHIFT | 15 | 15 | 15 |
| challenge/AMBIGREF | 3 | 3 | 5 |
| challenge/DENIAL | 5 | 7 | 8 |
| challenge/LOOKALIKE | 0 | 0 | 3 |
| challenge/PRESUP | 4 | 4 | 6 |
| challenge/SETCLOSE | 5 | 5 | 6 |
| challenge/TEMPSCOPE | 3 | 4 | 5 |
| challenge/UNIQUE | 6 | 7 | 8 |

这些机制各只有一个完整组，不能把某行的提升外推为该机制已解决。LOOKALIKE 在这批仍为 0/3，是明确的剩余缺口。

## “不显著退步”的解释

用户在确认调用之前补充“不显著退步即可”。调整记录见 [acceptance_amendment.json](acceptance_amendment.json)；原来的零点估计退步门槛仍保留在报告中，没有删掉失败标记。

按完整 group 交换两种方法预测，分别进行 128 种精确配对置换；另做 5,000 次整组 bootstrap。没有把相关变体视为独立样本。

- 两套数据的 accuracy、macro-F1、三类 recall 均未检测到双侧 p<0.05 的下降。
- 准确率改善的双侧配对组检验：basic **p=0.125**，challenge **p=0.25**，也尚未达到 0.05 的显著提升标准。
- 描述性 bootstrap 准确率差区间：basic **[+2.30, +12.50] 个百分点**，challenge **[+2.33, +17.39] 个百分点**。小组数下 bootstrap 与精确检验可能给出不同强度的证据，因此没有只挑选有利的区间来宣称已证明稳定提升。
- challenge R 召回差的区间为 **[-100, 0] 个百分点**；有 88/5,000 次 bootstrap 抽样没有 R 样本，单独记录为未定义。该项尤其缺乏精度。

完整结果见 [confirm/statistical_assessment.json](confirm/statistical_assessment.json)。**本轮达到放宽后的开发候选筛选标准，但未证明非劣效或测试泛化。** 每套仅 7 个组，未检测到下降可能来自检验效能不足。没有事后创造非劣效界值。

## 成本与执行验证

| 同批确认方法 | 调用数 | 输入 token | 输出 token | 总 token |
|---|---:|---:|---:|---:|
| A27 | 101 | 28,371 | 4,621 | 32,992 |
| NLI | 101 | 27,058 | 8,270 | 35,328 |

NLI 总 token 增加 **7.08%**。部署时仅需要 NLI 的一次调用；本轮额外运行 A27 是评测成本。客户端耗时包含免费额度节流且受交错调用次序影响，不据此宣称 NLI 更快。未查询实际账单，不将 token 用量冒充费用。

全部 202 个确认响应通过模型身份、可观察非思考字段、原始输入重建和协议检查，见 [confirm/audit.json](confirm/audit.json)。原始请求与响应保存在 `outputs/macro_v7/confirm/records/`；模型 ID 固定，但托管后端出现 4 个 system fingerprint，seed 不代表逐位确定性。未独立证明服务端内部计算量为零。

相关回归测试 **51 项通过**，覆盖输入隔离、严格解析、缓存完整性、断点保护、免费额度逻辑和按组统计。原数据、封存测试集和历史实验文件未改动。

## 探索过程与未采用方案

历史 42 题只用于探索，不作为独立验证。完整负结果保留在 [scout/RESULTS.md](scout/RESULTS.md)：NLI 的 challenge 为 17/21、basic 为 20/21；dual 为 17/21、19/21；certificate 为 14/21、21/21。三个两两共识均未通过初始严格门槛。

在 6 个分歧上追加盲阅读理解复核后，结果回到 A27 的 challenge 14/21、basic 21/21，增加 2,556 token 而无收益，见 [review_scout/metrics.json](review_scout/metrics.json)。

另准备了可复现的输入重复变换，依据 [Prompt Repetition Improves Non-Reasoning LLMs](https://arxiv.org/abs/2512.14982)，本次仅验证变换保持原始输入与基线系统指令，**没有运行模型实验、没有效果结论**。NLI 确认结束后已得到两套准确率提升，因此没有继续消耗额度来筛选更多方法。

当前可采用 NLI 作为下一轮候选，重点在新的开发组上确认稀少的 R 类与剩余错误机制。测试集继续封存；本报告所有分数均为开发集成绩。
