# V9 少量样本方案筛选结果

最终候选：`reason_first_nli`。所有阶段已完成，原始响应及计分审计通过。

Qwen-27B 非思考；仅开发集输入；未训练；测试集封存。初筛和扩展使用历史开发题，只能用于选方向。确认集为 14 个此前未使用的组、每组两题，共 28 题，并非完整组评测。

## 14 题初筛

| 方法 | Basic 正确数 | Challenge 正确数 |
|---|---:|---:|
| agree__claim_first_nli | 7/7 | 6/7 |
| agree__reason_first_nli | 7/7 | 7/7 |
| agree__repeat_baseline | 7/7 | 6/7 |
| agree__repeat_nli | 7/7 | 7/7 |
| baseline | 7/7 | 6/7 |
| certificate | 7/7 | 6/7 |
| claim_first_nli | 7/7 | 6/7 |
| dual | 6/7 | 7/7 |
| nli | 7/7 | 7/7 |
| reason_first_nli | 7/7 | 7/7 |
| repeat_baseline | 7/7 | 6/7 |
| repeat_nli | 7/7 | 7/7 |
| signed_v8 | 7/7 | 7/7 |

## 42 题扩展筛选

| 方法 | Basic 正确数 | Challenge 正确数 |
|---|---:|---:|
| agree__reason_first_nli | 21/21 | 17/21 |
| agree__repeat_nli | 21/21 | 16/21 |
| baseline | 21/21 | 14/21 |
| certificate | 21/21 | 14/21 |
| dual | 19/21 | 17/21 |
| nli | 20/21 | 17/21 |
| reason_first_nli | 21/21 | 17/21 |
| repeat_nli | 21/21 | 17/21 |
| signed_v8 | 21/21 | 17/21 |

## 28 题新开发组确认

| 方法 | Basic 正确数 | Challenge 正确数 |
|---|---:|---:|
| baseline | 14/14 | 9/14 |
| reason_first_nli | 14/14 | 10/14 |

## 确认集配对比较

| 数据集 | Accuracy 差值 | 修正 / 损害 | 组 bootstrap 95% 区间 | 组置换 p |
|---|---:|---:|---:|---:|
| basic | +0.00 pp | 0 / 0 | [+0.00, +0.00] pp | 1.0000 |
| challenge | +7.14 pp | 1 / 0 | [+0.00, +21.43] pp | 1.0000 |

小样本不能证明总体非劣或测试集提升。候选和规则在确认请求之前冻结；确认结果不会用于重新选择本轮赢家。

## 成本

本轮新增 168 个唯一响应，共 63,514 tokens；历史缓存成本不计入本轮新增开销。
确认阶段基线使用 8,683 tokens，候选部署所需响应使用 9,197 tokens（1.06 倍）。融合方案计入基线；单模型方案不计入用于比较的基线。

## 干预与解释限制

`reason_first_nli` 改变的是请求 schema 的字段顺序；还需区分请求顺序和实际生成顺序。各方案实际响应的首字段计数见 audit.json 的 observed_first_output_fields。若对照原本也先输出 justification，不能把差异解释为先推理后分类的因果效果。
14 题初筛的 challenge 恰好没有 REFUTES 样本，故该切片无法估计此类召回率；没有为了补齐标签而事后换题。42 题扩展和 28 题确认分别保留各自真实类别分母。

输入完整性、精确请求、模型返回 ID、非思考可观测检查、分组隔离、冻结时间、逐题决策及准确率/F1/类别召回率均已核对。未读取测试文件。
