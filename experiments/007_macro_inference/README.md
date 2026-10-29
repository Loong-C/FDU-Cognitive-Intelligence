# V7：宏观推断方式与保守共识

## 约束与对照

- 固定 Groq `qwen/qwen3.8-27b`，每个请求显式 `reasoning_effort=none`、temperature=0、seed=42。响应校验模型身份、可见 reasoning 字段和结束状态。
- 不训练模型，不使用 SFT/LoRA，不给出具体机制、关键词或题目的专用规则。
- 推理函数只接受 claim/evidence。label、group、mechanism、variant 等不会进入请求。
- 仅使用已有 development 划分。开发命令没有 test 读取入口；最终测试仍封存。
- 所有新增源文件、临时文件、日志和结果均留在本仓库。沿用已有 Groq 服务；不升级套餐。
- 用户在本次对话明确允许沿用 Groq，仅发送开发集输入。

A27 对照逐字复用 `prompts/v2/A2_*` 和 A2 JSON Schema，输出上限 1024。新方法统一上限 512；实际成本另报。新方法的短依据字段不设字符上限，避免旧实验中理由被字段长度约束截断的风险。它们输出简短依据，不请求思考链，不启用模型思考模式。

## 方法

1. `nli`：将 Evidence/Claim 改写为 Premise/Hypothesis，判别 ENTAILMENT/CONTRADICTION/NEUTRAL，再以固定映射还原三分类。
2. `certificate`：先输出一至两句证据依据，再输出原始三分类标签。只说明通用逻辑后承标准。
3. `dual`：分别判断 evidence 是否蕴含 claim 及其否定。真/假→S，假/真→R，假/假→NEI，真/真→INVALID；不会将“claim 为假”混成“假世界不可能”。
4. 探索阶段同时报告预定义的保守共识：两个独立方法一致才覆盖基线，否则保留基线。规则对三个标签对称，不读取 gold 或机制。

这些是待检验假设，不预设能够提高分数。Schema 合规和模型输出的依据也不是形式化证明。

## 评测设计

scout 使用 V6 的历史 42 道开发题（basic 21、challenge 21），复用同题历史 A27。此阶段可用于方法选择，不能叫独立验证，也不能排除历史基线与当前后端之间的变化。

在查看 scout 汇总分数前已写入 `planned_confirmation.json`：从未使用过的开发组中，每个数据集、每个机制按固定哈希抽一个完整组，排除旧 pilot、V5 fresh 及已有 V7 阶段的组。得到 basic 60、challenge 41，共 14 组。最终候选在这 101 道题上与重新运行的同批 A27 比较；模型只见各题本身，不见其组内其他题。

初始门槛：两个数据集分别满足准确率、macro-F1 和三类召回均不下降，且至少一个数据集准确率严格提高。另报更强门槛：每个机制准确率也不下降。任何缺失或 INVALID 均计错。所有组与机制的原始分母完整保留，不删除困难题，不修正 gold。

完成探索后，用户明确补充“要求不用过严，不显著退步即可”。在确认阶段发出任何请求之前，已保存 `acceptance_amendment.json`，取代初始的零退步筛选门槛。选择 NLI 进入确认：它在历史 challenge 多对 3/21，在 basic 少对 1/21；dual 的基础损失更大，独立盲复核则回到基线，没有新增收益。

放宽后的统计采用 **整组交换两个方法的预测** 的双侧精确置换检验，以及整组 bootstrap 区间。accuracy、macro-F1、三类 recall 分别报告；p<0.05 且方向为下降时标记显著退步。检验未作多重比较校正，因此对发现退步的标记较保守。每数据集仅 7 个组，检验效能有限；“未检测到显著退步”绝不改写为“证明非劣”。未指定非劣效界值，不事后发明界值来让方法通过。保留初始严格门槛供对照。

同时报告配对改对/改错数量及以完整 group 为单位的 bootstrap 区间。少量组、开发集选择、多方法探索均限制外推；不能把开发成功称为最终 test 提升。基线已满分的维度最多持平，不可能要求严格超过 100%。成本不保证下降，准确率与成本分别呈现。

## 运行与恢复

在仓库根目录运行，使用已有 `.venv`；设置 `PYTHONDONTWRITEBYTECODE=1` 可避免额外字节码缓存。

```powershell
.venv\Scripts\python.exe -B -m pytest tests/test_macro_v7.py -q
.venv\Scripts\python.exe -B -m ab_factcheck.macro_v7.experiment freeze --phase scout
.venv\Scripts\python.exe -B -u -m ab_factcheck.macro_v7.experiment run --phase scout
.venv\Scripts\python.exe -B -m ab_factcheck.macro_v7.report --phase scout
.venv\Scripts\python.exe -B -m ab_factcheck.macro_v7.experiment freeze --phase confirm --arms baseline nli
.venv\Scripts\python.exe -B -u -m ab_factcheck.macro_v7.experiment run --phase confirm
.venv\Scripts\python.exe -B -m ab_factcheck.macro_v7.report --phase confirm
.venv\Scripts\python.exe -B -m ab_factcheck.macro_v7.audit --phase confirm
.venv\Scripts\python.exe -B -m ab_factcheck.macro_v7.assess --phase confirm
```

配置与推理源码在发送请求前冻结哈希；收到的答案立即保存，不因错误答案而重试。缓存必须通过请求、冻结配置及响应内容哈希检查。未知是否收到服务端答案的传输中断保留 inflight 标记并停止；不能自动重复抽样。共享 `outputs/groq/quota.json` 账本保留历史记录。分钟限速等待、网络重试和实际 token 用量分别记录；服务端长额度限制会停止，不切换账户或付费服务。

原始请求/响应：`outputs/macro_v7/<phase>/records/`。可复算指标、混淆矩阵、分机制/组、配对结果、区间与成本：本目录各阶段的 `metrics.json`。逐条预测：各阶段 `predictions.csv`。

## 探索阶段的负结果

`scout` 的 126 个响应全部完成，43,213 token，协议和可见非思考检查全部通过。不能把字段合规当成语义正确。NLI 和 dual 的挑战集准确率均从 14/21 升到 17/21，但都有类别召回损失；基础集分别为 20/21 和 19/21。certificate 为 challenge 14/21、basic 21/21。完整三种两两保守共识也未通过初始门槛。

追加的 `review_scout` 是盲阅读理解复核：本地只在基线与 NLI 分歧时调用，API 仅收到原始 claim/evidence，不收到候选答案或 gold。6 个分歧追加 6 次请求，共 2,556 token；结果 challenge 14/21、basic 21/21，与基线完全相同。这是明确的无收益结果，保留代码和记录，不把它作为最终推荐方案。

实现时曾提议把模型候选及依据提供给复核者，该请求被自动审批拒绝且没有执行；随后改为上述已获准的纯原始输入盲复核。用户后续批准并放宽要求后，仍保留已冻结的盲复核版本，没有为追求分数重写或重发这些答案。

## 参考

Groq 官方 [Qwen 3.8 27B 模型说明](https://console.groq.com/docs/model/qwen/qwen3.8-27b)与 [API 文档](https://console.groq.com/docs/api-reference)说明 `reasoning_effort=none` 的接口用法。本实验只主张请求参数与可观察响应满足非思考要求；托管服务没有开放内部计算量的独立测量。
