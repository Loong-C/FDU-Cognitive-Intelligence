# A/B 对抗事实核查项目

B 组模型设计与优化仓库。任务是根据英文 `evidence` 判断 `claim`，输出
`SUPPORTS`、`REFUTES` 或 `NOT ENOUGH INFO`。
当前已完成仓库初始化和开发集 / 测试集划分，尚未实现模型训练或推理。

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

需要 Python 3.10 或以上版本，当前划分和测试只使用 Python 标准库，无需安装第三方依赖。
在仓库根目录运行：

```powershell
# 校验原始文件哈希、冻结划分和统计报告，不修改文件
python scripts/split_dataset.py --check

# 运行测试
python -m unittest discover -s tests -v

# 生成缺失的划分文件；已存在且一致的文件保持不变
python scripts/split_dataset.py
```

后续开发可选择建立本地环境并安装项目：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
```

## 开发约定

- 原始数据保存在 `data/raw/`，不要手工修改；划分结果通过脚本生成。
- 开发集用于方案设计、调试、提示词调整和模型选择。若开展训练，在开发集内部再按组划分训练 / 验证数据。
- 测试集保留到方案冻结后的最终评测，不据此反复调参或选择方案。
- 每个数据集分别报告准确率和三类召回率；核心挑战集进一步按机制统计，并关注 NEI 召回率。
- 实验说明与可复现配置放入 `experiments/`；日志、逐条预测和权重放入 `outputs/`。
- 原始数据、冻结划分、清单和报告均纳入 Git，便于复现。不要提交密钥或模型权重。

课题原文要求使用开源模型，且训练部署模型小于 30B；完整要求见
[选题说明](docs/references/AB对抗组选题说明.docx)。
