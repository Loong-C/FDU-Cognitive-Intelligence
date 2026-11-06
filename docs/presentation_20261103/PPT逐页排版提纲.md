# 五分钟汇报逐页提纲

[最终版 PDF](Adversarial_Fact_Verification_Revised.pdf) 共 17 页，英文展示，另有 2 分钟问答。提示词页讲清改动，例题页演示判断过程。

| 页 | 英文标题 | 主要内容与位置 | 时间 |
| --- | --- | --- | ---: |
| 1 | Adversarial Fact Verification | 左对齐标题、Team B / Group 2 及三位组员姓名 | 5 秒 |
| 2 | Evidence Verification and the Baseline | 左侧任务与标签；右侧 baseline user 提示词节选 | 20 秒 |
| 3 | Basic Skills and Adversarial Challenges | 基础集、挑战集及使用范围对照表 | 10 秒 |
| 4 | Seven Traps in Evidence-Based Reasoning | 七类机制表；旁侧真实 UNIQUE 原题 | 15 秒 |
| 5 | Natural Language Inference | 前提—假设关系与三分类映射示意 | 15 秒 |
| 6 | NLI: System Prompt | 左侧 baseline system 与共用 user 说明；右侧完整 NLI system | 20 秒 |
| 7 | NLI: Award Attribution | 左侧原题；右侧对命题及其否定分别作蕴含判断 | 20 秒 |
| 8 | PJ Rule-Based Prompting | 左侧三步检查；右侧机制规则摘要 | 20 秒 |
| 9 | PJ: Checks Added to the System Prompt | 通栏展示 PJ 三步检查及 NEI 条件的原文节选 | 25 秒 |
| 10 | PJ: A Source's Dismissal of a Report | 左侧 DENIAL 原题；右侧矛盾、额外假设、共存情形的推演 | 25 秒 |
| 11 | LoRA Fine-Tuning | 参数更新示意、三次独立训练及 728 条审核后样本的监督格式 | 25 秒 |
| 12 | A Unified Comparison Protocol | 左侧受控条件及集中后的调用、微调说明；右侧数据划分 | 20 秒 |
| 13 | LoRA Achieves the Highest Challenge Accuracy | 基础、挑战准确率图与结论 | 20 秒 |
| 14 | Improvements on Difficult NEI Subtypes | 七类难例正确题数与三次训练的结果范围 | 15 秒 |
| 15 | Where Do the Errors Go? | baseline、PJ、LoRA 三个并列混淆矩阵及 REFUTES 回退 | 20 秒 |
| 16 | Distillation Does Not Exceed Original LoRA | NLI/PJ/联合解释蒸馏结果图；比较条件限制 | 15 秒 |
| 17 | What We Need to Validate Next | 后续验证方向表 | 10 秒 |

第 4、7 页使用开发题 `e_51c3569118fd293c`，第 10 页使用 `e_b30e3a12162be36f`。题文、标准标签及预测见[原题记录](slide_examples.json)。第 14 页是对 22 道 NEI 难例的事后分析。第 15 页的百分比按真实类别计算，包含无效输出，LoRA 取三个种子的均值。第 16 页的蒸馏结果来自同一批历史开发题，解释时需要考虑检查点选择方式的差异。
