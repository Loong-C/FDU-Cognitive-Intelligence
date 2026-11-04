# V15 修订 1：最终执行入口

已完成。先读[结论与限制](ASSESSMENT.md)和[完整结果](RESULTS.md)：基础两者均168/168；挑战NLI为148/168、PJ v3为156/168。PJ v3的+4.76个百分点与模板族置换p=0.25未通过事前主标准。

方法和生成参数沿用原冻结：NLI 与 PJ v3，统一 JSON justification/verdict、相同输入格式、1024 token输出上限、temperature=0、seed=42、关闭thinking、并发4。全部实质提示词逐字相同，没有根据模型表现调参。

## 为什么修订

英文语义复核发现两类题需要更严格限定：

- RELDATE：包裹某日到达不能排除另一日再次到达；展览的开幕也应限定为唯一一次事件。为该机制24题统一补充单次事件限定。
- AMBIGREF：某个场合的唯一获奖者，不足以排除同年其他场合、或同一作品其他场合的获奖。将唯一性限制对齐到整个年份或该作品，并为该机制24题统一明确奖项身份。

原真值枚举和Z3只能验证作者给出的形式模型，无法自动发现英文与模型对应不充分的问题。修订发生在查看模型答案和分数之前，标签、形式模型、分组和统计规则均未改变。保留原冻结、原输入与全部已收响应，不将原轮包装成完整有效结果。

修订后仍为336题（基础/挑战各168，均含7机制和三类平衡标签），672个评分单元。`gold.jsonl` 的 `supersedes_id` 标明48道替换题。`protocol.json`、`amendment.json`、`freeze.json` 是机器可读的事前说明和冻结记录。

## 响应复用与中断记录

原轮收到336条正式响应。冻结清单无条件复用其中282条输入和完整请求参数相同的响应，另54条属于替换题，保留但不计入最终评分。复用不看答案是否正确，原始响应的旧freeze哈希保持原样。

修订版新增390次正式调用。原轮另有4次中断后未收到响应的请求，现场保存在原目录的 `.inflight`；无法确定是否已消耗服务资源，用量记未知。修订协议事前规定为这些缺失评分单元各发一次新请求，不根据结果选择重跑。

修订预检配置时发现父响应目录指向错误，正式调用前已修正；该次准备快照和2次能力预检保存在 `outputs/controlled_v15a_setup/`，未产生正式评估响应。实际总成本包括这两次预检，不能忽略。

## 复现

最终冻结和离线复算：

```powershell
.venv\Scripts\python.exe -m ab_factcheck.controlled_v15a verify
.venv\Scripts\python.exe -m ab_factcheck.controlled_v15a report
.venv\Scripts\python.exe scripts/audit_controlled_v15a.py --results
```

正式运行需要恢复时：

```powershell
.venv\Scripts\python.exe -m ab_factcheck.controlled_v15a run
```

完整复核需要本地 `outputs/controlled_v15/`（复用与被替换响应）、`outputs/controlled_v15a/`（新增响应）及 `outputs/controlled_v15a_setup/`（准备阶段预检）三个目录；它们不进入Git，也不包含密钥。`reuse_inventory.json` 逐条记录复用路径和SHA256。

正式评分仍遵循原预案：挑战集PJ v3相对NLI至少提高5个百分点，双侧模板族置换p≤0.05；基础准确率最多下降2个百分点，各类召回最多下降5个百分点。后者只是点估计限制，不是总体非劣效证明。

本轮不是独立出题或自然文本盲测。短文本、手写模板、对方法已有了解、模板相关性及修订过程都限制结论范围。自然语言/形式模型的对应没有独立人工裁决；应连同本次发现并修正的问题一起报告。原轮的其他说明见上级README。
