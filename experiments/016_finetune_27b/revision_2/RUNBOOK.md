# 修订 2 执行与恢复入口

工作树：`F:/Personal/Code/A_B_finetune_27b`，分支 `codex/finetune-27b-baseline`。凭据仅从忽略文件读取，连接说明见仓库 `docs/server_ssh.md`。

## 已授权的执行边界

用户已授权暂停现有 27B 推理服务，以设备 0、2、3、4、5 并行起草，并以独立单卡运行三个训练种子；结束或失败后恢复原服务。设备 1 的其他占用不处理。在服环境不升级。原测试文件不部署、不评测。

## 审核与冻结

在工作树中运行：

```powershell
python scripts/remote_finetune.py python scripts/status_finetune27b_v2.py
python scripts/sync_finetune27b_v2.py --verify-all
python scripts/review_finetune27b_v2.py --pending --count 20
python scripts/append_finetune27b_reviews.py <逐条审核决策文件>
```

每条初稿都必须由 Agent 阅读证据、陈述和金标后明确撰写决策。不能以模型预测是否正确自动审批。已有决策需调整时用 `--amend`，历史和原稿保留。全部 902 条有决策后才能调用 tokenizer 审计和冻结；整组排除不会减少审核覆盖要求。

部署命令只打包两个开发集：

```powershell
python scripts/package_finetune27b_v2.py
python scripts/remote_finetune.py upload outputs/finetune27b_v2.tar.gz /root/ab_finetune27b_20261030/setup/finetune27b_v2.tar.gz
python scripts/remote_finetune.py python scripts/deploy_finetune27b_formal.py
```

`revision_2_workspace` 保留实际起草代码；`revision_2_formal_workspace` 是正式训练代码。部署不会覆盖起草目录，也不会在起草服务恢复前替换运行中的 guard。最终冻结完成后需重新打包部署；正式训练开始后拒绝改变部署内容。

将审核和历史上传到远端忽略的运行目录。使用正式工作目录、`PYTHONPATH=src`、隔离 `venv/bin/python` 运行：

```text
python -m ab_factcheck.finetune27b_run_v2 audit-tokens --model /root/ab_finetune27b_20261030/models/Qwen3.8-27B --output <审计目录> --reviews <reviews.jsonl> --drafts /root/ab_finetune27b_20261030/revision_2_runs/rationale_drafts/drafts --world-size 1
python -m ab_factcheck.finetune27b_v2 freeze --reviews <reviews.jsonl> --drafts <drafts目录> --token-audit <token_audit.json>
```

冻结文件需同步本地和远端，哈希必须相同。冻结包括审核历史、全部初稿及原起草代码。若单卡正式烟测失败，应先查实际错误；仅显存不足时按协议进行两卡 FULL_SHARD 验收并另存执行修订，不允许跳过验收或更换精度、模型、提示词。

## 正式运行

本轮工程测试仅使用隔离入口：

```powershell
F:/Personal/Code/A_B/.venv/Scripts/python.exe scripts/check_finetune27b_test_isolation.py
```

该入口按明确清单复制本轮代码、测试和两个开发集，验证副本中不存在原测试或原始全集，并确认导入根目录位于副本后运行五个修订 2 测试文件。不要运行全项目 pytest：此前已发生的历史检查读取偏差见 [DEVIATIONS.md](DEVIATIONS.md)，后来隔离测试通过不能抹除该偏差。

确认起草完成、恢复服务回执通过、训练冻结通过后：

```powershell
python scripts/remote_finetune.py python scripts/start_finetune27b_formal.py
```

控制器依次执行完整 27B 烟测、暂停服务、三个种子训练和共享基线验证、三个种子验证选型、恢复服务，然后在设备 0 上用同一加载对象进行四组保留评估，最后离线复算并生成 `RESULTS.md`、`results.json`、`audit.json`、`predictions.csv`。

正式输出：`/root/ab_finetune27b_20261030/revision_2_runs/formal`。控制器日志：`logs/revision_2_formal_controller.log`；各阶段日志：`logs/revision_2_<action>_<seed>.log`。状态入口同上。结果未生成时，不得将代码测试通过或初步反向探针称为正式实验完成。

三个种子选型全部完成后，可只读复算验证集准确率、Macro-F1、各类召回、限制判断和 checkpoint 排序，并检查全部候选的 LoRA 配置在忽略目标模块集合序列化顺序后相同：

```powershell
python scripts/remote_finetune.py python scripts/check_finetune27b_selection.py
```

该检查保留收到的原始回答，不重新生成答案；回执为 `formal/selection_integrity.json`，随最终文件收集。

完整流程和服务器离线审计完成后，收集及本地复算：

```powershell
python scripts/collect_finetune27b_v2.py --publish
python scripts/recompute_finetune27b_v2.py outputs/finetune27b_v2/completed/formal
```

收集入口要求三个种子训练、选型、1044 份保留回答、最终审计和服务恢复均已完成；再次核验当前服务 PID/启动时间、模型列表及固定短请求，再按远端 SHA-256 校验所有文本回执、日志和三个选中适配器。适配器保存在忽略的 `outputs/finetune27b_v2/completed/formal/seed-*/checkpoint-*/`，优化器及原始模型权重继续留在服务器。公开报告、逐题 CSV、选型记录和文件清单位于本目录 `results/`。收集不会读取私有服务快照，HTTP 凭据仅由服务器健康检查函数本地读取，绝不下载或输出。

本地自动收尾入口为 `python scripts/finish_finetune27b_v2.py`，支持单实例锁。它每分钟只读查询服务器，待远端最终审计及服务恢复通过后收集文件、独立复算，并检查与服务器审计完全一致。状态写入忽略的 `outputs/finetune27b_v2/completion_status.json`；成功后生成公开 `results/completion.json`。连接中断会继续等待，远端控制器提前退出或本地校验失败会标记 `requires_attention`，不会宣称完成。若本机睡眠或关闭，服务器训练与恢复仍由远端控制器负责；恢复本机后可重启此收尾入口。

用户明确只考虑 Codex 原生定时任务，因此临时创建的 Windows 计划任务已撤销，相关安装脚本也已移除。当前会话没有可用的 Codex 定时任务工具，不存在自动唤醒聊天或桌面通知。实验仍由远端控制器运行，本地轻量收尾进程负责查询、下载和独立复算；不需要持续占用 Agent 对话轮询。收尾入口增加了 `--once` 可供手动单次查询，不注册任何定时任务。完成前还会独立复核三个种子的验证选型。

本地复算会把所需文本输入按原字节复制到 `completed/local_audit/`，在那里生成审计输出并检查原始下载文件的哈希未变；这样 Windows 换行不会重写已核验的服务器回执。直接调用底层 `audit_finetune27b_v2.py` 会在指定目录写报告，核验下载包时应使用上面的独立复算入口。

## 中断与恢复

checkpoint 每 8 个更新及每轮末保存。再次运行同一启动入口会核对冻结、代码、环境、模型和 checkpoint 哈希，然后恢复数据游标及优化器/RNG；最多重放尚未保存的 7 次更新。已经收到的生成结果永不重试替换，错误及失败仍计入分母。

服务 guard 的完整 argv/env/cwd 快照位于远端 `private/guard-*`，包含秘密，不下载、打印或提交。新 guard 的 `current_service.json` 记录恢复后的 PID 和启动时间。需手动中断时，应定位本任务记录的 guard PID 并发送 SIGTERM，让 finally 和 watchdog 清理本任务进程组、恢复并健康检查；不能按进程名批量 kill。

本轮已实测非零退出后的服务恢复及固定短请求，并实测监督进程先退出后的孤儿进程清理；公开回执在 `acceptance/`。完整 27B 正式验收以 `formal/smoke/receipt.json` 为准。
