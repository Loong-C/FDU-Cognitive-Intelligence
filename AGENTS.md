# Agent 工作入口

- 本项目的文件、输出和新增 Git 工作树统一存放在 `F:/Personal/Code/A_B/` 内，不再在其同级目录创建 `A_B_*` 文件夹。现有三个辅助工作树已移至 `worktrees/`，路径与结果入口见 [工作树位置](docs/worktree_locations.md)；操作辅助工作树前继续读取其自身的 `AGENTS.md`。
- 服务器 SSH 登录、凭据位置和可直接运行的连接检查：先读 [docs/server_ssh.md](docs/server_ssh.md)。2026-10-30 已实测 `root@10.176.30.103:20024` 密码登录成功。
- SSH 密码保存在本机 `F:/Personal/Code/A_B/.env.ssh.local`，已由 Git 忽略；不要打印密码或写入受版本管理的文件。其他工作树可复用此路径。
- 连接时使用 [configs/server_ssh_known_hosts](configs/server_ssh_known_hosts) 固定核验主机公钥；主机密钥不匹配时先核实原因。
- 模型 HTTP API 使用不同端口及凭据，见 [docs/qwen38_server_api.md](docs/qwen38_server_api.md)。
- 项目概况和数据使用约定见 [README.md](README.md)。
- 如开展权重微调，先读 [可行性评估](docs/finetuning_feasibility.md)：包含开发数据与测试暴露边界、昇腾资源快照及标签监督方案；其中建议尚未经过训练验证。
