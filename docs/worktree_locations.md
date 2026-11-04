# 本项目的本地工作树位置

2026-11-03 按用户要求，三个原位于 `F:/Personal/Code/` 下的项目辅助目录全部移入 `F:/Personal/Code/A_B/worktrees/`。使用 `git worktree move` 更新 Git 关联；各分支保持独立，未合并或覆盖文件，未提交修改和忽略的输出一并保留。

| 用途 | 旧目录 | 新目录（相对 A_B） | 分支 |
| --- | --- | --- | --- |
| 27B 微调 | `F:/Personal/Code/A_B_finetune_27b` | `worktrees/A_B_finetune_27b` | `codex/finetune-27b-baseline` |
| V17 比较、V18 融合 | `F:/Personal/Code/A_B_fusion_v18` | `worktrees/A_B_fusion_v18` | `codex/fusion-v18` |
| PJ 历史材料 | `F:/Personal/Code/A_B_materials_20261029` | `worktrees/A_B_materials_20261029` | `codex/import-pj-materials-20261029` |

## 当前入口

- [27B 微调结果](../worktrees/A_B_finetune_27b/experiments/016_finetune_27b/revision_2/results/RESULTS.md)
- [V17 同条件比较](../worktrees/A_B_fusion_v18/experiments/017_unified_comparison/ASSESSMENT.md)
- [V18 一天版最终分析](../worktrees/A_B_fusion_v18/experiments/018_fusion/quick24_results/ASSESSMENT.md)
- [PJ 材料说明](../worktrees/A_B_materials_20261029/experiments/imported_pj_20261029/README.md)
- [PPT 内容方案与图表](presentation_20261103/PPT内容方案.md)

以上工作树链接用于本机阅读。远端或新克隆请使用 [V16 微调](https://github.com/Loong-C/FDU-Cognitive-Intelligence/blob/codex/finetune-27b-baseline/experiments/016_finetune_27b/revision_2/results/RESULTS.md)、[V17 比较](https://github.com/Loong-C/FDU-Cognitive-Intelligence/blob/codex/finetune-27b-baseline/experiments/017_unified_comparison/ASSESSMENT.md)、[V18 融合](https://github.com/Loong-C/FDU-Cognitive-Intelligence/blob/codex/fusion-v18/experiments/018_fusion/quick24_results/ASSESSMENT.md) 和 [PJ 材料](https://github.com/Loong-C/FDU-Cognitive-Intelligence/blob/codex/import-pj-materials-20261029/experiments/imported_pj_20261029/README.md)。

在辅助工作树中继续执行 Git 操作即可使用对应分支。主工作树的 `.gitignore` 排除 `/worktrees/`，避免把另外三个完整仓库目录误加为嵌套仓库；这不影响它们自己的版本管理。

冻结实验文件、原始响应与历史报告保持原字节。它们可能仍记载运行当时的旧绝对路径；按上表转换为当前路径读取，不为修复历史链接而改写冻结记录。当前 PPT 文档链接、绘图脚本及图表来源清单已更新为新路径。

迁移核验覆盖 75,724 个文件：文件集合、大小、修改时间及文件身份一致；Git HEAD、未提交状态与 diff 一致；抽取的冻结清单 SHA-256 一致。Git 管理用的 `.git` 指针允许随迁移更新。没有读取原始全集或原测试文件内容来核验迁移。

本地迁移前清单与核验回执保存在 `outputs/worktree_relocation_20261103/`，不纳入 Git。原三个同级目录已经不存在，未保留指向新位置的外部目录链接。
