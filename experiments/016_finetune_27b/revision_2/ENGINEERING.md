# 工程验收记录

本页区分已完成的工程验收与仍需正式评测完成才能确认的检查。训练效果以最终 `results/RESULTS.md` 为准，不以损失下降或烟测成功代替。

**一项验收未完全通过：** 全量 pytest 的三个历史检查读取了原始全集/原测试文件。原因、范围与处理见 [DEVIATIONS.md](DEVIATIONS.md)。下列测试通过不等于原测试封存要求通过。

| 检查 | 已取得的证据 |
|---|---|
| 整轮工作流严格封存原测试 | 未完全通过：全量工程测试发生了结构及去重检查读取；27B 模型流程仍只使用开发数据 |
| 开发数据划分可重复、互斥、场景组完整 | 冻结清单及工程测试；只部署两份开发集 |
| 修订 2 在无原测试文件副本中运行 | 35 项通过、1 项因本地无 torch 跳过；已确认导入根目录位于副本且不存在原始全集/原测试文件 |
| 理由审核与输入隔离 | 902 条全部审核，728 条进入监督；冻结校验只允许 evidence、claim 进入提示词 |
| 完整原始 27B 可训练 | 单卡烟测通过，最长完整序列 851 tokens，覆盖三个标签，峰值 52.58 GiB |
| 回答损失掩码 | 实际 torch 梯度核验：提示 token 不承担监督损失，答案含 EOS 承担损失 |
| 仅 LoRA 更新、关闭适配器恢复基线 | 完整 27B 实测通过；主干 BF16 冻结，160 个投影模块、15,466,496 个 LoRA 参数 |
| 保存重载与优化器/RNG 恢复 | 完整 27B 保存重载 logits 一致，恢复后的额外更新与连续更新在规定容差内一致 |
| checkpoint 文件与数据游标 | 三种子首批、第一轮末、第三轮末 checkpoint 均核验通过，第三轮游标均为 728；三个训练完成回执已生成 |
| 生成结果去重与失败计错 | 工程测试覆盖；验证基线的 259 条原始回答原样保留，2 条截断计错 |
| 验证基线输入 token | 全部 259 条重新 tokenization 后，输入哈希逐条一致；无 thinking 输出、无缺理由 |
| 精确组检验 | 工程测试中与小规模穷举一致；最终结果另有独立卷积复算入口 |
| 异常后服务恢复 | 实际非零退出路径恢复成功，模型列表与固定短请求通过；孤儿进程清理测试通过 |
| 软件检查 | 289 项通过，1 项因本地无 torch 跳过；该损失掩码检查另在服务器实际通过 |
| 本地复算保留原始文件 | 新增测试验证下载文件字节不变并拒绝目录重叠；连同两项原有审计测试，3 项通过 |

正式实验已于北京时间 2026-10-31 03:09 完成：三个种子各训练三轮、各生成 777 条验证回答，选中轮次分别为 3、3、2；261 条开发保留样本的四臂评估共保存 1,044 份回答。三个选中适配器及日志已下载，验证选型与最终指标独立复算均通过，下载原文件字节保持不变。服务已恢复，2026-10-31 再次检查模型列表与固定短请求通过。

工程流程完成不等于效果验收通过。挑战集平均准确率提高 25.77 个百分点，精确组检验 p=0.0000152587890625；但三个种子的挑战集 REFUTES 召回均从 100% 降至 89.47%，超过预设最多下降 5 个百分点的限制，整体效果标准未通过。另保留上文原测试封存偏差，不能宣称全部工程要求满足。完整结果见 [RESULTS.md](results/RESULTS.md)。

证据索引：

- [工程测试](acceptance/engineering_tests.json)
- [无原测试文件的隔离检查](acceptance/no_original_files_tests.json)
- [部署依赖补包](acceptance/package_dependency_repair.json)
- [仅报告披露的修订](acceptance/report_disclosure_revision.json)
- [本地复算回归测试](acceptance/local_recompute_tests.json)
- [完整 27B 烟测](acceptance/full_27b_smoke.json)
- [损失掩码](acceptance/loss_mask.json)
- [首批 checkpoint](acceptance/first_checkpoints.json)
- [第一轮 checkpoint](acceptance/epoch_1_checkpoints.json)
- [第三轮 checkpoint](acceptance/epoch_3_checkpoints.json)
- [验证基线完整性](acceptance/validation_baseline_integrity.json)
- [异常路径服务恢复](acceptance/service_failure_recovery.json)
- [孤儿进程清理](acceptance/orphan_cleanup.json)
- [起草结束后的服务恢复](acceptance/draft_service_recovery.json)
- [环境包清单](acceptance/environment_packages.json)
- [正式完成回执](results/completion.json)
- [验证选型独立复算](results/selection_integrity.json)
- [保留评估本地独立复算](results/local_recompute.json)
- [服务再次健康检查](acceptance/final_health_check.json)

当前运行状态通过 [RUNBOOK.md](RUNBOOK.md) 中的状态入口查询。二进制、原始逐次运行回执与日志保留在忽略目录，最终公开文本结果由收尾入口校验后生成。
