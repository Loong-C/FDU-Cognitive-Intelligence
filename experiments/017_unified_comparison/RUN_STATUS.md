# 启动与续查记录

## 已完成：2026-10-31 20:27（北京时间）

全部 1566 个评分单元齐全，服务器独立审计通过，本地下载并复算 1599 个文件成功；原收到文件及暂停前回答哈希保持不变。
HTTP API 已恢复，模型列表与短生成健康检查通过。正式入口为 `results/RESULTS.md`、`results/audit.json`、`results/completion.json` 和 `results/resource_service_recovery.json`。
最后的发布核验修正了完成回执的文件哈希引用：服务器 JSON 为 LF，本地重新生成的 JSON 为 Windows 换行，内容数值完全一致。
完成回执现分别记录本地发布结果与服务器原结果的 SHA256，并保存原回执及修正原因；没有改动分数、预测或冻结协议。
后台收集已正常结束，无需继续等待或重启。下方均为过程记录。

## 2026-10-31 16:53 资源故障恢复（当前状态）

11:41（北京时间）worker 1 在 PJ 的 `challenge_e_77ae8814bffc08d4` 上显存不足，保存了 `request_failed/INVALID` 后停止；控制器同时终止另一 worker。
本机收集器 11:42 记录错误后退出，未向用户主动通知。直到用户 16:46 询问时发现，停留在 301/1566（其中 1 条失败），原 17:00 完成估计已失效。
当前 0/1 号卡均有大量本容器不可见占用，不能直接重启到这两张卡。已有 301 条记录与日志完整备份为 `outputs/unified_v17_collection/oom_snapshot.tar.gz`。

用户已明确批准“允许暂停 API，恢复原规模评测”。已核验并暂停原 HTTP 服务，保留私有启动快照，启用独立 watchdog；恢复命令及所有评测 worker 同属一个进程组，异常时可以先清理自身 worker 再恢复 API。
两个 worker 改用同型号 2/3 号卡；启动前各只占约 3460 MiB/65536 MiB，资源预检见 `resource_memory_preflight.json`。
模型权重、推理代码、提示词、生成参数、题目、适配器及统计协议均不变。收到的 OOM 失败不重跑覆盖，仍按错误计分。
另一 worker 没有收到回答的 NLI 请求已归档，用量未知，仅补齐该缺失单元。新恢复记录位于远端 `interruptions/resource_recovery_*/resumption.json`。

新守护控制器 PID 3955942；新 worker PID 3955995（卡 2）、3955996（卡 3）。本机自动收集 PID 78464，日志 `collector_resource_recovery.log` / `.err`。
16:52:56 已增至 305/1566，确认恢复后收到新回答。预计仍需约 4 小时，建议 21:00–22:00 复查；这是耗时估计，不保证完成时间。
服务当前处于用户批准的暂停状态。成功收尾先恢复 API 并通过模型列表与短生成健康检查，再打包结果供本机复算。
最终必须同时核验 `completion.json`、`audit.json`、`resource_service_recovery.json`，并披露两次中断及设备调整。

注意：旧 `manage_unified_v17.py status` 的 `error_tail` 会匹配历史日志里的 OOM；判断当前故障应结合控制器存活、新增记录和 `resource_recovery_controller.log`，不能单凭该历史字段。
资源恢复入口 `scripts/recover_unified_v17_resources.py` 已有单独授权，本次已执行，勿重复 launch。原始冻结文件没有改写。

## 2026-10-31 11:16 恢复原规模

用户先要求减少评测量，随即改为“还是按原样”。为缩减而暂停原控制器后，尚未冻结或执行任何缩减版，已恢复原 261 题、1566 个评分单元。
暂停前收到的 156 个回答全部保留并记录 SHA256；两个没有收到回答的中断请求已归档，成本未知。恢复仅生成缺失单元，原协议、源码、提示词及适配器均不变。
新控制器 PID 3862355。完整暂停/恢复记录位于远端 `interruptions/20261031_user_reversal/resumption.json`，本机副本在本目录 `resumption.json`。
两张卡的新 worker PID 为 3862631、3862632；本机隐藏收集进程已重启为 PID 25364，日志为 `collector_resumed.log` / `collector_resumed.err`。
最终报告与收集回执会披露这次暂停，并再次核验暂停前的全部回答未改动。原 104 题缩减草稿未执行，仅作为被忽略的草稿归档。

2026-10-31 10:52（北京时间）快照：正式回答 32 / 1566，两个 worker 正常；原始权重逐文件校验已通过。
首批各方法耗时外推剩余约 4.4 小时，考虑样本差异建议按 4–6 小时安排，约 15:00–17:00 再检查。
这是早期估计，不是完成回执或准确率结论。用户要求无需盯守时结束会话，届时由用户回来询问。

服务器：`/root/ab_finetune27b_20261030/unified_v17_runs`。
独立部署：`/root/ab_finetune27b_20261030/unified_v17_workspace`。
控制进程 PID 3852718，启动身份由远端 `controller.json` 的 PID/start_time 双重核验。
设备 0/1 运行评测，2–5 原 API 服务未停止。全部条件重新生成，不复用历史答案。

本机隐藏收集进程 PID 89016，身份见被忽略的 `outputs/unified_v17_collection/collector_process.json`。
它每 60 秒保存 `status.json`，远端完成后下载完整包，在独立副本重新计分并审计。
通过后发布到本目录的 `results/`；最终成功必须核对 `results/completion.json` 和 `results/audit.json`。
后台收集依赖本机联网、不休眠；服务器推理不依赖聊天会话继续打开。

只读查询：

```powershell
python -W ignore scripts/collect_unified_v17.py --once
Get-Content outputs/unified_v17_collection/status.json
```

远端查询：

```powershell
python -W ignore scripts/remote_finetune.py exec '/root/ab_finetune27b_20261030/venv/bin/python /root/ab_finetune27b_20261030/setup/manage_unified_v17.py status' --timeout 30
```

如果 `attention.json` 出现或控制进程停止且审计未通过，先检查运行日志，不能直接重跑已有回答。
若本地收集失败，远端原回答仍保存；先修复收集错误，不重跑推理。
已通过 14 项针对性测试及 1566 个模拟回答的完整报告/独立审计；模拟数据在 `outputs/unified_v17_mock_preflight`，不得混入正式报告。
冻结文件和历史 V16 文件不能改写。此次只新增 V17 文件，尚未提交 Git。
