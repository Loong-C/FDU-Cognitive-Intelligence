# Agent 工作入口

- 本工作树当前执行 27B 微调修订 2，先读 [实验协议](experiments/016_finetune_27b/revision_2/PROTOCOL.md)。使用 `_v2` 入口；旧版仅标签监督及原测试评测代码为历史草稿，不用于本轮。全部训练理由须逐条审核完并冻结后才可训练。
- 本轮不要执行全项目 pytest：三个历史测试会读取原始全集/原测试文件。已发生的一次全量执行必须如实披露，见 [封存偏差](experiments/016_finetune_27b/revision_2/DEVIATIONS.md)；后续使用 RUNBOOK 中的隔离测试入口，不得用后来通过的测试抹除该偏差。

- 服务器 SSH 登录、凭据位置和可直接运行的连接检查：先读 [docs/server_ssh.md](docs/server_ssh.md)。2026-10-30 已实测 `root@10.176.30.103:20024` 密码登录成功。
- SSH 密码保存在本机 `F:/Personal/Code/A_B/.env.ssh.local`，已由 Git 忽略；不要打印密码或写入受版本管理的文件。其他工作树可复用此路径。
- 连接时使用 [configs/server_ssh_known_hosts](configs/server_ssh_known_hosts) 固定核验主机公钥；主机密钥不匹配时先核实原因。
- 模型 HTTP API 使用不同端口及凭据，见 [docs/qwen38_server_api.md](docs/qwen38_server_api.md)。
- 项目概况和数据使用约定见 [README.md](README.md)。
- 如开展权重微调，先读 [可行性评估](docs/finetuning_feasibility.md)：包含开发数据与测试暴露边界、昇腾资源快照及标签监督方案；其中建议尚未经过训练验证。
