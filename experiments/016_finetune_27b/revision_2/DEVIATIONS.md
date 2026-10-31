# 原测试封存偏差

2026-10-30 12:38 UTC 检查工程测试源码时，确认此前全量 `python -m pytest -q` 执行了三个历史测试，读取了原始全集及原测试文件。这是 Agent 选择工程测试范围过宽造成的疏漏，违反了本轮“原测试继续封存”的要求，不能宣称整个 Agent 工作流从未读取原测试内容。

这三个检查位于 `tests/test_experiment.py`，分别检查历史提示词示例与原始全集去重、pilot 场景组与原测试组互斥、烟测样例与原始全集去重。它们读取 JSONL 内容并在 Python 内比较字段。该次 pytest 的输出是通过/跳过汇总，没有输出逐题原测试记录；该事实不能消除文件已被读取的偏差。

本次 27B 模型的训练、checkpoint 选型和保留评估仍只使用冻结开发数据。原测试数据未被部署到正式模型工作目录，也未参与本次 27B 模型调用。训练数据、理由、模型计算代码、超参数、选型及统计标准保持冻结；本次检查仅查看历史测试源码和已有测试回执，没有再次读取原测试数据。

原有 `data_freeze.json`、`training_freeze.json` 等文件保持原字节和哈希。它们的 `original_test_content_read: false` 只能描述对应准备/冻结函数的读取范围，不能外推为完整工程流程从未读取原测试。整轮工作流的访问披露以 [data_access_audit.json](data_access_audit.json) 为准。

处理措施：

- 后续仅执行本轮明确列出的工程测试，并在不含原测试文件或原始全集的副本中验证。
- 最终报告与审计回执明确标记封存要求未完全通过；数值指标即使达标，也不宣称全部工程验收通过。
- 报告脚本仅修改访问披露，不改变生成、训练、选型、解析、指标或统计检验代码。修改前版本保存在 `report_revisions/audit_before_access_disclosure.py.txt`，版本变化另有哈希记录。

已有开发保留结果仍可用于比较固定提示词下的微调效果，但这项流程偏差必须与结果一起交付。未通过严格封存验收的事实不会被后续隔离测试覆盖或抹除。

## 隔离检查与部署补包

不含原始全集/原测试文件的副本中，修订 2 检查结果为 35 项通过、1 项因本地缺少 torch 跳过；相应真实梯度检查已有服务器回执。检查过程中修正了测试副本的临时目录权限及依赖清单问题，失败日志保留在忽略的运行目录。

该检查同时暴露正式部署包遗漏共享依赖 `src/ab_factcheck/splitting.py`，会使后续指标模块导入失败。补入的是原工程验收时同一版本，SHA-256 为 `32be3ee4dd589c7aa02c0b9c1d459e227ff25870f10ace901e9acf87231ddba1`；未修改该文件实现。补包发生在 checkpoint 验证评分之前，修复过程核对冻结计算文件和训练冻结哈希保持一致。该修复不改变提示词、训练、生成、标签集合、选型或统计规则。

实际补包和报告修订回执分别见 [package_dependency_repair.json](acceptance/package_dependency_repair.json) 与 [report_disclosure_revision.json](acceptance/report_disclosure_revision.json)。原报告脚本 SHA-256 为 `3828dde269950edbf8a6c1dc97ba7e7abc96c5a0213eb6a5f6949293e84ab72e`，披露修订后为 `21c8c0e907844fb91012d6794c5c8e73966aaf323e5ebe44a08273b79a33e9cb`；训练冻结哈希仍为 `50bea167e2ec5e748ce96c17aa23f74d694272d81cf30deb8cf64324b7f0a4dc`。
