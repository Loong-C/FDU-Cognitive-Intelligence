# 2026-11-03 汇报材料

| 材料 | 入口 |
| --- | --- |
| 最终英文汇报 PDF | [Adversarial_Fact_Verification_Beamer.pdf](Adversarial_Fact_Verification_Beamer.pdf) |
| Beamer 源码及编译方法 | [beamer/README.md](beamer/README.md) |
| 内容方案 | [PPT内容方案.md](PPT内容方案.md) |
| 逐页排版提纲 | [PPT逐页排版提纲.md](PPT逐页排版提纲.md) |
| 图表数值与来源哈希 | [chart_data.csv](chart_data.csv)、[figure_sources.json](figure_sources.json) |
| 图表生成脚本 | [generate_figures.py](generate_figures.py) |
| 示例题 | [slide_examples.json](slide_examples.json) |
| A 组参考 PPT | [原始参考材料](../references/Adversarial_Fact_Verification_Midterm_1793104017.pptx) |

`01_unified_accuracy`、`02_recall_tradeoff`、`03_fusion_result` 各提供 PNG 与 SVG。`beamer/assets/` 保存最终演示使用的 PNG/PDF 图表；`beamer/build/` 为本地编译、预览和检查缓存，已由 `build/` 规则忽略。

重新生成图表需 Python、Matplotlib、NumPy，以及 `worktrees/A_B_fusion_v18/` 中的 V17/V18 冻结结果。新克隆可在仓库根目录运行以下命令建立该工作树；已有工作树无需重复创建：

```powershell
git worktree add worktrees/A_B_fusion_v18 codex/fusion-v18
python docs/presentation_20261103/generate_figures.py
```

生成器仅使用既有开发比较结果。各轮评估口径、限制及 V18 延期项应随图表一同说明，见[分支导航](../BRANCHES.md)。来源清单和旧提纲含本机绝对路径，换机器后按[工作树位置](../worktree_locations.md)定位。
