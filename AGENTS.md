# Agent 工作入口

- 2026-11-03 一天版已于北京时间11:26完成并通过本机独立复算，API已恢复。见 experiments/018_fusion/QUICK24_COMPLETION.json 和 quick24_results/ASSESSMENT.md。无需再轮询或重启实验；原完整版延期项不计完成。后续例行heartbeat应保持安静；若automation_update可用，删除已完成监控automation，否则不得声称已删除。

- 2026-11-02 用户已要求“立刻执行”一天版，已切换并实测运行 manage_fusion_v18_quick24.py；优先读 experiments/018_fusion/QUICK24_AMENDMENT.md 与 RUNBOOK 末尾。新目录 fusion_v18_quick24_runs；不得自动重启旧全量/priority控制器。固定epoch3、35验证配置、13开发配置，2026-11-03北京时间14:55停止计算/15:55交付。监看同时确认deadline_alive；截止后不得为了补齐原计划继续运行。

- 2026-11-01 用户要求优先看融合效果：当前控制器为 manage_fusion_v18_priority.py；独立排程清单 experiments/018_fusion/priority_schedule.json。先生成完整259题阶段验证报告，再自动回到原完整流程；不要误把中间报告当最终推荐。恢复及收集见 RUNBOOK 末尾。

- 本工作树执行 V18 三方法融合，先读 `experiments/018_fusion/README.md` 和 `RUNBOOK.md`。仅处理冻结的 728 条训练、259 条验证、261 条开发比较数据；不读取原始全集或原测试集。
- 三套解释共 2184 条必须逐条审核并通过 `freeze-reviews` 后才能训练；教师一致或预测正确不能自动视为审核通过。教师阶段完成后停止，先恢复 API，再开展审核。
- 不覆盖 V16/V17 冻结材料。V18 `freeze.json` 固定输入，`runtime.json` 固定实际执行代码；修改已运行配置或源码必须显式留存修订和影响，不混用运行身份。
- V18 隔离测试：`PYTHONPATH=src python -m pytest -q tests/test_fusion_v18.py tests/test_unified_v17.py tests/test_finetune27b_service_guard.py`。禁止全项目 pytest。

- V16 历史依赖见 [实验协议](experiments/016_finetune_27b/revision_2/PROTOCOL.md)。V18 复用经审核的 `_v2` 计算实现；旧版仅标签监督及原测试评测代码不用于本轮。全部训练理由须逐条审核完并冻结后才可训练。
- 本轮不要执行全项目 pytest：三个历史测试会读取原始全集/原测试文件。已发生的一次全量执行必须如实披露，见 [封存偏差](experiments/016_finetune_27b/revision_2/DEVIATIONS.md)；后续使用 RUNBOOK 中的隔离测试入口，不得用后来通过的测试抹除该偏差。

- 服务器 SSH 登录、凭据位置和可直接运行的连接检查：先读 [docs/server_ssh.md](docs/server_ssh.md)。2026-10-30 已实测 `root@10.176.30.103:20024` 密码登录成功。
- SSH 密码保存在本机 `F:/Personal/Code/A_B/.env.ssh.local`，已由 Git 忽略；不要打印密码或写入受版本管理的文件。其他工作树可复用此路径。
- 连接时使用 [configs/server_ssh_known_hosts](configs/server_ssh_known_hosts) 固定核验主机公钥；主机密钥不匹配时先核实原因。
- 模型 HTTP API 使用不同端口及凭据，见 [docs/qwen38_server_api.md](docs/qwen38_server_api.md)。
- 项目概况和数据使用约定见 [README.md](README.md)。
- 如开展权重微调，先读 [可行性评估](docs/finetuning_feasibility.md)：包含开发数据与测试暴露边界、昇腾资源快照及标签监督方案；其中建议尚未经过训练验证。
