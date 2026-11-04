# PPT 逐页排版提纲

更新日期：2026-11-03。用途：按“第几页、什么位置、放什么内容”制作 PPT。

已按此提纲生成英文 [Beamer PDF](F:/Personal/Code/A_B/docs/presentation_20261103/Adversarial_Fact_Verification_Beamer.pdf)，包含 15 页正文和 5 页答辩备份；[LaTeX 源文件](F:/Personal/Code/A_B/docs/presentation_20261103/beamer/adversarial_fact_verification.tex)保留在仓库内。

正文 15 页，答辩备份 5 页；保留“问题引入 → 问题难点 → 解决思路 → 实验结果 → 未来方向”结构。基线、NLI、PJ、LoRA 各自一页，融合另占一页。正文约 5 分钟，提问约 2 分钟。本文件是制作说明，尚未生成 PPT。

**本次修订：第 13 页改用三个并排混淆矩阵，第 20 页新增完整矩阵备份；正文页数和时间不变。所有上屏内容使用英语，中文仅用于制作说明；具体示例均来自开发原题。**

## 一、全局排版约定

- 使用 16:9 横版，左右各留约 6% 空白。标题约 32–36 pt，封面约 42 pt，正文约 22–26 pt，图表标签尽量不低于 18 pt。
- 白色背景、深蓝标题；SUPPORTS 用绿色，REFUTES 用红色，NOT ENOUGH INFO 用蓝色。同一方法在各结果图中保持同一种颜色。
- **只复制“Slide content (English)”列、明确标注的英文内容块和英文数据表到 PPT。** 中文页序分类、位置、制作说明、讲述重点、来源均不直接上屏；如写入 PPT 演讲者备注，也需译成英语。
- 图中的标题、节点、图例、坐标、表头、脚注以及代码占位符全部使用英语，不添加中文对照。三张现成结果图也已改为英语。
- 流程图用可编辑形状与箭头，数据表用可编辑表格。代码样式仅展示提示词节选或监督格式，不展示终端日志、服务器地址或凭据。
- 所有具体题目示例来自已用于 V17 比较的开发题快照。Evidence 摘录逐字保留原文，并标为 `Evidence excerpt`；Claim 保留完整原文。标签与预测使用冻结记录，不重新生成。
- 题目包含人工构造的人物与事件，引用题目不等于主张这些事件在现实中发生。示例页统一使用英文脚注：`Benchmark text; not a real-world factual claim.`
- 数据标清分母和比较范围。`pp` 表示百分点；种子标准差不是泛化置信区间。正文 300 秒；备份页只用于提问。

## 二、页序总表

本表是制作索引，其中“部分”和“核心素材”不直接上屏；英文标题可直接使用。

| 页码 | 部分 | English slide title | 核心素材 | 时间 |
|---|---|---|---|---:|
| 1 | 问题引入 | Adversarial Fact Verification | 标题与副标题 | 5 秒 |
| 2 | 问题引入 | What Does the Evidence Establish? | 任务图、真实 DENIAL 对照题 | 20 秒 |
| 3 | 问题引入 | Basic Skills and Adversarial Challenges | 数据对照表 | 15 秒 |
| 4 | 问题难点 | Seven Traps in Evidence-Based Reasoning | 机制表、真实 UNIQUE 题 | 20 秒 |
| 5 | 解决思路 | Route 1: Direct Classification | 基线流程、原提示词节选 | 15 秒 |
| 6 | 解决思路 | Route 2: Natural Language Inference | 前提与假设、三类映射 | 20 秒 |
| 7 | 解决思路 | Route 3: PJ Rule-Based Prompting | 三步检查、规则摘要 | 25 秒 |
| 8 | 解决思路 | Route 4: LoRA Fine-Tuning | 参数更新与训练数据流 | 35 秒 |
| 9 | 解决思路 | Can Prompting and Fine-Tuning Work Together? | 三条融合流程 | 20 秒 |
| 10 | 实验结果 | A Unified Comparison Protocol | 控制条件、数据划分 | 15 秒 |
| 11 | 实验结果 | LoRA Achieves the Highest Challenge Accuracy | 基础与挑战准确率图 | 25 秒 |
| 12 | 实验结果 | Improvements on Difficult NEI Subtypes | 同题正确数表 | 25 秒 |
| 13 | 实验结果 | Where Do the Errors Go? | Baseline、PJ、LoRA 混淆矩阵 | 20 秒 |
| 14 | 实验结果 | Distillation Does Not Exceed Original LoRA | 蒸馏结果图、完成范围 | 15 秒 |
| 15 | 未来方向 | What We Need to Validate Next | 问题与行动对应 | 25 秒 |
| 16 | 答辩备份 | Lessons from Earlier Attempts | 失败过程与发现 | 提问时使用 |
| 17 | 答辩备份 | Zero on a Subtype Is Not Zero Overall | 分母与统计口径 | 提问时使用 |
| 18 | 答辩备份 | Difficult Subtypes: Results by Seed | 完整正确数表 | 提问时使用 |
| 19 | 答辩备份 | Limitations and Open Questions | 限制与短答 | 提问时使用 |
| 20 | 答辩备份 | Confusion Matrices: NLI and Individual LoRA Seeds | NLI 与各 LoRA 种子的完整矩阵 | 提问时使用 |

## 三、逐页制作说明

### 第 1 页｜Adversarial Fact Verification

**归属：问题引入。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 中部偏上，约 80% 宽 | 文字，主标题 | **Adversarial Fact Verification** |
| 主标题下方 | 文字，副标题 | Prompting and Fine-Tuning for Evidence-Based Classification |
| 左下角 | 文字 | Team B · Course Project Presentation |
| 右下角 | 文字，制作时替换为真实姓名和日期 | [Team members] · [Presentation date] |

**讲述重点：**介绍研究对象：模型能否严格依据证据作出三分类判断，以及怎样改善对抗表达上的错误。

**制作说明：**姓名使用实际英文名或拼音；日期使用英文格式。封面不堆结果与目录。

### 第 2 页｜What Does the Evidence Establish?

**归属：问题引入。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | What Does the Evidence Establish? |
| 主体上方 | 任务流程图 | Evidence + Claim → Model → SUPPORTS / REFUTES / NOT ENOUGH INFO |
| 流程图下方 | 文字，三类定义 | SUPPORTS: entailed · REFUTES: contradicted · NOT ENOUGH INFO: neither |
| 主体中部 | 文字，两题共用的完整陈述 | **Claim:** Akira Toriyama secretly donated five million yen to a local orphanage in Fukuoka. |
| 主体左下，约 42% 宽 | 原题证据摘录，蓝色标签 | **Evidence excerpt:** His longtime editor at Shueisha dismissed as baseless the reports that Akira Toriyama had secretly donated five million yen to a local orphanage in Fukuoka.<br>**Gold label: NOT ENOUGH INFO** |
| 主体右下，约 42% 宽 | 同组对照题证据摘录，红色标签 | **Evidence excerpt:** Reports that Akira Toriyama had secretly donated five million yen to a local orphanage in Fukuoka were later shown to be false.<br>**Gold label: REFUTES** |
| 底部 | 文字，关键句 | **Lack of support is not evidence of falsity.** |
| 最下方 | 英文脚注 | Benchmark text; not a real-world factual claim. Evidence excerpts from two items in the same scenario group. |

**讲述重点：**同一个陈述，有人把报道斥为无稽之谈，只能说明其态度；证据直接说报道被证实为假，才能据此反驳。标签是证据与陈述之间的关系。

**制作说明：**突出 `dismissed as baseless` 与 `shown to be false`，不把整段背景塞进 PPT。两题均为真实开发题，长背景未展示，因此必须保留 `Evidence excerpt`。此页只展示冻结标签，不展示或杜撰模型回答。

**原题来源：**[开发题快照](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/016_finetune_27b/revision_2/holdout.jsonl)。左题 ID `e_b30e3a12162be36f`，`DENIAL / baseless`；右题 ID `e_072e61b1f738c059`，`DENIAL / shown_false`；同属 `g_8610864a2344d7ec`。摘录与完整 Claim 已逐字核对。

### 第 3 页｜Basic Skills and Adversarial Challenges

**归属：问题引入。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Basic Skills and Adversarial Challenges |
| 中央，约 85% 宽 | 表格，复制下方英文表 | — |
| 表格下方 | 双向箭头示意图 | Improve challenge performance ↔ Preserve basic accuracy |
| 底部 | 文字 | **Evaluate the two datasets separately.** |

下表为上屏内容：

| Dataset | Original size | Content | Purpose |
|---|---:|---|---|
| Basic | 900 items | Numbers, dates, locations, plans and facts | Check for loss of basic ability |
| Challenge | 885 items | Seven adversarial reasoning mechanisms | Detect unsupported inferences |

**讲述重点：**A 组提供数据，B 组负责评估和优化。两套数据分别评估，避免只提高信息不足预测比例却损害基础判断。

**来源：**[数据说明](F:/Personal/Code/A_B/data/raw/benchmark_1011/数据说明.md)。这里的数字是原始规模，不是第 11 页成绩的分母。

### 第 4 页｜Seven Traps in Evidence-Based Reasoning

**归属：问题难点。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Seven Traps in Evidence-Based Reasoning |
| 主体左侧，约 52% 宽 | 表格，复制下方机制表 | — |
| 主体右侧，约 36% 宽 | 原题卡片，复制下方英文内容块 | — |
| 题目卡片下方 | 错误推断示意图；中间假设标红，整条路径划叉 | Olivia won → Assume only one winner → Daisy did not win |
| 底部 | 文字，关键句 | **Do not invent identity, exclusivity, time, or scope constraints.** |
| 最下方 | 英文脚注 | Benchmark text; not a real-world factual claim. |

机制表为上屏内容；这些是机制摘要，不是新增题目：

| Mechanism | Key distinction |
|---|---|
| DENIAL | A denial is not a disproof. |
| LOOKALIKE | Facts about one person do not transfer to another. |
| UNIQUE | One person's success does not exclude another's. |
| PRESUP | An earlier event need not be in an earlier calendar year. |
| TEMPSCOPE | A first term does not cover all terms. |
| SETCLOSE | A complete subset is not the complete set. |
| AMBIGREF | A pronoun about another person does not refute the subject's claim. |

右侧原题内容块：

```text
Evidence excerpt:
In 2024, Olivia Edgar-Jones won a regional theater award for best supporting actress.

Claim:
Daisy Edgar-Jones won a regional theater award for best supporting actress in 2024.

Gold label: NOT ENOUGH INFO
```

**讲述重点：**证据说 Olivia 获奖，并没有说 Daisy 没获奖。把“获奖者只有一人”补进去，才会得到错误的反驳结论。正文口述 DENIAL、UNIQUE、范围三个代表，不逐行念七类。

**制作说明：**示意图中的 `Assume only one winner` 是我们对错误推断的概念说明，不是证据原文，也不是模型推理日志。真实题目和标签放在题目卡片内，两者明确分开。

**原题来源：**[开发题快照](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/016_finetune_27b/revision_2/holdout.jsonl)，ID `e_51c3569118fd293c`，`UNIQUE / other_indef|indef`，组 `g_3574de4786a85e19`。原题另一句交代 Daisy 与 Olivia 的关系及毕业经历；这里逐字摘录获奖句，未改人物、年份或奖项。

### 第 5 页｜Route 1: Direct Classification

**归属：解决思路。四条路线之一，单独一页。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Route 1: Direct Classification |
| 主体左侧，约 47% 宽 | 单次推理流程图 | Original prompt + Evidence + Claim → 27B model → Brief rationale + Verdict |
| 流程图旁 | 文字 | One model call · No weight updates |
| 主体右侧，约 39% 宽 | 代码样式文本，复制下方原提示词节选 | — |
| 底部 | 文字 | **Establish a reference point and identify existing errors.** |

提示词节选为上屏内容；为原文中连续的末段，不是改写：

```text
Judge the claim ONLY against the evidence below; do not use outside knowledge.

EVIDENCE:
{evidence}

CLAIM: {claim}

Give a brief justification, then finish with a final line of exactly this form:
Verdict: <SUPPORTS | REFUTES | NOT ENOUGH INFO>
```

**讲述重点：**基线已有三分类定义和仅依据证据的要求；优化针对模型执行这些要求时的错误。

**制作说明：**长行仅视觉换行，不改原文。`{evidence}` 与 `{claim}` 是真实提示模板占位符，不是具体题目示例。

**来源：**[原始提示词](F:/Personal/Code/A_B/prompts/v1/A0_user.txt)。

### 第 6 页｜Route 2: Natural Language Inference

**归属：解决思路。四条路线之一，单独一页。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Route 2: Natural Language Inference |
| 主体左侧，约 45% 宽 | 前提与假设示意图 | Evidence = Premise<br>Claim = Hypothesis<br>Does the premise entail the hypothesis or its negation? |
| 主体右侧，约 41% 宽 | 代码样式文本，复制下方概念映射 | — |
| 主体下方 | 文字，核心规则 | **The evidence is all available information, not a complete description of the world.** |
| 底部 | 文字 | One model call · No weight updates · Same rationale-and-verdict output |

概念映射为上屏内容：

```text
ENTAILMENT    → SUPPORTS
CONTRADICTION → REFUTES
NEUTRAL       → NOT ENOUGH INFO
```

**讲述重点：**回扣第 4 页同一原题：Olivia 获奖不能推出 Daisy 获奖，也不能推出 Daisy 没获奖，因此属于 NEUTRAL。这里不新增自拟例子。

**制作说明：**这是逻辑关系映射，不是实际输出代码。V17 已统一理由与 Verdict 输出，不混入早期 JSON 协议；基线也有逻辑定义，不说只有 NLI 才引入了逻辑。

**来源：**[统一比较提示词](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/017_unified_comparison/prompts.json)。

### 第 7 页｜Route 3: PJ Rule-Based Prompting

**归属：解决思路。四条路线之一，单独一页。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Route 3: PJ Rule-Based Prompting |
| 主体左侧，约 46% 宽 | 三步检查流程 | Locate contradictory evidence → Check unstated assumptions → Check whether evidence and claim can both hold |
| 主体右侧，约 40% 宽 | 文字，规则摘要 | A denial is not a disproof.<br>Do not assume identity or exclusivity.<br>Preserve the stated time and set boundaries. |
| 主体下方 | 文字，平衡要求 | **Do not add unstated constraints or remove explicit ones.** |
| 底部 | 文字 | One shared prompt · No mechanism labels in the input · One model call |

**讲述重点：**这条路线已经针对挑战机制加入规则；在反驳之前，要求模型检查自己是否暗中添加前提。所有题使用同一套规则，不按已知机制给模型泄露答案。

**制作说明：**上屏是英文摘要，不冒充冻结提示词的逐字引用。这些步骤是推理要求，不是程序证明器；PRESUP 的专项覆盖仍较间接，不说七类机制全部解决。

**来源：**[PJ 冻结提示词](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/017_unified_comparison/prompts.json)中的 `pj_v3.system`。

### 第 8 页｜Route 4: LoRA Fine-Tuning

**归属：解决思路。四条路线之一，单独一页。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Route 4: LoRA Fine-Tuning |
| 主体左侧，约 44% 宽 | 大矩形与小矩形；只突出小矩形的参数更新 | Frozen 27B backbone + Trainable LoRA adapters |
| 模型框上方 | 输入箭头 | Original prompt + Evidence + Claim |
| 主体右侧，约 42% 宽 | 数据处理流程 | 902 candidate items → AI-assisted item review → Remove 174 items by group → 728 training items |
| 主体下方左侧 | 代码样式文本，复制下方监督格式 | — |
| 主体下方右侧 | 文字，训练设置 | Seeds: 42 / 43 / 44<br>LoRA rank: 8<br>Update adapter parameters only |
| 底部 | 文字 | **Keep the original prompt; learn from reviewed rationales and labels.** |

监督格式为上屏内容；这是格式示意，不是新增题目或模型原始输出：

```text
[Reviewed brief rationale]
Verdict: [Gold label]
```

**讲述重点：**提示路线改变提问方式；LoRA 保留原始提示，利用经过审核的理由和标签进行监督训练。三个种子用于观察训练波动。

**制作说明：**训练理由是 AI 辅助审核，不标成人工专家金标。冻结主干仍需加载主干，模型最终行为仍会因适配参数改变。

**来源：**[V16 训练协议](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/016_finetune_27b/revision_2/PROTOCOL.md)、[训练数据审核](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/016_finetune_27b/revision_2/TRAINING_DATA.md)。

### 第 9 页｜Can Prompting and Fine-Tuning Work Together?

**归属：解决思路。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Can Prompting and Fine-Tuning Work Together? |
| 主体上排 | 提示组合流程 | **Prompt combination:** LoRA model + NLI / PJ prompt → Final answer |
| 主体中排 | 分歧复核流程，画成分支 | **Disagreement review:** Initial answers → All valid and unanimous? → Yes: return answer / No: one review |
| 主体下排 | 解释蒸馏流程 | **Rationale distillation:** NLI / PJ / Joint rationales → Item review → New LoRA → One model call |
| 底部 | 文字，研究问题 | **Can the gains from prompting and fine-tuning accumulate?** |

**讲述重点：**分别在推理时组合、分歧时复核、训练时利用解释三个位置尝试融合。

**制作说明：**三条路线阅读方向一致；解释来源是不同提示路线，不是更大的教师模型。此页只讲设计，完成范围及结果放第 14 页。

**来源：**[V18 实验设计](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/018_fusion/README.md)。

### 第 10 页｜A Unified Comparison Protocol

**归属：实验结果。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | A Unified Comparison Protocol |
| 主体左侧，约 47% 宽 | 控制条件列表 | Same BF16 27B backbone<br>Thinking disabled; greedy decoding<br>Same output format; 1,024-token generation limit<br>Compare every method on the same items |
| 主体右侧，约 39% 宽 | 三行数据用途图 | Train: 728 items → Learn parameters<br>Validation: 259 items → Select checkpoints<br>Development comparison: 261 items → Report results |
| 主体下方 | 文字 | Comparison set: 120 basic + 141 challenge items<br>Evaluate all three seeds; no voting or best-seed selection |
| 底部 | 文字，必要边界 | **Scenario groups are separated. Previously used development data; not an independent blind test. Invalid outputs count as errors.** |

**讲述重点：**统一模型、题目和生成口径后比较，避免把不同条件下的成绩直接排列。

**制作说明：**数据划分图表示用途，不画验证题直接流向训练参数；token 数是生成上限，不是实际成本。历史开发数据暴露的限制不能省略。

**来源：**[V17 比较协议](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/017_unified_comparison/README.md)。

### 第 11 页｜LoRA Achieves the Highest Challenge Accuracy

**归属：实验结果。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字；整图插入时使用图内标题 | LoRA Achieves the Highest Challenge Accuracy |
| 主体左半 | 柱状图 | Basic accuracy · 120 items |
| 主体右半 | 柱状图，突出 PJ 与 LoRA | Challenge accuracy · 141 items |
| 底部 | 文字 | PJ: +13.48 pp on challenge.<br>LoRA: +25.77 pp on challenge; −0.28 pp on basic. |
| 图内脚注 | 整图自带；重做图时也保留 | V17: Same BF16 27B backbone, items and generation protocol. LoRA: mean ± sample SD across three seeds.<br>Previously used development data; not an independent blind test. Invalid outputs count as errors. |

可直接使用英文[主结果图 PNG](F:/Personal/Code/A_B/docs/presentation_20261103/01_unified_accuracy.png)，也提供同名 SVG。需要可编辑表格时使用下表，不必与图重复摆放：

| Method | Basic accuracy | Challenge accuracy |
|---|---:|---:|
| Baseline | 96.67% | 71.63% |
| NLI | 95.83% | 74.47% |
| PJ rules | 96.67% | 85.11% |
| LoRA, three-seed mean | 96.39% ± 0.48 pp | 97.40% ± 1.48 pp |

**讲述重点：**规则提示和 LoRA 均观察到挑战准确率提升，LoRA 均值最高。

**制作说明：**整图自带标题与脚注，不重复叠加。重做原生图时纵轴从 0 起；误差线为种子样本标准差。均值提升使用未四舍五入的数据计算。

**来源：**[V17 结果与限制](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/017_unified_comparison/ASSESSMENT.md)。

### 第 12 页｜Improvements on Difficult NEI Subtypes

**归属：实验结果。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Improvements on Difficult NEI Subtypes |
| 中央，约 88% 宽 | 表格，复制下方七行表；突出指代、首次任期、baseless 三行 | — |
| 表格下方 | 文字，关键发现 | **Several zero-correct baseline subtypes improve; LoRA gains are broader but vary by seed.** |
| 底部 | 英文脚注 | Selected NEI subtypes only: 22 items. Post-hoc diagnosis, not an overall score or an independent significance claim. LoRA ranges show correct counts across three seeds. |

上屏表格：

| NEI subtype | Baseline | NLI | PJ | LoRA range |
|---|---:|---:|---:|---:|
| A relative wins; claim concerns the subject | 0/5 | 0/5 | 1/5 | 4–5/5 |
| Pronoun refers to another person | 0/3 | 0/3 | 2/3 | 3/3 |
| Another person succeeds; claim concerns the subject | 0/2 | 1/2 | 1/2 | 2/2 |
| A subset list is treated as complete | 1/2 | 1/2 | 2/2 | 1–2/2 |
| An award this year; claim concerns an earlier year | 0/3 | 0/3 | 2/3 | 1–3/3 |
| Service after the first term | 1/3 | 1/3 | 1/3 | 3/3 |
| Reports dismissed as baseless | 0/4 | 1/4 | 4/4 | 4/4 |

**讲述重点：**这些是在我们同一批开发题中重新统计的难例子类型，多个原本全错的类型得到改善。第 2 页左题属于本表最后一行，第 4 页题目属于第三行；无需再编例子。

**制作说明：**范围是三个种子的最少至最多正确数，不是置信区间；完整明细在第 18 页。不能把 A 组的局部 0% 与我们的整体 97.40% 直接相减，也不能把 22 题当成全挑战集。

**来源：**[V17 逐题预测](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/017_unified_comparison/results/predictions.csv)与[开发题变体字段](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/016_finetune_27b/revision_2/holdout.jsonl)。

### 第 13 页｜Where Do the Errors Go?

**归属：实验结果。用混淆矩阵替换原类别召回柱状图，仍讲 20 秒。** 第 11 页回答整体提升多少，第 12 页回答哪些机制改善，本页回答错误去了哪里。

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Where Do the Errors Go? |
| 标题下方 | 文字，数据范围 | V17 challenge development set · 141 items |
| 主体左侧，约 28% 宽 | 3×4 混淆矩阵；单元格用下方 Baseline 百分比 | Baseline |
| 主体中央，约 28% 宽 | 3×4 混淆矩阵；单元格用下方 PJ 百分比 | PJ rules |
| 主体右侧，约 28% 宽 | 3×4 混淆矩阵；单元格用下方 LoRA 百分比 | LoRA · Mean of 3 seeds |
| 各矩阵左侧与下方 | 轴标题；三张图共享相同顺序 | True label<br>Predicted label |
| 各矩阵行标签 | 按顺序标注真实类别及各行分母 | SUPPORTS (n=54)<br>REFUTES (n=19)<br>NEI (n=68) |
| 各矩阵列标签 | 按顺序标注预测类别；必须保留第四列 | SUPPORTS / REFUTES / NEI / Invalid |
| 主体下方 | 共用色条 | Percentage within each true class · 0–100% |
| 底部左侧 | 文字，突出主要错误变化 | **NEI → REFUTES: 58.82% → 23.53% → 2.45%** |
| 底部右侧 | 文字，保留优化代价 | **REFUTES recall: 100% → 100% → 89.47%** |
| 最下方 | 英文脚注 | Rows normalized by true class. LoRA: mean of seeds 42, 43 and 44; no voting. Invalid outputs remain in the denominator.<br>NEI = NOT ENOUGH INFO. Previously used development data; frozen labels; not an independent blind test. |

下列三个表是矩阵的精确制图输入，数字为各真实类别内的百分比；上屏时做成热力图，不把三张表再重复放在旁边。

**Baseline：**

| True label | SUPPORTS | REFUTES | NEI | Invalid |
|---|---:|---:|---:|---:|
| SUPPORTS | 100.00% | 0.00% | 0.00% | 0.00% |
| REFUTES | 0.00% | 100.00% | 0.00% | 0.00% |
| NEI | 0.00% | 58.82% | 41.18% | 0.00% |

**PJ rules：**

| True label | SUPPORTS | REFUTES | NEI | Invalid |
|---|---:|---:|---:|---:|
| SUPPORTS | 98.15% | 0.00% | 1.85% | 0.00% |
| REFUTES | 0.00% | 100.00% | 0.00% | 0.00% |
| NEI | 0.00% | 23.53% | 70.59% | 5.88% |

**LoRA · Mean of 3 seeds：**

| True label | SUPPORTS | REFUTES | NEI | Invalid |
|---|---:|---:|---:|---:|
| SUPPORTS | 100.00% | 0.00% | 0.00% | 0.00% |
| REFUTES | 1.75% | 89.47% | 8.77% | 0.00% |
| NEI | 0.00% | 2.45% | 97.55% | 0.00% |

**讲述重点：**“基线把 68 道信息不足题中的 40 道判成反驳。PJ 将这种错误降到 16 道，LoRA 三个种子分别为 1、0、4 道；但 LoRA 每个种子又错了 2 道反驳题。”只指向 NEI→REFUTES 格及 LoRA 的 REFUTES 行，不逐格讲解。LoRA 的反驳错误还包括判成 SUPPORTS 的情况，不能全部描述成判为 NEI。

可直接使用的英文讲述句（如写入 PPT 备注，也使用本段）：

```text
The baseline misclassifies 40 of 68 NEI items as REFUTES.
PJ reduces this to 16; LoRA makes 1, 0 and 4 such errors across three seeds.
However, every LoRA seed also misses 2 of the 19 REFUTES items.
```

**制作说明：**

- 三张矩阵统一使用一种连续色阶，例如浅蓝到深蓝，固定 0–100%；颜色表示比例，不表示方法或类别。每格直接标百分比，保留两位小数；0% 可统一简写。
- 横轴始终是预测标签，纵轴始终是真实标签。三张图的类别、顺序、大小、色阶一致；可共享纵轴标签，避免文字拥挤。
- 用同色细框突出三个 `True NEI / Predicted REFUTES` 单元格；LoRA 的 REFUTES 行另加细框，提示新增错误。不要只框对角线上的高分。
- 每行比例的分母分别为 54、19、68，包含无效输出。`Invalid` 是输出无效的统计列，不是新增真实类别。PJ 的 4 条无效输出均来自 NEI 行，不能删除后重新归一化。
- LoRA 先对每个种子的矩阵逐行归一化，再对三个对应格取算术平均；这是三个训练运行的平均比例，不是选最高种子、投票结果或 423 道独立题。四舍五入后行和可能为 99.99%。
- 本页仍保留原结论：LoRA 的 REFUTES 召回下降 10.53 pp，超过预设 5 pp 限制；V17 中 PJ 是唯一通过全部预设门槛的候选。这一解释放讲述或提问环节，不再堆一整段文字到主图下。

**素材状态：**已绘制英文[混淆矩阵矢量图](F:/Personal/Code/A_B/docs/presentation_20261103/beamer/assets/confusion_main.pdf)，已用于 Beamer PDF 第 13 页；原[类别召回图](F:/Personal/Code/A_B/docs/presentation_20261103/02_recall_tradeoff.png)保留为备用素材。

**来源：**[V17 逐题预测](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/017_unified_comparison/results/predictions.csv)、[V17 结果与限制](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/017_unified_comparison/ASSESSMENT.md)。

### 第 14 页｜Distillation Does Not Exceed Original LoRA

**归属：实验结果。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字；整图插入时使用图内标题 | Distillation Does Not Exceed Original LoRA |
| 主体中央 | 柱状图 | Original LoRA: 97.40%<br>NLI rationales: 95.74%<br>PJ rationales: 95.27%<br>Joint rationales: 96.93% |
| 主体下方 | 文字，完成范围 | V18 quick scope completed: 9 training runs, 35 validation configurations, 13 development comparison configurations. |
| 底部 | 文字，必要边界 | No statistically significant decline after correction. The full experiment still has deferred components. |
| 图内脚注 | 整图自带；重做图时也保留 | V18 quick scope: 141 challenge items; mean ± sample SD across three seeds. No new distillation family met all criteria.<br>Differences were not significant after correction. New adapters: epoch 3; original LoRA: prior checkpoint selection. |

可直接使用英文[融合结果图 PNG](F:/Personal/Code/A_B/docs/presentation_20261103/03_fusion_result.png)，也提供同名 SVG。

**讲述重点：**已完成的三种解释蒸馏均没有达到进一步改进的目标，复杂组合没有自动带来收益。这是当前范围内的结果，不是对融合方法的普遍否定。

**制作说明：**图中均值来自同一批 141 道挑战开发题。提示组合与分歧复核主要已有验证集结果，不能与此图混排。保留新蒸馏固定第 3 轮与原 LoRA 选型方式不同的脚注。

**来源：**[V18 一天版最终分析](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/018_fusion/quick24_results/ASSESSMENT.md)。

### 第 15 页｜What We Need to Validate Next

**归属：未来方向，同时作为收束页。**

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | What We Need to Validate Next |
| 主体 | 三行问题与行动对应，复制下表 | — |
| 主体下方 | 文字，阶段结论 | **Prompting and fine-tuning improve development results. Class trade-offs and generalization still need validation.** |
| 底部 | 英文脚注 | Previously used development data; AI-assisted rationale review. Label disputes and data-sealing deviations are documented in the appendix. |

上屏表格：

| Observed limitation | Next step |
|---|---|
| Unclear rule contributions and coverage gaps | Add presupposition and time-scope rules; ablate rules individually |
| Higher NEI recall but lower REFUTES recall | Add explicit refutation / NEI contrasts; independently adjudicate disputed labels |
| Prior data exposure and similar templates | Evaluate on newly collected, unseen items; vary wording and compare inference cost |

**讲述重点：**下一步围绕未解决的类别边界、规则贡献和独立泛化验证展开。

**制作说明：**此页结束正文，不必增加空白致谢页。未来实验不标为已完成，不编预期提升数字。实际分工或 AI 使用说明如放入 PPT 备注，也使用英语。

## 四、答辩备份页

### 第 16 页｜Lessons from Earlier Attempts

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Lessons from Earlier Attempts |
| 中央 | 表格，复制下表 | — |
| 底部 | 文字 | **Valid formatting and extra verification do not guarantee faithful reasoning.** |
| 最下方 | 英文脚注 | Different experiment rounds and subsets; not a unified performance comparison. |

上屏表格：

| Attempt | Observation | Lesson |
|---|---|---|
| Two-world reasoning | Counterexamples sometimes altered evidence or added exceptions | Preserve every evidence constraint |
| JSON constraints | V2: all 441 formal outputs were valid JSON; semantic errors remained | Format validity is not reasoning accuracy |
| Four-role construction and verification | V5 challenge: baseline 30/44; four-role method 18/44 | Extra verification can introduce errors |
| Semantic formalization + Z3 | V6: 42 valid JSON outputs, 24 executable ASTs; challenge 7/21 vs. baseline 14/21 | Translation and representation were major bottlenecks |

**答辩口径：**这是不同轮次的探索，不画成统一性能曲线，也不能证明双世界或符号方法普遍无效。

**来源：**[V2](F:/Personal/Code/A_B/experiments/002_constrained_output/RESULTS.md)、[V5](F:/Personal/Code/A_B/experiments/005_layered_worlds/RESUMPTION_20261026_RESULTS.md)、[V6](F:/Personal/Code/A_B/experiments/006_symbolic_z3/RESULTS.md)。

### 第 17 页｜Zero on a Subtype Is Not Zero Overall

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Zero on a Subtype Is Not Zero Overall |
| 左半 | 文字与算式 | **V17 baseline: AMBIGREF**<br>SUPPORTS: 9/9 correct<br>NEI: 0/6 correct<br>Mechanism total: 9/15 = 60% |
| 右半 | 文字与算式 | **V17 baseline: all challenge items**<br>Correct: 54 SUPPORTS + 19 REFUTES + 28 NEI<br>Overall: 101/141 = 71.63% |
| 底部 | 文字 | **A 0% score on an NEI subtype is not a 0% score on the whole mechanism or dataset.** |

**答辩口径：**A 组 PPT 第 8–10 页的低分不能直接当作整个机制准确率；第 12 页整体挑战准确率仍为 66.7%。第 8–9 页没有明确给出低分分母，因此只能说复现错误模式，不能声称逐项复算其原数字。若将这一补充写入 PPT，使用下面英文文字：

```text
Team A reports 66.7% overall challenge accuracy on slide 12.
The low-score denominators on slides 8–9 are not explicit.
We reproduce related error patterns, not an exact recalculation of those percentages.
```

**来源：**[A 组 PPT](../references/Adversarial_Fact_Verification_Midterm_1793104017.pptx)、[V17 逐题预测](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/017_unified_comparison/results/predictions.csv)。

### 第 18 页｜Difficult Subtypes: Results by Seed

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Difficult Subtypes: Results by Seed |
| 主体 | 表格，复制下表，数字为正确数 | — |
| 底部 | 英文脚注 | Correct counts on 22 selected NEI items. Post-hoc diagnosis only. Seeds do not create additional independent items. |

上屏表格：

| Mechanism / variant | N | Baseline | NLI | PJ | LoRA 42 | LoRA 43 | LoRA 44 |
|---|---:|---:|---:|---:|---:|---:|---:|
| LOOKALIKE / bare | 5 | 0 | 0 | 1 | 4 | 5 | 5 |
| AMBIGREF / diff_gender_other_pronoun | 3 | 0 | 0 | 2 | 3 | 3 | 3 |
| UNIQUE / other_indef\|indef | 2 | 0 | 1 | 1 | 2 | 2 | 2 |
| SETCLOSE / subset_count | 2 | 1 | 1 | 2 | 2 | 2 | 1 |
| PRESUP / still_decoy\|before | 3 | 0 | 0 | 2 | 3 | 3 | 1 |
| TEMPSCOPE / first_term | 3 | 1 | 1 | 1 | 3 | 3 | 3 |
| DENIAL / baseless | 4 | 0 | 1 | 4 | 4 | 4 | 4 |
| Total | 22 | 2 | 4 | 13 | 21 | 22 | 19 |

**制作说明：**variant 是统计筛选字段，不提供给模型。PRESUP 这一行只选冻结标签为 NEI 的三条，不混入同名变体的其他标签。合计是诊断子集，不是整体挑战成绩。

**来源：**同第 12 页；按题目 ID 对齐统计。

### 第 19 页｜Limitations and Open Questions

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Limitations and Open Questions |
| 主体左侧 | 三条限制 | Prior exposure to development data<br>AI-assisted rationale review<br>No PRESUP training coverage; some labels remain disputed |
| 主体右侧 | 问答摘要，复制下方英文内容块 | — |
| 底部 | 英文脚注 | V16 engineering tests read raw full/test files for overlap and deduplication checks. Those reads were not used for this run's model training, selection, or evaluation, but strict data-sealing acceptance was not fully satisfied. |

右侧上屏内容：

```text
Which method is best?
LoRA has the highest V17 challenge accuracy.
PJ is the only candidate meeting all V17 criteria.

Why did fusion not improve further?
The completed designs did not meet all criteria.
The cause has not been isolated.

What remains unfinished?
49 full-scope development comparison configurations,
additional post-distillation review, epoch-wise selection,
and a new independent generalization evaluation.
```

**答辩口径：**若被问到 V18 回退 A0 与 V17 推荐 PJ 是否矛盾：V18 一天版事前固定的五个最终候选方法族不含独立 PJ 提示路线，两次推荐的候选范围不同。需要写入 PPT 备注时直接用下面英文：

```text
V18 selected among five predefined method families, excluding standalone PJ prompting.
Its fallback to A0 does not invalidate the V17 comparison.
```

**来源：**[封存偏差](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/016_finetune_27b/revision_2/DEVIATIONS.md)、[V18 最终分析](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/018_fusion/quick24_results/ASSESSMENT.md)。

### 第 20 页｜Confusion Matrices: NLI and Individual LoRA Seeds

**归属：新增答辩备份。** 展示第 13 页省略的 NLI 及 LoRA 三个种子的独立结果，不占正文 5 分钟。

| 位置 | 类型／制作指令 | Slide content (English) |
|---|---|---|
| 顶部 | 文字，标题 | Confusion Matrices: NLI and Individual LoRA Seeds |
| 主体左上 | 3×4 矩阵；格内标原始条数 | NLI |
| 主体右上 | 3×4 矩阵；格内标原始条数 | LoRA · Seed 42 |
| 主体左下 | 3×4 矩阵；格内标原始条数 | LoRA · Seed 43 |
| 主体右下 | 3×4 矩阵；格内标原始条数 | LoRA · Seed 44 |
| 轴与共用色条 | 方向、顺序、色阶同第 13 页 | True label / Predicted label<br>Color: percentage within each true class · 0–100% |
| 底部 | 英文脚注，解释文字数值与颜色的区别 | Cell text: item counts. Color: row-normalized percentage. Each panel uses the same 141 challenge items.<br>Rows: SUPPORTS (54), REFUTES (19), NEI (68). Invalid outputs count as errors. Seeds are separate runs, not extra independent items. |

以下为四张图的原始正确与错误条数，列顺序均为预测标签；上屏转成矩阵，颜色仍按每行比例映射，格内保留整数：

**NLI：**

| True label | SUPPORTS | REFUTES | NEI | Invalid |
|---|---:|---:|---:|---:|
| SUPPORTS | 53 | 0 | 0 | 1 |
| REFUTES | 0 | 19 | 0 | 0 |
| NEI | 0 | 32 | 33 | 3 |

**LoRA · Seed 42：**

| True label | SUPPORTS | REFUTES | NEI | Invalid |
|---|---:|---:|---:|---:|
| SUPPORTS | 54 | 0 | 0 | 0 |
| REFUTES | 1 | 17 | 1 | 0 |
| NEI | 0 | 1 | 67 | 0 |

**LoRA · Seed 43：**

| True label | SUPPORTS | REFUTES | NEI | Invalid |
|---|---:|---:|---:|---:|
| SUPPORTS | 54 | 0 | 0 | 0 |
| REFUTES | 0 | 17 | 2 | 0 |
| NEI | 0 | 0 | 68 | 0 |

**LoRA · Seed 44：**

| True label | SUPPORTS | REFUTES | NEI | Invalid |
|---|---:|---:|---:|---:|
| SUPPORTS | 54 | 0 | 0 | 0 |
| REFUTES | 0 | 17 | 2 | 0 |
| NEI | 0 | 4 | 64 | 0 |

**答辩口径：**三种子均值隐藏了具体错误数量的波动，因此提供各运行明细。Seed 43 在 NEI 上全对，但仍错 2 道反驳题；Seed 42 的反驳错误分别去了 SUPPORTS 与 NEI。NLI 也有 4 条无效输出，其中 1 条来自 SUPPORTS、3 条来自 NEI，不能直接画成丢弃无效输出的 3×3 矩阵。

**素材状态与来源：**已绘制英文[四矩阵矢量图](F:/Personal/Code/A_B/docs/presentation_20261103/beamer/assets/confusion_seeds.pdf)，已用于 Beamer PDF 第 20 页；全部由 [V17 逐题预测](F:/Personal/Code/A_B/worktrees/A_B_fusion_v18/experiments/017_unified_comparison/results/predictions.csv)中 `dataset=challenge` 的记录统计，不与基础集或其他实验轮次混合。

## 五、真实题目核对索引（制作说明，不上屏）

本次只使用下列三道实际题目；第 6、12 页回扣同一批例子，不额外构造人物或事件。原题摘录与预测的可核对记录见 [slide_examples.json](F:/Personal/Code/A_B/docs/presentation_20261103/slide_examples.json)。

| 使用位置 | 题目 ID | 机制／变体 | 冻结标签 | 原题使用方式 |
|---|---|---|---|---|
| 第 2 页左侧；第 12 页最后一行的实例 | e_b30e3a12162be36f | DENIAL / baseless | NOT ENOUGH INFO | 证据关键句逐字摘录；完整 Claim |
| 第 2 页右侧 | e_072e61b1f738c059 | DENIAL / shown_false | REFUTES | 同组对照题的证据关键句逐字摘录；同一完整 Claim |
| 第 4 页；第 6 页回扣；第 12 页第三行的实例 | e_51c3569118fd293c | UNIQUE / other_indef\|indef | NOT ENOUGH INFO | 证据获奖句逐字摘录；完整 Claim |

若提问需要展示这些题的实际预测，可直接使用下面英文表；正文第 2、4 页不必额外塞入这张表：

| Item ID | Gold | Baseline | NLI | PJ | LoRA 42 / 43 / 44 |
|---|---|---|---|---|---|
| e_b30e3a12162be36f | NEI | REFUTES | REFUTES | NEI | NEI / NEI / NEI |
| e_072e61b1f738c059 | REFUTES | REFUTES | REFUTES | REFUTES | REFUTES / REFUTES / REFUTES |
| e_51c3569118fd293c | NEI | REFUTES | NEI | NEI | NEI / NEI / NEI |

此表的 `NEI` 是 `NOT ENOUGH INFO` 的显示缩写，不改变评分标签。来源为 V17 逐题预测文件，而非根据方法总体准确率推测。

## 六、素材与制作顺序

以下为制作索引，不上屏：

| 素材 | 使用页码 | 状态 |
|---|---|---|
| [01_unified_accuracy.png](F:/Personal/Code/A_B/docs/presentation_20261103/01_unified_accuracy.png) | 第 11 页 | 英文标题、标签和脚注；可直接插入 |
| 本文件第 13 页的三个混淆矩阵输入表 | 第 13 页 | 比例已核对；已绘制三张并排英文矩阵，包含 Invalid 列 |
| 本文件第 20 页的四个混淆矩阵输入表 | 第 20 页 | 条数已核对；已绘制 2×2 排列的英文矩阵 |
| [02_recall_tradeoff.png](F:/Personal/Code/A_B/docs/presentation_20261103/02_recall_tradeoff.png) | 备用素材 | 保留英文召回图；第 13 页已改用混淆矩阵 |
| [03_fusion_result.png](F:/Personal/Code/A_B/docs/presentation_20261103/03_fusion_result.png) | 第 14 页 | 英文标题、标签和脚注；可直接插入 |
| [chart_data.csv](F:/Personal/Code/A_B/docs/presentation_20261103/chart_data.csv) | 第 11、14 页及备用召回图 | 原有图表数值；混淆矩阵数据使用本文件第 13、20 页的表格 |
| [slide_examples.json](F:/Personal/Code/A_B/docs/presentation_20261103/slide_examples.json) | 第 2、4、6、12 页 | 原题 ID、原文摘录、标签、冻结预测与来源哈希 |
| 本文件英文表格和内容块 | 对应页码 | 可直接复制；中文制作说明不进 PPT |
| 实际组员姓名、日期、分工 | 第 1 页及备注 | 制作时按真实信息填写为英语 |

先做第 11–14 页结果图表，再做四条方法路线，最后补引入、未来方向和备份页。不需要重新请求模型，也不需要重新读取原测试数据。
