# 第六轮：27B 受限逻辑形式化 + Z3

从 `codex/layered-world-v5` 的 `9d0daea` 创建 `codex/symbolic-z3-v6`。本轮仅验证一次语义翻译的可行性；没有训练、更换模型、开启思考、多模型集成、自动提示词搜索或新增推理 Agent。v1–v5 的代码、数据、提示词与结果保留。

## 复现

```powershell
.venv/Scripts/python.exe -m pip install -e '.[dev,symbolic]'
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ab_factcheck.symbolic_z3.cli freeze
.venv/Scripts/python.exe -m ab_factcheck.symbolic_z3.cli probe
.venv/Scripts/python.exe -m ab_factcheck.symbolic_z3.cli extract
.venv/Scripts/python.exe -m ab_factcheck.symbolic_z3.cli validate
.venv/Scripts/python.exe -m ab_factcheck.symbolic_z3.cli compile
.venv/Scripts/python.exe -m ab_factcheck.symbolic_z3.cli solve
.venv/Scripts/python.exe -m ab_factcheck.symbolic_z3.cli report
.venv/Scripts/python.exe scripts/audit_symbolic_v6.py
```

`freeze` 校验已存在的冻结文件，不覆盖它们。`extract` 对已保存的回答只做身份校验和离线重放，不再次请求模型；`--limit N` 限制本次新增的完成数。`validate/compile/solve/report` 均可离线运行，批量阶段会校验并重放已完成记录。单文件模式：

```powershell
.venv/Scripts/python.exe -m ab_factcheck.symbolic_z3.cli validate --ast sample.json --evidence evidence.txt
.venv/Scripts/python.exe -m ab_factcheck.symbolic_z3.cli compile --ast sample.json --evidence evidence.txt --output constraints.json
.venv/Scripts/python.exe -m ab_factcheck.symbolic_z3.cli solve --ast sample.json --evidence evidence.txt --output answer.json
```

`evidence.txt` 必须保留原始 UTF-8 文本。输出限制为 4096 token，温度 0、seed 42、`reasoning_effort=none`、非流式，严格递归 JSON Schema。实际请求、模型身份与非思考可观察检查在原始记录内可查。没有声称独立验证供应商内部计算。

## DSL 与求解

冻结文件为 `prompts/v6/{system,user,dsl}.txt` 和 `schema.json`，哈希在 `freeze.json`。system/user 使用任务书原文；dsl 仅补足字段、类型、变量作用域和执行语义，不含本批样本或标签。完整 JSON AST 支持类型实体、别名、变量、整数、加减、整数属性函数、谓词、逻辑连接、比较与量词。

编译前检查 Schema、状态约定、引用连续匹配、声明/参数类型、符号/别名冲突、量词作用域和输入规模。`source_quote` 仅作出处检查，文字不参与公式推理。不同常量默认可同指；确知不同的实体需有原文支持的 `ne` 公式。同义别名映射到同一常量。量词遍历开放域，不限于已声明实体。无 `eval`、模型源码执行、闭世界补全或按 gold 修补。

先检查 `SAT(E)`，再分别检查 `SAT(E ∧ C)`、`SAT(E ∧ ¬C)`。只有 `(sat,unsat)`、`(unsat,sat)`、`(sat,sat)` 分别映射 S/R/NEI。不一致证据、unknown、类型/引用错误、输出截断等均记为 UNSUPPORTED。每次 Z3 检查限时 3000 ms；一般一阶量词并不保证可判定，unknown 不转成 NEI。[Z3 官方量词说明](https://microsoft.github.io/z3guide/docs/logic/Quantifiers/)

Groq strict 输出主要保证 JSON Schema 结构；跨字段类型、状态与语义仍由本地检查/逐题审阅负责。[Groq Structured Outputs 文档](https://console.groq.com/docs/structured-outputs)

## 样本、盲区与统计口径

只读既有 dev 及历史 pilot manifest，按 `challenge/basic × mechanism` 共 14 个分层，每层取 3 题，种子 `20261028`，用规范 JSON `[seed,dataset,mechanism,id]` 的 SHA-256 排序。`selection.json` 冻结 42 个 ID、group、原文和输入哈希；`evaluation.json` 单独保留历史 gold/A27。发送给模型的只有固定提示词和 Evidence/Claim，完整 payload 可审计。

这是重复使用的历史开发实验，不是独立验证；group 内样本相关。抽中 UNIQUE 分层不保证每条都出现 only，抽中 AMBIGREF 也不保证每条都是真歧义。唯一性、开放域、量词、边界和两次 SAT 的专门能力由 15 个手写逻辑案例补充验证，不能据分层名字宣称模型已解决这些全部机制。测试集继续封存。

端到端准确率以全部 42 题为分母，UNSUPPORTED 算错；另报模型可求解覆盖率、Schema 合规率、AST 可执行率、条件准确率、三类召回与七类 challenge 机制。语义翻译正确率由逐题原文审阅判定，正确标签不能掩盖错误形式化。reviewed AST 的覆盖率反映本批样本可表达性，不能泛化为所有自然语言的 DSL 覆盖率。

## 原始记录与复核

- `records/`：每题唯一模型回答、完整请求、JSON 原文、usage、速率头与响应标识哈希。
- `solved/`：原始 AST、SMT 表达式、三次 SAT 状态、最终标签与错误原因。
- `baseline_A27.jsonl`：第四轮同 ID 原始记录，报告时逐字核对当时输入。
- `semantic_review.json`：逐题正确/遗漏/增加/实体/作用域/不可表达及类型错误审阅意见和记录哈希。
- `reviewed_asts/`、`reviewed_solved/`：独立来源复核 AST 及同一个编译器的实际求解结果。由 `scripts/build_symbolic_v6_review_asts.py` 显式逐题构造；该脚本不读 gold、历史预测或模型输出。
- `predictions.csv`、`mechanisms.csv`、`metrics.json`、`RESULTS.md`：可复算表格。
- `ANALYSIS.md`：具体错误、时间歧义、扩展建议。

“人工修正”在本次执行中由 Codex 助手逐题审阅实现，并非外部人类专家标注。修正 AST 不替代原始预测，也不参与模型提示。原文存在歧义时单列，绝不以与 gold 一致为修正目标。

## 技术探针与续跑

两个合成技术探针使用同一提示词/Schema。独立奖项探针产生了语义失败：模型把不确定标签当成不能形式化，返回合法 UNSUPPORTED；出生年份探针验证非空 AST 的类型/编译/求解。没有重生成奖项答案或据此调提示词。第一次探针的冻结凭据保留在 `preflight/initial_freeze.json`；正式运行前仅修改技术门控，使结构合规与语义正确分开统计，并补测非空 AST。

提交前将 Windows 生成的 `client.py` 从 CRLF 统一为仓库要求的 LF；仅字节换行变化，无代码、提示词、请求或结果变化。运行时原冻结凭据和前后哈希保存在 `preflight/run_freeze.json`、`preflight/newline_normalization.json`；当前 `freeze.json` 使用与 Git blob 一致的 LF 哈希，审计同时核对 Git 内的字节，保证克隆后可复现。

密钥只由既有 `load_local_key` 从忽略的 `.env.local` 或进程环境读取，不写入记录。复用 `outputs/groq/quota.json` 全历史账本和第五轮已授权的免费配额策略：25 RPM、7000 TPM、最小间隔 3 秒、最长单次等待 60 秒，服务端实际额度优先。字节保守预留不是实际 token；请求可能按一分钟一个排队。保持既有账户/模型/端点，不升级付费。

连接建立前失败或明确可重试 HTTP 最多重试两次；已收到的回答不重生成；读写超时或崩溃留下 inflight 标记，禁止自动重发。长配额重置按失败凭据暂停，之后运行同一 `extract` 命令可续跑。不要删除 inflight 以强行重试；需先检查账本和是否已收到响应。用量是 token/观察时间，不是独立核验的账单金额。
