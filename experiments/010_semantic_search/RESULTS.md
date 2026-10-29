# V10 语义判别小样本实验

状态：futility_stop；扩展候选：`agree__contrast`。新增 70 个响应，28,656 tokens。

固定 Qwen-27B 非思考。仅开发集输入，无训练、无具体题型规则。incumbent 是 V9 的 reason_first_nli。探索使用旧开发样本，不能当作独立确认。

## pilot

| 方法 | Basic | Challenge |
|---|---:|---:|
| agree__compatibility | 7/7 | 6/7 |
| agree__contrast | 7/7 | 7/7 |
| agree__normalize | 7/7 | 6/7 |
| baseline | 7/7 | 6/7 |
| compatibility | 5/7 | 4/7 |
| contrast | 7/7 | 7/7 |
| incumbent | 7/7 | 6/7 |
| normalize | 7/7 | 6/7 |

## scout

| 方法 | Basic | Challenge |
|---|---:|---:|
| agree__contrast | 21/21 | 17/21 |
| baseline | 21/21 | 14/21 |
| contrast | 20/21 | 17/21 |
| incumbent | 21/21 | 17/21 |

扩展候选未通过事前冻结的增益门槛，因此未调用新确认题，保留现有 V9 候选。不能宣称新方案提升，也不能把未确认视为确认失败。
