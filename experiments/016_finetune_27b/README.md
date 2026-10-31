# 实验 016：27B 基线提示词微调

当前执行版本为 [revision_2/PROTOCOL.md](revision_2/PROTOCOL.md)，对应用户批准的“三种子、审核理由监督、仅开发数据”方案。根目录旧草稿、配置和冻结记录作为历史保留，不作为本轮运行入口。

执行、恢复和自动收尾见 [RUNBOOK](revision_2/RUNBOOK.md)，已完成的实际模型验收与仍待完成的检查见 [工程验收记录](revision_2/ENGINEERING.md)。

新入口以 `finetune27b_v2`、`finetune27b_run_v2`、`finetune27b_training_v2` 命名。不要调用旧版 `finetune27b_runtime` 的原测试集评测或仅标签训练入口。

连接服务器前读取 [SSH 文档](../../docs/server_ssh.md)。凭据和原始权重不纳入版本控制。
