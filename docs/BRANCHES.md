# 方法分支与历史实验

## 当前导航（2026-11-04）

| 分支 | 内容 |
| --- | --- |
| [codex/nli](https://github.com/Loong-C/FDU-Cognitive-Intelligence/tree/codex/nli) | V1–V15，服务器接入文档和[汇报材料](presentation_20261103/README.md) |
| [codex/finetune-27b-baseline](https://github.com/Loong-C/FDU-Cognitive-Intelligence/tree/codex/finetune-27b-baseline) | V16 微调与 V17 统一 BF16 比较 |
| [codex/fusion-v18](https://github.com/Loong-C/FDU-Cognitive-Intelligence/tree/codex/fusion-v18) | V17 依赖材料，V18 原计划、排程修订、逐条审核及一天版最终结果 |
| [codex/import-pj-materials-20261029](https://github.com/Loong-C/FDU-Cognitive-Intelligence/tree/codex/import-pj-materials-20261029) | PJ 外部历史材料 |

各分支分别提交和推送，保留原有实验边界。V18 一天版已完成；原完整版延期项不计完成。V16/V17/V18 使用历史开发数据，不能称作独立盲测。具体结论见各分支报告，本次整理不重新调用模型。

本地目录和结果入口见[工作树位置](worktree_locations.md)。`worktrees/` 不作为嵌套仓库加入主分支。

## 历史整理记录

2026-11-03 本地目录更新：微调、融合和 PJ 材料三个工作树已从 `A_B` 同级移入 `A_B/worktrees/`，分支与未提交修改保留。新路径见 [工作树位置](worktree_locations.md)。下文是 2026-10-29 的历史分支整理记录。

2026-10-29 按用户要求，将按轮次拆分的分支合并为两条方法路线。

| 保留分支 | 用途 |
| --- | --- |
| `codex/nli` | 默认分支；保留 V1–V14 历史实验，并提交 V7–V14 的代码、配置、提示词、指标与审计。当前推荐通用单次 NLI。 |
| `codex/import-pj-materials-20261029` | 保留已有 PJ 阶段报告、冻结提示词、原版脚本和复现材料；保留原分支名及其独立工作树。 |

原 `main`、`codex/14b-nonthink-v3`、`codex/groq-27b-v4`、`codex/layered-world-v5`、`codex/symbolic-z3-v6` 均是 NLI 分支历史的祖先。清理的是冗余分支引用，既有提交、历史实验和失败结果仍可从保留分支追溯，不重写实验记录。

整理前的本地分支记录和完整 Git bundle 保存在被忽略的 `outputs/branch_consolidation_20261029/`。该目录不推送远端。密钥、模型权重和原始运行响应同样不进入本次提交；NLI 的原始运行缓存仍在当前仓库 `outputs/` 下。冻结报告、代码与所需的开发清单进入 Git，冻结文件的原始换行字节保持不变。

NLI 当前结果入口：

- [跨轮次结果总览](../experiments/server_summary/RESULTS.md)
- [方法定义与证据边界](server_nli_method.md)
- [最终请求模板](../experiments/server_summary/recommended_method.json)
- [V13 独立开发确认](../experiments/013_binary_bilingual/RESULTS.md)

PJ 路线保留的是外部历史全量开发评估，来源数据已用于优化，其中包含本仓库划分里的测试样本。它不能作为本次 NLI 方法的独立确认或测试结果，也不参与本次 NLI 方法选择。

这次分支整理不重新运行模型、不重新评估测试集，也不把两条路线的分数合并。
