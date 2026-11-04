# 文档索引

## 研究与结果

| 内容 | 入口 |
| --- | --- |
| 仓库概况、开发约定 | [项目 README](../README.md) |
| 数据划分与使用边界 | [划分说明](data_split.md) |
| V1–V14 NLI 路线 | [服务器实验总览](../experiments/server_summary/RESULTS.md)、[方法说明](server_nli_method.md) |
| V15 受控合成题比较 | [最终结论](../experiments/015_controlled_comparison/amendment_1/ASSESSMENT.md)、[复现入口](../experiments/015_controlled_comparison/amendment_1/README.md) |
| V16–V18 与 PJ 材料 | [分支导航](BRANCHES.md)、[本地工作树及远端入口](worktree_locations.md) |
| 汇报材料 | [PDF、图表、源码与参考材料](presentation_20261103/README.md) |

## 环境与维护

- [Agent 工作入口](../AGENTS.md)
- [模型 HTTP API](qwen38_server_api.md)
- [服务器 SSH](server_ssh.md)
- [微调可行性评估](finetuning_feasibility.md)：训练前历史评估，执行结果应查 V16 分支。

冻结实验文件、源码和回执按原字节保存，整理目录时不改写哈希引用。历史报告中的旧绝对路径按工作树位置表转换。密钥、权重、原始运行缓存及编译中间文件保存在 Git 忽略目录；克隆仓库不自动包含这些本地文件。
