# A/B 对抗事实核查项目

B 组模型设计与优化仓库。任务是根据英文 `evidence` 判断 `claim`，输出
`SUPPORTS`、`REFUTES` 或 `NOT ENOUGH INFO`。
已实现开发集 / 测试集划分，以及本地小模型 A0/B1/C1 提示词对照实验流程。
本轮只做零训练 pilot 推理，封存测试集。

## 目录结构

```text
A_B/
├── configs/
│   └── data_split.json          # 划分参数、原始数据哈希与输出版本
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
所有模型推理均通过本地 HTTP 服务完成，无需商业 API key。

## 开发约定

- 原始数据保存在 `data/raw/`，不要手工修改；划分结果通过脚本生成。
- 开发集用于方案设计、调试、提示词调整和模型选择。若开展训练，在开发集内部再按组划分训练 / 验证数据。
- 测试集保留到方案冻结后的最终评测，不据此反复调参或选择方案。
- 每个数据集分别报告准确率和三类召回率；核心挑战集进一步按机制统计，并关注 NEI 召回率。
- 实验说明与可复现配置放入 `experiments/`；日志、逐条预测和权重放入 `outputs/`。
- 原始数据、冻结划分、清单和报告均纳入 Git，便于复现。不要提交密钥或模型权重。

课题原文要求使用开源模型，且训练部署模型小于 30B；完整要求见
[选题说明](docs/references/AB对抗组选题说明.docx)。
