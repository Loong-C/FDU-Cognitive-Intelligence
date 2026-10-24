# v5 工程与真实运行报告：架构完成，正式对照尚未运行

截至北京时间 **2026-10-24 17:09**，四调用架构、冻结提示词/Schema、确定性分类器和回归测试已完成；真实 Groq 调用完成 **22 次、9,800 token**。其中只有 **3/10 道虚构题**完成四个角色，第 4 道完成两个构造器。**新开发集 V5 为 0/104，A27 为 0/104，完整配对为 0/104。没有新开发集准确率、宏 F1、召回改善或消融结论。**

暂停原因是既有历史用量仍占用本地保守的滚动 24 小时预算，并非服务端拒绝请求，也不代表已证明账号免费额度耗尽。没有清零账本、放宽预算、切换付费服务、修改提示词、补造结果或重复生成错误答案。

**最重要的已观察失败：静态坏候选门槛没有通过。** 验证器仍把“候选自身违反证据”误判为“原始目标与证据不相容”。因此，即便工程上已拆分角色，也不能宣称这一逻辑问题已经解决。

## 1. 基线、实现和保存范围

- 新分支：`codex/layered-world-v5`；基线为 `codex/groq-27b-v4` 最新提交 `5425613d937148f862e3583caddafef5603d5546`，本地与远端 SHA 一致。没有从 main 开始。
- 独立模块包括 `models`、`prompts`、`constructor`、`verifier`、`adjudicator`、`orchestrator`、`client`、`selection`、`experiment`、`evaluation`，以及独立 CLI 和审计脚本。
- 两个构造器和两个验证器各发起一次新会话。主流程固定为 T 构造、F 构造、T 验证、F 验证，不依据 A27、gold 或上游语义判断选择性触发。某节点技术失败或额度不足时暂停，未完成题不能算作跑完四调用。
- 原始 Evidence/Claim 是唯一任务输入；验证器另外只看到本分支的 `target_condition` 和 `candidate_world`。标签、组别、机制和其他分支不进入模型请求。候选只作为不可信数据插入固定 user 模板。
- 8 个英文模板及 2 个 Schema 按附件原始字节复制，原 SHA-256 清单逐项验证；未压缩、改写或附加系统指令。
- 模型固定 `qwen/qwen3.8-27b`，`reasoning_effort=none`、temperature 0、seed 42、非流式、严格 Schema。四角色上限各 384 completion token；独立 A27 对照沿用旧 A2 提示词、Schema 和 1024 上限。
- 这是同一 Groq 托管模型的四个独立角色，不是四套不同权重。Groq 不公开可独立核对的权重、内部模板和计算过程；不能证明与本地 Q8_0 完全等价。

程序映射严格区分见证、目标矛盾、坏候选与未知：

| T 状态 | F 状态 | Python 结果 |
|---|---|---|
| FEASIBLE | INFEASIBLE | SUPPORTS |
| INFEASIBLE | FEASIBLE | REFUTES |
| FEASIBLE | FEASIBLE | NOT ENOUGH INFO |
| INFEASIBLE | INFEASIBLE | UNRESOLVED_CONTRADICTION |
| 任一 UNKNOWN | 任意 | UNRESOLVED_BRANCH |

`CANDIDATE_INVALID` 和 `UNDETERMINED` 均映射为 UNKNOWN。候选失败不会自动变成不可能，不会重生成，也不会回退 A27。**验证器输出仍是 LLM 对可满足性的估计，不是 SAT/SMT 形式证明。**

## 2. 测试与真实技术门槛

[测试凭据](test_validation.json)：**153 项通过、0 项失败**，包括旧 109 项回归与新增 44 项。新增测试覆盖全部 16 个决策组合、花括号/Unicode/长输入、恶意候选文本、拒绝元数据、空字段/重复 JSON/枚举/Schema、403/429/503、两次有界重试、响应不明与崩溃恢复、账本限额、完整离线 smoke 和缓存重放。离线 HTTP fixture 只用于测试，从未计入真实实验结果。

真实技术探针共 6 次：无 Schema 对照返回 `NOT_JSON`；构造器、验证器、A27 三个对抗哨兵仅在 Schema 中指定字段值且得到遵守；另用不限制/限制长度的成对请求验证 maxLength。故本轮不是仅凭“合法 JSON”推断服务端执行约束。

22 个响应全部返回指定模型 ID，全部通过可观察非思考检查；21 个带 Schema 响应全部通过结构验证，另 1 个是故意无 Schema 的文本对照。未观察到 token 截断、HTTP 错误或网络重试。内部 reasoning token 的不可观察部分仍不能独立证明。

三个 `system_fingerprint` 分别出现 7、7、8 次，见[预算及环境凭据](budget_receipt.json)。固定 seed 和模型 ID 不保证托管后端逐位确定；只有 Python 分类器本身是确定性的。

## 3. 真实静态坏候选检查：1/2 符合预期

完整判断及原始哈希见 [static_gate_results.json](static_gate_results.json)。以下属于助手语义审读，不是外部人类审核。

| 检查 | 原始约束与候选 | 预期 | 真实输出 | 结论 |
|---|---|---|---|---|
| 坏候选，目标仍可满足 | E：Mira 周三浇水；C：周四浇水；候选：周三没浇、周四浇了 | CANDIDATE_INVALID | TARGET_CONTRADICTS_EVIDENCE | **错误**：周三浇与周四浇可以同时成立，只有候选否认周三有问题 |
| 原始目标矛盾 | E：2010 年出生；C：2000 年前出生；候选并列二者 | TARGET_CONTRADICTS_EVIDENCE | TARGET_CONTRADICTS_EVIDENCE | 正确：矛盾来自 E/C 本身，无需依赖额外候选错误 |

第一条理由直接诉诸候选中的 “did NOT water Wednesday”，却输出目标层矛盾，并把 “Mira watered Wednesday” 当作目标冲突锚点。该证据不能排除周四浇水。这是**候选错误被提升为目标不可满足**的实际反例，而非解析器或状态映射错误。

两条静态理由均达到 240 字符，句子未完整结束；已记录 `REASON_LIMIT_HIT:reason`。没有把它们包装成完整有效的证明，也没有改写理由或重新请求。

## 4. 真实虚构样本：3 道完成、1 道部分完成、6 道未启动

| 样本 | gold（只用于本地检查） | T 验证 | F 验证 | Python 结果 | 完成调用 |
|---|---|---|---|---|---:|
| synthetic_s_equal | SUPPORTS | WITNESS_VALID | TARGET_CONTRADICTS_EVIDENCE | SUPPORTS | 4/4 |
| synthetic_r_birth | REFUTES | TARGET_CONTRADICTS_EVIDENCE | WITNESS_VALID | REFUTES | 4/4 |
| synthetic_n_water | NOT ENOUGH INFO | WITNESS_VALID | WITNESS_VALID | NOT ENOUGH INFO | 4/4 |
| synthetic_n_openlist | NOT ENOUGH INFO | 未调用 | 未调用 | 未生成 | 2/4 |
| synthetic_n_denial | NOT ENOUGH INFO | 未调用 | 未调用 | 未生成 | 0/4 |
| synthetic_r_only | REFUTES | 未调用 | 未调用 | 未生成 | 0/4 |
| synthetic_s_interval | SUPPORTS | 未调用 | 未调用 | 未生成 | 0/4 |
| synthetic_n_attempt | NOT ENOUGH INFO | 未调用 | 未调用 | 未生成 | 0/4 |
| synthetic_n_conjunction | NOT ENOUGH INFO | 未调用 | 未调用 | 未生成 | 0/4 |
| synthetic_r_number | REFUTES | 未调用 | 未调用 | 未生成 | 0/4 |

按照全部预定 10 道样本为分母，当前执行进度下的正确率为 **3/10=30%**，coverage 为 **30%**；已完成 3 道的条件准确率为 100%。后者只是固定前缀的描述，**不能作为完整 smoke 通过、基准性能或方法改善证据**。此处 7 道未完成主要是预算造成的缺测，不能误写成 7 道模型语义错误。正式数据一个也未运行。

三道完整样本的助手审读：

- 精确数量：T 候选保留“恰好三枚”；F 候选并列原事实与其否定。按任务约定，这种目标无法成立时显露张力的构造允许存在，验证器正确指出 E 蕴含 C，而没有修改证据。
- 出生年份：T 候选保留 2010 与 before 2000 的冲突；T 验证正确判目标矛盾。F 候选为 2010、因此不早于 2000，F 验证输出 WITNESS_VALID。这个案例中没有再把“claim 为假”理解成“假世界不可能”。
- 跨日浇水：两个候选都保留周三浇水，分别让周四浇/不浇；两个验证器均认为见证有效，程序得出 NEI。与静态坏候选构成对照，说明验证器对同类开放目标的处理会受到候选错误干扰。
- 开放名单：两个构造器分别写 Ivo 出席与不出席，均保留 Uma、Bo；尚无验证结果，不补推断模型会如何判断。

六个完整分支判断为 4 个 WITNESS_VALID、2 个 TARGET_CONTRADICTS_EVIDENCE，未出现 CI/U 或双不可能；加入两个静态检查后为 4 个 WITNESS_VALID、4 个 TARGET_CONTRADICTS_EVIDENCE，其中至少 1 个目标矛盾判断错误。没有观察到 CI 不等于构造失败率为零，尤其静态坏候选恰恰应当被归为 CI。

普通虚构题 6 个验证理由中 4 个触及字符上限；加静态检查为 **6/8=75%**。这些响应 finish_reason 仍为 stop，Schema 合规，但说明存在句中/词中结束。字符顶格与 token 截断已分开记录；本轮未调整冻结 Schema。

逐节点结构、成本与哈希见 [smoke 报告](reports/layered_worlds_qwen38_27b_v5_r1_smoke/metrics.json)、[节点凭据](reports/layered_worlds_qwen38_27b_v5_r1_smoke/node_receipts.jsonl)、[逐题状态](reports/layered_worlds_qwen38_27b_v5_r1_smoke/predictions.csv)。

## 5. 新开发集冻结与未运行的配对对照

[fresh_dev_v5.json](fresh_dev_v5.json) 使用固定种子 20261024，以 SHA-256 对每种机制的可用 group 排序，选择第一个完整 group；排除两套旧 pilot 的全部 group。选择不使用旧预测、新预测或正确率，不根据标签调整胜出组；标签只用于汇总覆盖。源文件哈希、全部候选组排名、选中行和执行顺序均记录。

| 数据集 | 新 group | 题数 | SUPPORTS | REFUTES | NEI | V5 完成 | 同题 A27 完成 |
|---|---:|---:|---:|---:|---:|---:|---:|
| challenge | 7 | 44 | 17 | 5 | 22 | 0 | 0 |
| basic | 7 | 60 | 13 | 23 | 24 | 0 | 0 |
| 合计 | 14 | 104 | 30 | 28 | 46 | 0 | 0 |

challenge 的 AMBIGREF、DENIAL、LOOKALIKE、PRESUP、SETCLOSE、TEMPSCOPE、UNIQUE 及 basic 的 BOUND、FUNCTIONAL、IMPLICATIVE、PLACE、PLAN、RELDATE、TIMESHIFT 各一个完整场景组。两套数据按机制索引交错执行，组内连续，同题先 A27 后完整四调用。暂停时保留这一预定前缀，不按已看到的性能选择续跑对象。

冻结时间和哈希见 [freeze_receipt.json](freeze_receipt.json)。**顺序上的已披露偏离**：代码、单元测试、完整离线虚构流程和真实技术/静态检查完成后，因剩余真实 smoke 受预算约束，先冻结了正式清单和指纹；完整真实 smoke 尚未通过。没有借此跳过门槛：实际调用 `run` 已验证会在缺失 smoke 响应处停止，新增 HTTP 请求为零。

正式报告已经按全部 104 个预定样本生成缺测状态、含 INVALID 的混淆矩阵结构、每类 precision/recall、宏 F1、coverage、条件准确率、机制/group 分层及配对统计。**其中零分/零计数只是“全部未运行”的机器可读占位，不是实测准确率。** 不应引用这些占位值评价模型。见 [fresh 状态报告](reports/layered_worlds_qwen38_27b_v5_r1_fresh/metrics.json)。

旧 pilot 已被 v1-v4 多轮使用，不作为新验证集；旧 B27 仅作为历史动机，没有伪装成 fresh_dev 的同题对照。封存 test 未用于选择或推理，原 gold 未改。继承的 basic 标签人工审核状态仍应按源数据解释，不能因本轮抽样而称为重新人工核验。

## 6. 之前的问题解决了吗？

| 问题 | 本轮可支持的结论 | 尚缺的证据 |
|---|---|---|
| 世界状态颠倒 | Python 映射与方向通过全部 16 组合测试；已完成 3 题未见反向输出 | 新开发集全部未运行，无法估计真实方向错误率 |
| 候选违反证据却被当成目标不可能 | **尚未解决**；静态周三/周四案例明确重现 | 更多坏候选与真实场景的人工语义复核 |
| REFUTES 召回崩溃 | 一个虚构 REFUTES 得到正确 I/F 可行性组合 | 正式 28 道 REFUTES 均未运行；不能声称相对旧 37 道 0 召回已恢复 |
| 双 IMPOSSIBLE/双不可行 | 3 个完整虚构题没有双不可行；代码将该组合留为 UNRESOLVED | 样本太少，不能证明该问题消失 |
| 证据被改写或否定范围出错 | 已完成候选显示保留证据、显露矛盾的路径可运行 | only、完整合取否定、否认/归因、attempt、区间和数值边界的真实 smoke 尚未完成 |
| 理由与状态不一致 | 静态坏候选已有理由针对候选缺陷而状态宣称目标矛盾的错位 | 正式数据的系统复核及未截短理由 |
| 理由不完整 | **仍明显存在**：真实非探针验证理由 6/8 达到 240 字符 | 不改变本 run 的前提下无法把已有文本补全；如另做改版必须保留本结果并另立版本 |

角色分离和 Schema 可以约束输出形式及信息流，不能保证模型正确地区分逻辑层级。当前没有任何证据允许宣称 v5 优于直接三分类，也没有新鲜样本配对证据可判断其是否更差。

## 7. 成本、保护性停止和恢复

真实调用跨度为北京时间 **17:02:02–17:05:30**。6 个技术探针、2 个静态验证、14 个普通虚构角色响应，共 22 次成功请求；输入 8,440、输出 1,360、合计 **9,800 token**。没有失败网络请求或重试。已完整 3 道虚构题的四调用共 7,157 token，均值约 2,385.7；仅按这个短文本均值外推 104 道 V5 就约 24.81 万 token，**还不含 A27 与长证据开销**，该值只是粗略预算估计，绝非实际正式用量。

暂停时历史近 24 小时保守收费量 165,808，本轮 9,800，合计 **175,608**；本地保护线 180,000，剩余 4,392。下一条 `synthetic_n_openlist/verify_T` 的保守预留为 **4,508**，会超保护线 **116**，所以在发 HTTP 前停止。保守预留使用请求 UTF-8 字节数、固定开销和 completion 上限，不是实际 tokenizer 计数。历史失败请求的未知用量仍保留预留，没有为挤出预算而删除。

最新服务端头为 1000 RPD、8000 TPM，显示剩余 978 requests、7082 minute tokens。它不提供 TPD 剩余额度。本次停止由更保守的本地滚动账本触发，不应说成 Groq 拒绝服务或官方日额度已经耗尽。没有查询账单，因此也不独立宣称零费用。

旧用量从北京时间 **2026-10-24 19:13:35** 开始逐渐退出 24 小时窗口，旧 v4 最后一项在 **20:20:34** 退出。较方便的手动恢复时间为 **20:21 之后**；这不保证剩余 104 对可在同一个滚动窗口全部完成。本轮的用量仍会计入后续预算。

恢复步骤见 [README](README.md)：先重跑 `smoke --env-local --free-plan-confirmed`；完整技术协议门槛完成后，再运行 `run --env-local --free-plan-confirmed`。语义错误保留为观察，不因此补答或修改冻结提示词。若再次达到预算，继续保存固定清单进度，待后续窗口手动恢复。当前剩余 **26 个 smoke 角色调用、520 个正式调用**；可选旧 B27 基线和省略构造器的消融均未运行，不占主方法统计。

本次实际重放 smoke 和尝试 formal gate，账本请求数都保持 **333→333**，22 份成功响应哈希全部不变，见 [resume_validation.json](resume_validation.json)。没有不明飞行中请求；停止点是发送前预算拒绝，可安全续跑。

## 8. 完整性、密钥和交付限制

[独立代码路径审计](integrity_audit.json)核对了 22 个真实响应、逐角色模板/Schema/输入隔离、依赖哈希、三个确定性结果、全部 **2,050 个历史文件**和 **311 条原账本项**，均通过。此处“独立”指不复用分类器的审计代码路径，执行者仍是同一助手，不宣称由另一位人类或独立 Agent 审核。

`.env.local` 保持忽略且未跟踪。提交前用实际密钥值扫描非忽略文件及本轮 raw JSON，未发现泄漏；扫描只输出是否发现，没有输出密钥。系统代理设置未修改、代理地址与凭证未记录；只使用既有固定 Groq HTTPS 端点。

完整响应、精确请求、API 元信息及错误记录留在被 Git 忽略的 `outputs/runs/layered_worlds_qwen38_27b_v5_r1_smoke/`；正式运行目录已经冻结指纹但没有任何推理响应。Git 中只提交新代码、附件冻结版本、清单、脱敏统计、语义审读与哈希凭据。历史 v1-v4 文件没有改写。

**尚未完成的核心交付是新开发集上的真实配对比较。** 当前报告如实交付工程、部分真实验证和具体失败证据；不将模拟测试、缺测占位、旧数据成绩或三个虚构成功案例替代正式实验。
