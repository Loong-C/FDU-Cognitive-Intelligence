# A/B 对抗事实核查项目

B 组模型设计与优化仓库。任务是根据英文 `evidence` 判断 `claim`，输出
`SUPPORTS`、`REFUTES` 或 `NOT ENOUGH INFO`。

本分支 `codex/nli` 汇总 V1–V14 的研究过程，当前推荐 **Qwen-27B 非思考模式的单次通用 NLI**。模型权重不变，使用开发集筛选与独立确认，测试集封存。历史实验和失败结果保留在各轮目录及 Git 提交历史中。

| 方法分支 | 内容与入口 |
| --- | --- |
| [`codex/nli`](https://github.com/Loong-C/FDU-Cognitive-Intelligence/tree/codex/nli)（默认） | 当前分支；[结果总览](experiments/server_summary/RESULTS.md)、[方法说明](docs/server_nli_method.md)、[可复用请求模板](experiments/server_summary/recommended_method.json) |
| [`codex/import-pj-materials-20261029`](https://github.com/Loong-C/FDU-Cognitive-Intelligence/tree/codex/import-pj-materials-20261029) | PJ 材料路线；[阶段报告与复现入口](https://github.com/Loong-C/FDU-Cognitive-Intelligence/blob/codex/import-pj-materials-20261029/experiments/imported_pj_20261029/README.md) |

两条路线保留各自的评估口径。PJ 材料属于外部全量开发评估，不能与 NLI 的独立开发组确认直接混合计分。分支整理说明见 [BRANCHES.md](docs/BRANCHES.md)。

## 目录结构

```text
A_B/
├── configs/
│   ├── data_split.json          # 划分参数、原始数据哈希与输出版本
│   └── experiment.json          # 本地模型与首轮 pilot 的冻结参数
├── data/
│   ├── raw/benchmark_1011/      # 原始数据及原始说明，保持内容不变
│   └── splits/v1/
│       ├── basic/              # 基础能力集 dev.jsonl / test.jsonl / manifest.json
│       ├── challenge/          # 核心挑战集 dev.jsonl / test.jsonl / manifest.json
│       └── report.json         # 数量、分布、完整性与交叉检查
├── docs/
│   ├── references/             # 原有选题文本和课题说明文档
│   └── data_split.md           # 划分规则、数据使用约定及检查结果
├── src/ab_factcheck/            # 可复用 Python 代码
├── prompts/v1/                 # 冻结的 A0/B1/C1 system/user 模板
├── scripts/                    # 命令行入口
├── tests/                      # 数据隔离、完整性和可复现性测试
├── experiments/                # 实验配置与结果摘要，纳入版本管理
├── outputs/                    # 本地日志、预测与权重，忽略其内容
└── pyproject.toml              # Python 项目元数据
```

## 数据划分

目标为 **80% 开发集 / 20% 测试集**，固定种子 `42`。
先按 `mechanism` 分层，再按 `group` 整组划分，同组变体不会跨集合。

| 数据集 | 原始样本 | 开发集样本 / 组 | 测试集样本 / 组 | 测试样本占比 |
| --- | ---: | ---: | ---: | ---: |
| 基础能力集 `basic` | 900 | 720 / 84 | 180 / 21 | 20.00% |
| 核心挑战集 `challenge` | 885 | 702 / 114 | 183 / 29 | 20.68% |

整组划分会使样本比例略有偏差。两个数据集分别开发、分别评测，不合成一个总分。
原始标签及管理字段全部保留；模型输入仅使用 `claim` 与 `evidence`。

详见 [划分说明](docs/data_split.md) 和 [机器可读报告](data/splits/v1/report.json)。

## 快速开始

需要 Python 3.10 或以上版本。原始划分脚本只使用标准库；实验使用 httpx，新增测试使用 pytest。
在仓库根目录运行：

```powershell
# 校验原始文件哈希、冻结划分和统计报告，不修改文件
python scripts/split_dataset.py --check

# 运行原始划分测试
python -m unittest discover -s tests -p test_splitting.py -v

# 生成缺失的划分文件；已存在且一致的文件保持不变
python scripts/split_dataset.py
```

建立本地环境并安装实际验证过的依赖版本：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.venv\Scripts\python.exe -m pip install --no-deps -e .
.venv\Scripts\python.exe -m pytest -q
```

## 内网 Qwen3.8-27B 服务

用户提供的 `http://10.176.30.103:20027/v1` 已于 2026-10-29 验证可调用，模型 ID 为 `qwen38-27b`。
Agent 接入请先阅读 [服务器 API 调用说明](docs/qwen38_server_api.md)，其中包含本机 Key 文件位置、环境变量约定、可直接运行的调用示例和现有客户端兼容性说明。

## 首轮核心实验

配置见 `configs/experiment.json`。保留现有开发集划分，从中按完整组选择挑战集 87 条、
基础集 60 条作为 pilot。A0 为原始直接分类，B1 为双世界零样本，C1 仅增加一个虚构 NEI 示例。
每个条件都使用同一份 Qwen3-4B-Instruct-2507 Q4_K_M 权重和统一推理参数，共 441 条 pilot 请求。

```powershell
.venv\Scripts\python.exe scripts/bootstrap_local.py
powershell -ExecutionPolicy Bypass -File scripts/start_local_server.ps1
# 等待 http://127.0.0.1:8081/health 返回正常后运行
.venv\Scripts\python.exe -m ab_factcheck.cli doctor
.venv\Scripts\python.exe -m ab_factcheck.cli smoke
.venv\Scripts\python.exe -m ab_factcheck.cli run --dataset all --arm all
.venv\Scripts\python.exe -m ab_factcheck.cli report
```

完整的安装、恢复和统计口径见 [实验说明](experiments/001_two_world_pilot/README.md)。
原始响应保存在 `outputs/runs/`，报告保存在 `experiments/001_two_world_pilot/reports/`。
首轮模型推理均通过本地 HTTP 服务完成，无需商业 API key。

首轮已完成 441 条正式推理与 9 条 smoke。实际结果见 [执行结果摘要](experiments/001_two_world_pilot/RESULTS.md) 和 [完整评测报告](experiments/001_two_world_pilot/reports/pilot_qwen3_4b_q4_v1/pilot_report.md)。

第二轮已完成相同 pilot 的 A2/B2/C2 约束 JSON 评测，共 441 条正式请求。新增 Schema 约束、1024-token 预算、世界状态到标签的确定性映射与独立审计，保留第一轮全部历史材料。见 [第二轮结果](experiments/002_constrained_output/RESULTS.md)、[完整报告](experiments/002_constrained_output/reports/pilot_qwen3_4b_q4_struct_v2_r2/pilot_report.md) 和 [运行说明](experiments/002_constrained_output/README.md)。

第三轮已在 RTX 4060 Ti 8GB 与 32GB 内存上完成 Qwen3-14B Q4_K_M 非思考模式的 A14/B14 两组对照，共294次正式生成。采用16/41层CPU/GPU混合卸载，逐字复用第二轮提示词与Schema。挑战集准确率为60.92%/79.31%，基础集为76.67%/80.00%；完整成本、资源限制、错误分析与独立复算见[第三轮结果](experiments/003_model_scaling_14b/RESULTS.md)及[Windows运行说明](experiments/003_model_scaling_14b/README.md)。

第六轮新增一次语义形式化 → JSON AST 校验 → Z3 三分类的独立实验，使用第四轮历史 dev pilot 中冻结的 42 题，并逐题保存语义复核与独立修正 AST。见[第六轮说明](experiments/006_symbolic_z3/README.md)、[结果](experiments/006_symbolic_z3/RESULTS.md)与[错误分析](experiments/006_symbolic_z3/ANALYSIS.md)。

第七轮完成 334 次 Qwen-27B 非思考调用，比较通用 NLI、依据优先、双蕴含判别及盲复核。选出的单次 NLI 在预先冻结的 101 道新开发题上，将基础集从 56/60 提到 60/60、挑战集从 26/41 提到 30/41；14 个分机制/组准确率均不下降，但挑战集 S、R 召回各少对一题。没有检测到显著退步，也尚未证明统计显著优势或测试泛化。详见[第七轮结果](experiments/007_macro_inference/RESULTS.md)和[复现说明](experiments/007_macro_inference/README.md)。

第八轮完成通用正反命题 NLI 一致性过滤的独立开发确认，固定 Qwen-27B 非思考模式。101 道新开发题上，基础集为 59/60（A27 60/60），挑战集为 31/41（A27 26/41）；通过用户允许“不显著退步”的开发筛选，但未通过原先所有点估计不下降的严格门槛，也未证明统计非劣效或测试泛化。216 次确认调用经过独立审计，token 成本约为基线的 2.28 倍。详见[完整结果](experiments/008_negation_consistency/RESULTS.md)和[方法与复现说明](experiments/008_negation_consistency/README.md)。此前[暂停报告](experiments/008_negation_consistency/PAUSE_REPORT.md)保留为历史快照。

第九轮已完成小样本分阶段筛选与审计，新增 168 个响应、63,514 tokens。胜出 NLI 方案在 28 道新开发题上，基础集 14/14（A27 14/14），挑战集 10/14（A27 9/14），修正 1 题且未损害原本正确的题；确认推理 token 为基线的 1.06 倍。样本较小，尚无统计显著优势，字段顺序的因果作用未确立。见[完整结果](experiments/009_small_search/RESULTS.md)及[方案与复现](experiments/009_small_search/README.md)。

第十轮已完成逻辑相容性、保义复述和三候选关系核验的分阶段比较，新增 70 个响应、28,656 tokens，并通过独立审计。三候选核验在初筛表现较好，但扩展至 42 题后为基础集 20/21、挑战集 17/21，低于或持平 V9 的 21/21、17/21；融合只能追平，因此按事前规则停止，未消耗后续 84 次确认调用。当前保留 V9。见[结果与复核](experiments/010_semantic_search/ASSESSMENT.md)及[方案与执行说明](experiments/010_semantic_search/README.md)。

第十一轮已使用用户提供的内网 Qwen-27B API 完成九种宏观候选的筛选、扩展和独立确认，所有基线均在新服务器重跑。203 道新开发题中，NLI 将基础集从 113/120 提到 119/120、挑战集从 56/83 提到 66/83；幅度限制通过，但挑战集单侧组置换 p=0.03125 未达事前 alpha=0.025，故保留为未通过主检验的确认结果。新增 1246 次正式响应、425,523 tokens，原始响应和指标已复算。见[第十一轮结果](experiments/011_server_search/RESULTS.md)。

第十二轮已保持 NLI 方法和参数完成独立复现：另外 306 道开发题、41 个完整新组中，基础集从 164/180 提到 174/180，挑战集从 85/126 提到 92/126；三类召回率均不下降。但挑战集单侧组置换 p=0.015625，未达预先分配的 alpha=0.0125，因此目标仍未标记完成。新增 612 次响应、212,011 tokens，已独立复算；不拼接两轮确认结果重新选择显著结论。见[完整结果](experiments/012_server_replication/RESULTS.md)与[复现协议](experiments/012_server_replication/README.md)。

第十三轮已完成 356 道保留开发题的同期基线对照及独立复算，固定单次 NLI **通过事前主检验与其他指标幅度限制**：基础集 109/120 → 116/120（+5.83 pp），挑战集 134/236 → 161/236（+11.44 pp）；挑战单侧组置换 p≈0.0000124，小于预定 alpha=0.00625。新增 964 次响应、339,928 tokens。基础 NEI 召回下降 2.17 pp、挑战 REFUTES 召回下降 2.78 pp，均在预定 5 pp 限制内；不是所有指标都上升，也不等于证明总体非劣。挑战新确认只含六种机制，没有 SETCLOSE，测试集未读取。见[结果](experiments/013_binary_bilingual/RESULTS.md)、[协议](experiments/013_binary_bilingual/README.md)及[服务器实验总览](experiments/server_summary/RESULTS.md)。

第十四轮完成直接矛盾概率和“简短依据 → 正反二元判断”的旧开发组补充探索，共 126 次响应、33,842 tokens，已独立复算。最好的 proof_pair 为基础 21/21、挑战 18/21，既有 NLI 为 21/21、17/21；没有达到事前挑战至少多对 2 题的扩展标准，按规则停止，不作独立显著性声明。见[结果](experiments/014_semantic_binary/RESULTS.md)及[方案](experiments/014_semantic_binary/README.md)。

通用 NLI 的定义、调用方式及与双世界逻辑的对应关系见[方法说明](docs/server_nli_method.md)。

## 开发约定

- 原始数据保存在 `data/raw/`，不要手工修改；划分结果通过脚本生成。
- 开发集用于方案设计、调试、提示词调整和模型选择。若开展训练，在开发集内部再按组划分训练 / 验证数据。
- 测试集保留到方案冻结后的最终评测，不据此反复调参或选择方案。
- 每个数据集分别报告准确率和三类召回率；核心挑战集进一步按机制统计，并关注 NEI 召回率。
- 实验说明与可复现配置放入 `experiments/`；日志、逐条预测和权重放入 `outputs/`。
- 原始数据、冻结划分、清单和报告均纳入 Git，便于复现。不要提交密钥或模型权重。

课题原文要求使用开源模型，且训练部署模型小于 30B；完整要求见
[选题说明](docs/references/AB对抗组选题说明.docx)。
