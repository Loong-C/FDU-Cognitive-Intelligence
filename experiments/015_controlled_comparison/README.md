# V15：冻结 NLI 与 PJ v3 的统一受控评估

**最终执行入口是 [修订 1](amendment_1/README.md)。** 原轮在查看模型答案和分数前，因英文事件/范围限定问题暂停；本目录的原冻结完整保留。不要继续运行原 `controlled_v15 run`。最终评估使用 `controlled_v15a`，不是本目录原轮的未完成结果。

本轮按用户要求，使用新构造受控题集比较两条方法路线。模型返回前冻结方法、题集、参数、调用顺序和统计规则。它是双方统一协议下的受控实验，不是 A 组独立自然文本盲测。

## 冻结内容

- NLI 原文取自 `ddfc4d2:prompts/v7/nli_system.txt`。
- PJ v3 原文取自 `8d8c4fb:prompts/imported_pj_20261029/challenge-prompt-v3-full-20261028/prompt-v3.txt`。
- 原文在 `prompts/original_*.txt` 按原始字节保留。统一后的 `prompts/nli.txt`、`prompts/pj_v3.txt` 保留各自实质定义和规则，替换输出格式指令；所有任务指令放入 system，同一 user 模板只包含 evidence/claim。
- 同一服务 `qwen38-27b`、temperature=0、seed=42、关闭 thinking、max_tokens=1024、并发4。统一 JSON 的 `justification`/`verdict` 字段与最终标签，理由最多三句。
- 两种方法都各调用一次；不投票、不根据正确与否重抽。提示词长度保留差异，实际 token 成本单独报告；相同输出上限不意味着相同总成本。
- `freeze.json` 保存数据、提示词、协议、调用顺序、源码和测试哈希。运行前逐项验证；收到的原始响应关联同一 freeze 哈希。后续不修改本轮冻结文件。

统一版与历史版的输出协议不同，结果不能直接替代各自原报告的分数。历史数据和实验记录保持原状。

模型权重由远端服务管理，本轮不能独立给权重文件做哈希。保存了服务自报模型列表和每次响应的模型 ID/fingerprint；这属于可观测服务信息的留档，不应写成已经验证远端权重逐字节不变。

## 新数据

基础与挑战各168题，三类标签各56题；每套7种机制、14个模板族、56个场景组。每个模板族有4个更换实体/数值的场景，每场景包含S/R/NEI三种证据变体。共336题、672次正式响应，另有2次预检调用。

基础机制：BOUND、FUNCTIONAL、IMPLICATIVE、PLACE、PLAN、RELDATE、TIMESHIFT。

挑战机制：AMBIGREF、DENIAL、LOOKALIKE、PRESUP、SETCLOSE、TEMPSCOPE、UNIQUE。

`inputs.jsonl` 是推理输入；`gold.jsonl` 包含完整组、机制、标签和形式模型。标签不进入模型请求。程序检查336个唯一输入与旧1785题没有完全相同的 evidence/claim 对；这不等同于不存在语义/模板重叠，更不证明预训练未见类似内容。

标签由真值枚举产生，并由独立 Z3 实现检查 E∧C 和 E∧¬C 是否可满足；整数题的枚举使用0..50代表值，Z3另以无上界的非负整数复核。两边一致才准许运行。

形式模型中的 q 通常表示待判断命题；p 表示相关但不同的事件或状态；member 表示是否属于受唯一性限制的集合；denial 是否认言语行为；past 是过去的位置事实。数字题的 n/day 代表数量/日号。形式模型记录作者给出的文本语义或其相关后果，不能用求解器一致性代替对自然语言翻译的独立验证。

本题集由了解双方方法的同一助手构造，没有独立出题者或独立人工裁决。S/R变体多含明确正负证据，可能比NEI容易；短文本、平衡标签、模板集中和虚构实体均限制其代表性。不得将其准确率外推为原挑战集准确率或自然文本总体准确率。

## 统计协议

主比较预定为挑战集 `PJ v3−NLI` 准确率差。按模板族汇总净正确数，进行双侧精确配对符号置换；alpha=0.05，且PJ v3至少提高5个百分点才通过主标准。不把同模板的实体替换当作独立样本。

基础能力限制：PJ v3准确率最多下降2个百分点，各类召回最多下降5个百分点。这些是点估计限制，不是统计非劣效证明。基础/挑战分开报告，不合成一个总分。其余指标包括三类精确率/召回/F1、Macro-F1、机制分数、配对纠正与损害、实际token、耗时和无效输出。

置信区间按机制内重抽模板族，固定5000次bootstrap。每机制只有两个手写模板，且机制之间也可能相似，推断仅是对当前受控模板的条件性诊断，不能代表随机抽取的自然文本总体。

调用按冻结哈希顺序交错安排，轮换每题先提交的方案；无按效果提前停止。截断或格式无效的已收答案计错，不重新抽取。认证、模型、thinking或基础设施异常会暂停；失败和未完成题不从分母剔除。

## 执行与复核

仓库现有 `.venv` 已包含 httpx、jsonschema、z3-solver；实际版本另见 `environment.json`。密钥沿用 `docs/qwen38_server_api.md` 的本机配置，绝不写入实验文件。

```powershell
.venv\Scripts\python.exe -m pytest tests/test_controlled_v15.py -q
.venv\Scripts\python.exe -m ab_factcheck.controlled_v15 prepare
.venv\Scripts\python.exe scripts/audit_controlled_v15.py
.venv\Scripts\python.exe -m ab_factcheck.controlled_v15 preflight
.venv\Scripts\python.exe -m ab_factcheck.controlled_v15 run
.venv\Scripts\python.exe -m ab_factcheck.controlled_v15 report
.venv\Scripts\python.exe scripts/audit_controlled_v15.py --results
```

`preflight` 和 `run` 会请求模型。重复 `run` 只复用哈希一致的已收响应；不覆盖历史记录。网络结果不确定的 `.inflight` 保留现场，不自动重发。

`verify`、`report`、审计不请求模型。`report` 必须等全部672个正式响应齐备才生成最终分数；审计另从原始响应复算预测、准确率、混淆矩阵、召回、机制分数、token和精确置换检验。

上面的完整流程用于首次执行。已有 `preflight.json` 时不要重复创建预检时间戳记录；恢复正式运行直接执行 `verify` 和 `run`。已有完整响应时，离线复算只执行 `report` 与 `--results` 审计。

原始响应与运行状态位于被Git忽略的 `outputs/controlled_v15/`。若在别的机器复核原始响应，必须同时复制此目录；仅仓库中的逐题预测可用于重算摘要，不能替代原始响应审计。

本轮完成后，结果入口为 `RESULTS.md`、`metrics.json`、`predictions.csv`、`audit.json`。任何基于本轮结果的提示词修改都应建立新版本，并另找评估数据。
