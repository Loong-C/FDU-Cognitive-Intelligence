# V8：正反命题 NLI 一致性

**状态：2026-10-28 完整确认与独立审计均已完成。** 在 101 道预先选定的新开发题上，一致性方案 basic 为 59/60（A27 60/60）、challenge 为 31/41（A27 26/41）。按用户允许“不显著退步”的开发筛选口径通过；原先两套准确率与 macro-F1 点估计都不下降的严格门槛未通过。未证明统计非劣效或测试泛化。详见 [完整结果](RESULTS.md)。此前 [69 题暂停报告](PAUSE_REPORT.md)保留为历史快照。

本轮由用户明确要求持续研究至得到不差于 A27 基线的方法，沿用“不显著退步即可”的约束。模型固定 Groq `qwen/qwen3.8-27b`，每次请求 `reasoning_effort=none`、temperature=0、seed=42；不训练、不使用题型规则、不读取封存测试集。所有文件均留在仓库内。

## 推理方法

1. 用冻结的 A27 直接分类获得基线判断 B。
2. 用上一轮冻结的 NLI 提示词判断原命题，获得 P。
3. 若 B=P，直接返回 B；若分歧，才判断原命题的整句否定，获得 N。
4. 将 N 翻回原命题方向：S↔R、NEI↔NEI。
5. 若 P 与翻回后的 N 相同，采用 P；否则保留 B。

规则对三个标签对称，没有按数据集、机制、词语、题目 ID 或 gold 路由。两种 NLI 不一致时不会自动输出 NEI。生成或协议无效时执行事前定义的基线回退，并单列无效数。

否定是确定性的整句包装：

```text
It is not the case that the following statement holds: "<完整原 claim>"
```

JSON 引号保留原始 claim 的全部字符；不改写原句、不拆量词、不增删条件。Evidence 完全保留，NLI 系统指令和 Schema 与 V7 相同。API 只收到原 evidence 与原 claim 或其确定性否定，不发送 gold、管理字段或其他模型回答。

该包装在形式上表示整个命题的否定，但模型是否准确理解自然语言否定仍需实验验证。**正反一致不等于正确，也不是 SAT/SMT 证明。** 当前做法不生成“可能世界”，不把找不到反例解释成不可满足。

## 预检与开发流程

先冻结 `planned_confirmation.json`：basic 60、challenge 41，共 14 个此前未使用的完整开发组，排除历史 pilot、V5 fresh 和全部 V7 组。此清单在本轮任何模型调用前生成，选样没有使用模型预测。虽然数量与 V7 确认相同，组与样本不同；隔离凭证在 `group_isolation.json`。

`probe` 使用 9 个独立合成命题，每个分别判断原命题和否定，覆盖原子、合取、析取及三类标签。18 个结果必须全部按预期互换或保持 NEI，才能发送开发集请求。合成例子只作为单独测试，不加入正式提示词。

`scout` 复用 V7 的历史 42 题及原始预测，仅为 6 个分歧追加否定调用。探索结果为 challenge 17/21（A27 14/21），basic 21/21（A27 21/21）；修复了单次 NLI 的一道 basic 误伤，但保留了一道 challenge 误伤。共增加 2,815 token。18 个合成探针消耗 4,301 token。以上均非新的独立验证成绩。

`confirm` 在新 101 题上重新运行 A27 与正向 NLI，并按规则追加否定调用；全程不从中途结果改方法。另有可选 `bridge` 入口复用 V7 的 101 题，但它只能作为已使用开发数据的诊断，不能冒充新的独立确认。

## 验收与统计

两套数据分别要求准确率与 macro-F1 点估计不低于 A27，且至少一套准确率严格提高。三类召回均报告变化，并检查是否出现 p<0.05 的按组配对显著下降。完整报告所有组、机制、改对与误伤，以及条件否定一致率。

沿用 V7 的整组 bootstrap 和配对组置换检验。不把同组变体当独立样本；未检出显著下降不等于证明非劣效。类别样本很少时必须说明区间的不确定性。若方法所有输出都与 A27 相同，只能报告无新增收益，不能宣称取得了改进。

部署成本是 **每题 A27 + 正向 NLI，共两次调用，加上分歧时的一次反向 NLI**。探索阶段的缓存复用只减少研究调用，不意味着部署免费或只需一次调用。成本与准确率分开比较。

## 运行和恢复

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -B -m pytest tests/test_negation_v8.py tests/test_macro_v7.py -q
.venv\Scripts\python.exe -B -m ab_factcheck.negation_v8.experiment prepare
.venv\Scripts\python.exe -B -m ab_factcheck.negation_v8.experiment freeze --phase probe
.venv\Scripts\python.exe -B -u -m ab_factcheck.negation_v8.experiment run --phase probe
.venv\Scripts\python.exe -B -m ab_factcheck.negation_v8.experiment report --phase probe
# scout 与 confirm 均先 freeze，再 run，最后 report。
.venv\Scripts\python.exe -B -u -m ab_factcheck.negation_v8.experiment run --phase confirm
.venv\Scripts\python.exe -B -m ab_factcheck.negation_v8.experiment report --phase confirm
# 若因服务端明确的 429 额度等待而中断，可按原冻结版本自动续跑：
.venv\Scripts\python.exe -B -u scripts/resume_negation_v8.py
```

代码、配置、清单在请求前冻结哈希。成功响应缓存不得重抽；读取缓存时检查内容哈希及精确请求。未知是否收到答案的网络中断保留 inflight 标记，禁止盲目重发。长额度限制保存断点并以非零状态退出。沿用 `outputs/groq/quota.json` 的共享账本，不清零、不换账户、不升级套餐。恢复时重用已有答案。

原始请求与响应在 `outputs/negation_v8/<phase>/records/`。本目录保存冻结文件、派生指标、逐条预测、统计与报告；未完成阶段不得以已完成前缀替代全部应测分母。

自动续跑器仅对明确的 429 额度中断按账本中的服务端重置时间等待；遇到其他错误停止检查。等待期间不发请求、不重置账本。`outputs/negation_v8/confirm/continuation.json` 保存续跑状态，全部完成后自动生成确认报告；不自动宣称目标已达成，还需要独立审计及最终判断。

完整确认后的离线复核与汇总：

```powershell
.venv\Scripts\python.exe -B scripts/audit_negation_v8.py
.venv\Scripts\python.exe -B scripts/report_negation_v8_final.py
```

独立审计已通过：216 个原始响应、14 个完整组、历史组重叠为零，确认总用量 85,667 token。筛选结论在 `final_assessment.json` 中同时保留严格门槛与用户原有宽松口径，未覆写冻结配置。相关本地测试 59 项通过。

## 理论关系

对一致证据 E，E 蕴涵 C 等价于 E∧¬C 不可满足；C 的蕴涵、矛盾、中立关系在严格否定后应分别交换为矛盾、蕴涵、中立。依据见 [Stanford 逻辑教材的反驳原理](https://logic.stanford.edu/intrologic/lessons/lesson_14_07.html)和 [Stanford NLI 任务说明](https://nlp.stanford.edu/projects/snli/)。本实验只检验语言模型是否能利用这个对称性改善预测，不赋予模型输出形式证明的地位。
