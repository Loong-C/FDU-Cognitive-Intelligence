# V9：少量样本分阶段比较通用推理方案

用户要求测试多种方案、优先使用部分题目节约 token，并选择最有可能提高准确率的方向。本轮沿用获准的 Groq 开发输入推理；模型固定 `qwen/qwen3.8-27b`、`reasoning_effort=none`、temperature=0、seed=42。所有产物在仓库内，测试集不读取、不发送。

## 比较方案

四种新方案都是保持 claim/evidence 内容的宏观变换，没有样本、机制或关键词专用规则，也没有训练：

1. `repeat_nli`：将 NLI 用户输入逐字重复两遍，system 与输出 Schema 不变。
2. `claim_first_nli`：仅将输入顺序改为 hypothesis 在前、premise 在后，文本逐字保留。
3. `reason_first_nli`：保持输入不变，仅将结构化输出的字段顺序改为简短 justification 在前、relation 在后；不请求长思考链。
4. `repeat_baseline`：将 A27 用户输入逐字重复两遍，其余协议不变。

每种新方案同时评测单独使用，以及“与原 NLI 一致才覆盖 A27，否则回退 A27”的标签对称融合。已有 A27、NLI、V8 正反一致性、V7 certificate/dual 均作为历史对照。旧 certificate/dual 只作描述，不重新进入晋级选择。

输入重复的研究依据：[Prompt Repetition Improves Non-Reasoning LLMs](https://arxiv.org/abs/2512.14982)。论文不是本任务有效性的证明，本轮会记录实际 token 开销和负结果。

## 节约额度的试验设计

- 复用 V7 scout 的 42 道历史开发题及缓存。先按数据集/机制分层、依据固定 hash 选 14 题，每个机制一题；初筛 4 种新推理共 56 次调用。
- 只晋级 2 个底层方案，补齐这 42 题的其余 28 题；最多增加 56 次调用。初筛已收到的 28 个对应响应直接复用，不重抽。
- 根据完整 42 题的表现，在新方案、融合方案、原 NLI、V8 中冻结 1 个最终候选。
- 在 28 道新开发题上与新运行的 A27 成对确认。它们来自 14 个未使用组，每组 hash 选两题，排除历史 pilot、V5 fresh、全部 V7/V8 组。**只评估完整组的一个切片，不声称完成全组或全开发集评测。**
- 新确认清单在任何 V9 模型请求之前固定。采样只依据 ID/hash 和分层字段，不根据 gold、模型预测或是否容易选题。

初筛与晋级采用预先固定的排序：优先每套数据比 A27 少对不超过 1 题的方案，然后比较两套准确率均值、较差一套的准确率差、macro-F1 均值、部署调用数、固定名称顺序。原始三类召回和每套指标仍完整报告，不用合并总分掩盖下降。

这是探索阶段的候选排序，不是统计显著性判据。独立确认只测一个胜出方法；无论成功失败都保留完整分母和原始输出，不从确认结果挑题或修改方案。没有预设能够达到 100% 的结论。

## 冻结与执行

`plan.json` 保存全部探索/确认清单与选择规则，`freeze.json` 保存代码、原提示词、开发文件和依赖哈希。`shortlist.json`、`winner.json` 分别冻结两次选择；只有本地评测读取 gold，模型只收到固定模板与 claim/evidence。

成功响应保存在 `outputs/search_v9/records/<dataset>/<id>/<arm>.json`，所有阶段共享去重缓存。未知是否收到响应的请求留下 inflight 标记，禁止自动重抽。只对明确的 429 额度暂停按原账本期限恢复，不切换账户、模型或套餐。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -B -m pytest tests/test_search_v9.py -q
.venv\Scripts\python.exe -B -m ab_factcheck.search_v9 prepare
.venv\Scripts\python.exe -B -u -m ab_factcheck.search_v9 pipeline
```

`pipeline` 完成初筛、扩展、选择和小样本确认。已冻结的阶段可安全重入，已有答案直接复用。运行状态在 `outputs/search_v9/pipeline.json`；本目录各阶段的 `metrics.json` 与 `predictions.csv` 保留全部方案的本地分数。

部署成本按实际需要的调用计算：单次新方案为 1 次；两种判别一致才覆盖基线的融合为 3 次；V8 为基线加原 NLI 两次，以及分歧时的反向调用。研究中复用历史缓存不会使部署调用免费。

## 初筛与后台完成

14 题初筛已完成，新增 56 个响应、21,257 tokens。A27 为 basic 7/7、challenge 6/7；原 NLI、V8、重复 NLI、调整 NLI schema 字段顺序均为 7/7、7/7。调整输入顺序和重复 A27 均为 7/7、6/7。因此本轮初筛尚未显示超过原 NLI 的增益，两个晋级方案还需扩展及新组确认。

当前实际进展见 [STATUS.md](STATUS.md)。Groq 日 token 配额不足时，执行器按服务端 retry-after 等待；原进程仍存在时不要启动第二个 pipeline。暂停或不确定传输失败时不自动重抽。

`scripts/finalize_search_v9.py --worker-pid <pipeline 的 Python 进程 ID>` 是独立的本地完成观察器，没有模型 API 调用。它检查现有执行器存活情况，完成后运行 `scripts/audit_search_v9.py`，输出 `RESULTS.md`、`audit.json` 和 `outputs/search_v9/completion.json`。所有产物写在本仓库内。若需要手动复核已完成实验：

```powershell
.venv\Scripts\python.exe -B scripts/audit_search_v9.py
```

字段顺序实验还检查实际响应顺序；初筛中原顺序的重复 NLI 同样先输出 justification。因此不能把潜在分数差异直接解释为生成顺序改变。初筛 challenge 中没有 REFUTES 样本，其召回率不可估计；后续阶段保持冻结抽样，不事后换题。
