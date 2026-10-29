# 持续目标状态与下一轮工作

截至 2026-10-29，用户的持续目标仍 ACTIVE，尚未达到事前分配的显著性门槛，不应标记 complete，也没有暂停请求。V11/V12 进程都已正常结束，当前没有仍在等待的 API worker。继续实现并运行 V13，不要重新运行已经收到的答案。

## 已完成

- 用户新提供文档 `docs/qwen38_server_api.md`，授权全面使用内网 `http://10.176.30.103:20027/v1`，模型 `qwen38-27b`。服务器自报 Qwen3.8-27B-w8a8，必须关闭思考，使用 `chat_template_kwargs={enable_thinking:false}`。已实测 JSON Schema、structured_outputs.choice、logprobs/top_logprobs 20，所有能力探针在 V11 目录。
- 独立适配器 `src/ab_factcheck/intranet_client.py`。认证由其 key_value() 从已授权本机 Key 文件/环境读取，禁止输出或复制 Key。记录不含认证头；连接直连、禁代理和重定向；未知传输结果保留 inflight、禁止重发；确定错误有界重试。旧 Groq 客户端/冻结源文件未改，不再使用 Groq。
- V11 筛选 42 题的 9 个候选：NLI、保义复述、三关系核验、原/否定命题 A/B/C 三轮换概率池、六视角池、投票、正反 NLI 一致性过滤。扩展 126 题的前两名实际是 nli 与 signed_gate，不是 normalize（曾在口头进度中误说，随后已更正）。冻结赢家 nli。
- V11 独立确认 203 题/28 完整新组：basic A27/NLI=113/120、119/120；challenge=56/83、66/83，+12.05 pp，修正/损害=11/1。按组单侧精确 p=.03125，未过 alpha=.025。幅度限制通过。1246 正式响应、425523 tokens。审计通过，完整记录保留。
- V12 固定同一个 NLI，另 306 题/41 完整新组：basic=164/180、174/180；challenge=85/126、92/126，+5.56 pp，修正/损害=7/0。两套三类 recall 均不下降。p=.015625，未过 alpha=.0125。612 响应、212011 tokens。审计通过。
- V11/V12 全部成功响应缓存不可改/重抽；源码在 freeze.json 中锁定，不改 frozen 文件。新增版本使用独立文件/目录。

## 剩余独立确认数据

`reserved_confirmation.json` 已经冻结 **所有剩余此前未用于推理的开发组**，不是按标签/预测/难易选择：basic 120 题/14 组，challenge 236 题/38 组。模型尚未收到这些 V13 保留输入。

重要范围限制：challenge/SETCLOSE 已没有未使用组。剩余 challenge 只覆盖 LOOKALIKE 13 组、PRESUP 9 组、DENIAL 8 组、UNIQUE 1 组、AMBIGREF 5 组、TEMPSCOPE 2 组。之后若在此集合确认，必须明确是六机制的剩余开发组，不能伪称新的全七机制确认；之前的 SETCLOSE 结果只作分开报告。

下一次独立主检验 alpha 上限=.00625（累计之前 .0375，加入下一轮共 .04375）。保持 challenge 增益至少5pp；basic accuracy/macro-F1 退步≤2pp，challenge macro-F1不下降，各类 recall下降≤5pp。不能事后更改 V11/V12 门槛、不能把两个失败主检验合并重新挑选显著结果。若最终没有达到，应如实继续/说明数据限制，不造阳性。

## V13 原始计划方向（已实现，见末尾进度）

继续用户的宏观逻辑思路，比较两个新视角：

1. **二元蕴含概率分解**：分别问 E 是否必然推出 C、E 是否必然推出整句 C 的否定；每个请求只输出两个受约束选项的一个 token，读取两个实际 logprobs。用同一个阈值 tau 对两个分支做对称判断：仅正分支超过阈值→S；仅负分支超过→R；都没超过→NEI；两者都超过则回退固定 NLI。开发阶段预先冻结 tau 网格（例如 .5,.65,.8,.9），不按关键词/机制或题目路由。不是 SFT/LoRA，不训练基座权重。
2. **中文指令的 NLI 视角**：输入仍保留原始英文 claim/evidence；只将通用的必要蕴含/矛盾/均不推出定义改为中文。不能加入否认、名单、时间等具体题型提示。按同一模型、非思考、固定 schema 测试。可预先冻结与英文 NLI 的通用融合规则。

先在 V11 screen 的42题比较（重用已有同服务器 baseline/NLI 缓存作为探索对照，明确非新确认），只扩展有希望的一种到 V11 expand126题。候选必须在开发扩展中胜过已有 NLI 或有清楚可检验的价值，随后冻结一个方法才调用 reserved confirmation。若没有新方向胜出，可考虑固定 NLI 的剩余池确认，但要透明说明不是新方法以及剩余六机制范围。不要为制造显著性反复改规则。

需要先验证二选一受约束输出和概率字段，用不含数据集内容的探针；源码/协议/选择规则/保留清单哈希必须在新数据调用前冻结。小样本筛选应优先使用旧组，保留最后独立开发池。

## 工具与复核

- Python `.venv/Scripts/python.exe -B`，设置 PYTHONDONTWRITEBYTECODE=1、PYTHONUTF8=1。所有代码、缓存、临时文件、测试产物必须留在 F:/Personal/Code/A_B 内；不要写外部目录。Key 文件仅按已授权位置读取。
- 没有 AGENTS.md，未使用技能，无子代理授权，不要 spawn agent。HTTP 并发最多先沿用4路，每批4个，尊重服务器响应。
- 复用 V11 的 request/parse 及独立 Client；新二元/中文接口用新源码，不修改 V11/V12 冻结模块。
- `scripts/audit_server_v11.py`、`scripts/audit_server_v12.py` 均已执行成功。V12 的 exact_p 用整数卷积计数全部组符号翻转；测试与独立暴力枚举一致。V13 38组不能直接枚举2^38，可复用精确卷积，并用独立 meet-in-the-middle 或其他等价实现核验。
- 主目标通过后仍需独立核验请求、推理模式、采样组隔离、完整组、映射、指标、主检验和密钥未落盘，整理可复现方法与结果，再 update_goal complete。

用户约束：Qwen-27B、不开思考；不做原数据 SFT/LoRA；测试集绝不读取/发送；不能用过度具体题目/机制提示；不把文件放仓库外；先小样本节约 token；允许仅不显著/明显退步，但当前冻结幅度限制必须保持。

## V13 执行进度（2026-10-29）

代码 `src/ab_factcheck/binary_bilingual_v13.py` 已实现并冻结，3 项单元检查通过。二元选择/真实 logprob 的人工文本探针通过。协议和代码 SHA256 已冻结于 `plan.json`、`freeze.json`，不要修改冻结源码。

当前 pipeline 已启动，unified exec session ID **36559**；恢复观察用 write_stdin，不要重复启动。初筛 126 个新响应已完成，42 道旧开发题上：baseline 18/21、14/21；NLI 21/21、17/21；中文 NLI 21/21、15/21；一致性门控 21/21、15/21；binary_50/65 16/21、16/21；binary_80 14/21、15/21；binary_90 14/21、14/21。冻结初筛候选为 `zh_nli`，正在 126 道旧开发题上扩展。最终 winner 仍须读取实际 `winner.json` 后报告。

`scripts/audit_server_v13.py` 已实现但尚未运行完整审计，需等待流水线完成；其独立 meet-in-the-middle p 值算法已通过 6 组边界/混合符号对照，包含 14 组穷举对照。脚本会独立检查所有阶段决策、分组隔离、选法、指标、请求、非思考、成本、密钥和主检验，并生成 `audit.json`、`RESULTS.md`。流水线状态存于 `outputs/server_v13/pipeline.json`。

扩展已完成：baseline basic 59/63、challenge 37/63；NLI 62/63、42/63；中文 NLI 63/63、39/63。`winner.json` 已冻结最终 **nli**。同一 session 36559 正在执行 356 道保留开发题 × baseline/NLI 的 712 次确认调用，已收到至少 80 个响应。仅监测接收数/延迟，不中途查看准确率或调整策略。

待执行：pipeline 完成后运行 `.venv/Scripts/python.exe -B scripts/audit_server_v13.py`；通过后运行 `.venv/Scripts/python.exe -B scripts/report_server_series.py`，生成 `experiments/server_summary/RESULTS.md` 和逐轮/机制 JSON。后者不合并各轮主检验。`docs/server_nli_method.md` 已写好通用方法、与双世界逻辑的对应和证据边界；需在确认结束后更新其运行状态说明。最后更新根 README 和本文件，以实际审计结果判断目标是否达成。

## 同步执行的旧开发组探索 V14

在 V13 固定 NLI 确认期间，额外实现并冻结 `src/ab_factcheck/semantic_binary_v14.py`，仅使用旧的 42/126 开发题，不接触 V13 新确认结果。V13 二元分支诊断显示初筛 8 道 REFUTES 中反分支仅 1 道高于 .5；汇总在 `screen/binary_diagnostics.json`，已被 V14 冻结引用，不再修改。

V14 比较 direct_contrad（保留原命题，直接问是否必假，A/B 概率）及 proof_entail/proof_contrad（先简短依据再 YES/NO）；直接分支共享 .10/.25/.50 阈值，另有 proof_pair/proof_gate。3 项单元测试通过。初筛 126 次新增调用，两路并发；只有挑战较 NLI 至少多对 2 题、基础少对至多 1 题且基线幅度限制通过才扩展一个候选到 126 道旧题；无独立确认或显著性声明。

V14 unified exec session ID **42491** 正在运行；V13 **36559** 同时运行。2026-10-29 13:36:54 UTC：V13 正式缓存共 524 个（252 探索 +272/712 确认），V14 26/126，均无 error。不要重复启动任何 worker。两者完成后各自独立审计；V14 审计脚本为 `scripts/audit_server_v14.py`，还未完整执行。`README.md`、源码、冻结协议和测试均已落盘。最后总览应补上 V14 探索结果并区分 V13 独立确认。

**更新：V14 已完成，session 42491 退出码 0，不再轮询。** 126 次响应、33,842 tokens；direct_10 基础/挑战 17/21、15/21；direct_25 19/21、16/21；direct_50 16/21、16/21；proof_pair 21/21、18/21；proof_gate 21/21、17/21。没有候选满足预定挑战 +2 题，selection=None，未扩展。`scripts/audit_server_v14.py` 已运行通过，`audit.json` 和 `RESULTS.md` 已生成，全部有效、无接口错误、无测试集读取。README、方法文档和总览脚本已补 V14。当前唯一活跃 worker 仍是 V13 **36559**，已完成至少 400/712 确认调用；尚未查看确认准确率。

## 最终状态（2026-10-29 13:56 UTC 后）

V13 **已完成，session 36559 退出码 0，不再轮询**。所有 712 次确认响应已接收；含探索共 964 响应、339,928 tokens。固定 NLI 基础 116/120（A27 109/120），挑战 161/236（A27 134/236）；主挑战增益 +11.4407 pp，精确单侧组置换 p=0.00001239776611328125 < 0.00625，其他指标幅度限制通过。基础 +5.8333 pp，组 p=.078125（基础优势不单独宣称显著）。挑战修正/损害 31/4，基础 9/2。基础 NEI 召回 -2.17 pp、挑战 R 召回 -2.78 pp，不能声称所有指标都上升或总体非劣已证明。NLI 的 3 个无效响应保留并计错。

`scripts/audit_server_v13.py` 已独立验证逐条请求、哈希、非思考、完整新组、无组交叉、选法、所有指标、精确主检验和密钥扫描，**通过**；`audit.json`、`RESULTS.md` 已生成。V13 主挑战组仅六机制，不能声称新的七机制确认；V11/V12 的 SETCLOSE 结果分别保留，无退步。本轮独立目标达标，不合并失败轮次重算主检验。

`scripts/report_server_series.py` 已运行，生成 `experiments/server_summary/RESULTS.md`、`summary.json`。V11–V14 共 2,948 次正式响应、1,011,304 tokens，不含人工探针。V14 仍是探索终止，不改写为成功。根 README 和方法文档已改为完成状态。当前没有本任务活跃模型 worker，无需继续消耗服务器调用。
