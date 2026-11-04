# V15 修订 1：冻结统一协议的受控评估

新构造受控题集；两种方法均在看见模型结果前冻结。不是独立自然文本盲测。

| 数据集 | NLI | PJ v3 | PJ−NLI |
|---|---:|---:|---:|
| basic | 168/168（100.00%） | 168/168（100.00%） | +0.00 pp |
| challenge | 148/168（88.10%） | 156/168（92.86%） | +4.76 pp |

挑战集双侧模板族置换 p=0.25000000；预设 alpha=0.05，PJ v3 至少 +5 pp 的主标准通过：False。
基础能力点估计限制通过：True。这不是统计非劣效证明。

## 三类召回率

| 数据集 | 标签 | NLI | PJ v3 |
|---|---|---:|---:|
| basic | SUPPORTS | 100.00% | 100.00% |
| basic | REFUTES | 100.00% | 100.00% |
| basic | NOT ENOUGH INFO | 100.00% | 100.00% |
| challenge | SUPPORTS | 100.00% | 100.00% |
| challenge | REFUTES | 100.00% | 100.00% |
| challenge | NOT ENOUGH INFO | 64.29% | 78.57% |

## 分机制准确率

| 数据集 | 机制 | NLI | PJ v3 |
|---|---|---:|---:|
| basic | BOUND | 24/24 | 24/24 |
| basic | FUNCTIONAL | 24/24 | 24/24 |
| basic | IMPLICATIVE | 24/24 | 24/24 |
| basic | PLACE | 24/24 | 24/24 |
| basic | PLAN | 24/24 | 24/24 |
| basic | RELDATE | 24/24 | 24/24 |
| basic | TIMESHIFT | 24/24 | 24/24 |
| challenge | AMBIGREF | 23/24 | 24/24 |
| challenge | DENIAL | 17/24 | 24/24 |
| challenge | LOOKALIKE | 22/24 | 22/24 |
| challenge | PRESUP | 22/24 | 22/24 |
| challenge | SETCLOSE | 16/24 | 16/24 |
| challenge | TEMPSCOPE | 24/24 | 24/24 |
| challenge | UNIQUE | 24/24 | 24/24 |

## 成本与限制

- nli：336 次正式响应，输入 87432 tokens，输出 23164 tokens，总计 110596 tokens。
- pj_v3：336 次正式响应，输入 327336 tokens，输出 23835 tokens，总计 351171 tokens。
- 上述为最终评分对应成本；包括被替换题目的旧响应和预检在内，实际已收 732 次响应，共 502691 tokens。
- 另有 4 次原轮中断请求未收到响应，用量未知，不计为零。

每套 168 题、56 个场景组，但仅 14 个手写模板族；同模板更换实体的四个变体不被当作独立模板。区间与置换检验仅对这些受控模板作条件性描述，不证明自然文本总体泛化。
本轮在查看答案和分数前修正了48道题的英文事件/范围限定，旧冻结和全部旧响应保留。其余输入的完整旧响应按冻结清单无条件复用；修订和补跑不依据答案正确与否。详见 amendment.json。
构造者已了解双方方法，题集并非独立出题；标签通过真值枚举与 Z3 一致性核验，但自然语言到形式模型的对应未经独立人工裁决。S/R 题可能明显容易于 NEI。
统一了角色、JSON 字段、最终标签、1024 token 上限、seed 与交错调用；提示词自身的长短和实质规则保留。因此结果针对统一后的方法版本，不覆盖历史原协议。
零原文重叠不代表与既有机制独立，也不证明模型预训练未见类似模板。严禁依据本轮结果改提示词后继续把本题集称作保留评估。

复现：`python -m ab_factcheck.controlled_v15a verify`；`python scripts/audit_controlled_v15a.py --results`。仅 `run`/`preflight` 请求模型；`report`/审计只读既有响应。
