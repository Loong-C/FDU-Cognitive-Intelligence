# V18 操作入口

工作树：`F:/Personal/Code/A_B_fusion_v18`；远端：`/root/ab_finetune27b_20261030/fusion_v18_workspace` 与 `fusion_v18_runs`。

本机 PowerShell 设置 `$env:PYTHONPATH='src'`。SSH 通过 `scripts/remote_finetune.py`，复用原凭据位置与固定主机公钥；不打印凭据。

## 准备与测试

```text
python -m ab_factcheck.fusion_v18 verify
python -m pytest -q tests/test_fusion_v18.py tests/test_unified_v17.py tests/test_finetune27b_service_guard.py
python scripts/package_fusion_v18.py
```

包只包含显式列出的代码和开发数据。部署不会覆盖已有但内容不一致的文件；代码冻结后不得静默重新打包不同实现。

远端管理器支持 `deploy`、`launch --phase teachers`、`status`、`launch --phase experiment`。`launch` 只在服务身份匹配且无活跃控制器时启动；用户已经批准本计划及沿用 API 暂停/恢复安排。

## 进度与收集

```text
python scripts/collect_fusion_v18.py status
python scripts/collect_fusion_v18.py collect --phase teachers
```

教师阶段目标 2184 份答案，另有六次最长输入烟测。阶段完成会自动恢复 API 并生成 `teachers_complete.json`、`service_recovery_teachers.json` 和下载包。它不会自动开始训练。

## 逐条审核

收集回执 `outputs/fusion_v18_collection/latest_teachers.json` 给出本地 received 路径。按小批量输出审核包：

```text
python scripts/review_fusion_v18.py --output <received目录> --start 0 --count 5
```

每个 source/key 恰好一条 JSONL 决定，字段为 `source`（nli/pj/joint）、`key`、`draft_sha256`、`decision`（accept/revise/fallback）、`rationale`、`evidence_quote`、`review_note`、`reviewer`。quote 必须来自当前 evidence；理由最多 60 个英文词，不含 Verdict。accept 必须逐字匹配正确教师理由，fallback 必须逐字匹配原审核理由，revise 记录实质修改。预测正确不自动代表审核通过。

```text
python -m ab_factcheck.fusion_v18 freeze-reviews --reviews <2184条决定JSONL> --output <received目录>
python scripts/package_fusion_v18.py
```

部署新增的 supervision 冻结文件后，远端执行 `launch --phase experiment`。该阶段依次完成新验证基线、三套完整烟测、九次训练、27 个 checkpoint 验证、全方法验证、审计和推荐冻结、全方法开发比较与审计，然后自动恢复 API。

## 最终复算

```text
python scripts/collect_fusion_v18.py collect --phase experiment
```

收集器保留接收字节及哈希清单，在独立副本重新生成指标，并用独立解析器/混淆矩阵/组检验复算；服务器与本机结果一致、API 恢复通过后才发布到本实验 `results/`。

若资源失败：先检查控制器、阶段日志及恢复回执；不处理其他进程。`archive-unanswered` 仅在控制器停止后归档未完成尝试，保留已收到回答和未知成本记录，再启动原阶段。冻结哈希不同则拒绝恢复，不能绕过验证。

运行时长由前几十条实际生成速度估算；教师和训练审核是两个不同阶段。无需人工盯守时报告 ETA 并结束会话，之后再继续审核和后续阶段。


## 正式实验只读监看（审核已于 2026-11-01 冻结）

    python -W ignore scripts/remote_finetune.py python scripts/probe_fusion_v18_experiment.py --timeout 30

该入口是独立只读观察器，不属于冻结运行代码。检查 running、worker_failure、训练 smoke_passed/complete/selected、两个矩阵及 API recovery；完整结束后仍需 collect --phase experiment 复算。不要重新审核或覆盖已冻结 supervision；存在修订需求时必须另行保留版本与影响。

审核辅助脚本 author_fusion_v18_reviews.py 和 amend_fusion_v18_reviews.py 只用于冻结前逐条决定的机械落盘和检查。它们不自动作语义判断。16项冻结前更正的原件在 review_amendments/，当前有效决定为 reviews.jsonl。


## 2026-11-01 排程修订：先产出融合结果

见 PRIORITY_AMENDMENT.md 与 priority_schedule.json。优先流程不改变冻结计算实现，按 seed42、three_seeds、direct_all、fusion_all 顺序生成完整259题验证报告，然后自动回到原完整流程。初始种子42固定，阶段报告不冻结最终推荐，不作不完整Holm检验。

新的启动/恢复入口（远端；确认旧控制器已停、API已恢复，且未收到的中断调用已按原协议归档）：

    /root/ab_finetune27b_20261030/venv/bin/python /root/ab_finetune27b_20261030/fusion_v18_workspace/scripts/manage_fusion_v18_priority.py launch

阶段报告查询仍使用 probe_fusion_v18_experiment.py，读取 priority.stages。阶段完成后可在完整实验仍运行时收集：

    python scripts/collect_fusion_v18_priority.py --stage seed42

收集器下载该阶段报告与对应原始调用，在独立副本复算、严格解析并核对哈希后发布到 priority_results/<stage>。此中间收集无需停止实验或恢复API。最终完整交付仍走 collect_fusion_v18.py collect --phase experiment。


## 2026-11-02 已授权的一天版（优先于上面的旧恢复入口）

用户明确要求立刻执行ONE_DAY_PLAN_20261102.md。细节见QUICK24_AMENDMENT.md，冻结清单quick24_schedule.json。不要重新启动manage_fusion_v18.py或manage_fusion_v18_priority.py；旧controller停止是有意切换，不代表需要恢复原全量排程。

只读监看（本地）：

    python -W ignore scripts/remote_finetune.py python scripts/probe_fusion_v18_experiment.py --timeout 30

观察器在quick24 controller存在时自动转向新目录。也可直接远端运行：

    /root/ab_finetune27b_20261030/venv/bin/python /root/ab_finetune27b_20261030/fusion_v18_workspace/scripts/manage_fusion_v18_quick24.py status

检查running、deadline_alive、deadline_ready、active_jobs、training、coverage、worker_failure及service_recovery。14:55计算截止，15:55交付截止（11月3日北京时间），到期不重启继续耗时。

结束后本机收集并复算（PowerShell先设PYTHONPATH=src）：

    python -W ignore scripts/collect_fusion_v18_quick24.py

完整或截止部分结果发布到experiments/018_fusion/quick24_results。收到失败/截断不重抽；无原全量experiment_complete标记。服务器delivered.json证明计算停止、API恢复请求验证和归档完成；本机独立复算后才声明本机最终交付已验证。
