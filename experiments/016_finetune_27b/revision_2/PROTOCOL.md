# 27B 原始基线提示词微调对照实验，修订 2

本版本替代修订 1 的仅标签监督及原测试集评测行为。目标是在相同原始 Qwen/Qwen3.8-27B BF16、相同 A0 提示词和相同生成路径下，测量监督微调的收益。开发数据已有历史使用，本轮保留集仅指未用于此次训练和选型，不能称为全项目独立盲测。

执行后发现一项工程偏差：全量 pytest 中的历史检查读取了原始全集/原测试文件，严格封存要求未完全通过。详情和影响见 [DEVIATIONS.md](DEVIATIONS.md)。冻结的模型计算、数据、训练和统计标准保持不变；最终报告必须同时披露该偏差。

## 已冻结的控制条件

- 原始权重见上一层 `model_source.json`：固定来源 revision、文件清单、大小和 SHA-256，包括配置、tokenizer 和聊天模板。全部 18 个 safetensors 已完成校验。
- 逐字复用 `prompts/v1/A0_system.txt`、`A0_user.txt` 的有效内容，和旧基线一样只去除文件首尾空白。模型输入只有 system 指令及填入 evidence、claim 的 user 提示，不使用机制、理由、标签、组或管理字段。
- 同一 Transformers/NPU BF16 加载对象关闭适配器为基线、开启适配器为实验组。贪心生成、关闭 thinking、单样本、最多 1,024 新 tokens；不使用 W8A8 服务历史分数作对照。
- 训练种子 42、43、44，各三轮，共用完全相同的审核数据。LoRA rank 8、alpha 16、dropout 0.05，限定语言层的 q/k/v/o_proj、in_proj_qkv、out_proj，实际匹配名称完整写入环境回执。其余参数冻结。
- 完整模型实测匹配 160 个投影模块、15,466,496 个可训练 LoRA 参数。冻结原始主干为 BF16，PEFT 默认保留 LoRA 参数为 FP32；参数实际 dtype 和原始模型 27,356,728,560 个参数均在烟测环境回执中记录。两组使用同一加载对象和计算实现，仅开关适配器。
- AdamW，学习率 1e-4，weight decay 0，恒定学习率，梯度裁剪 1.0，梯度检查点。单卡 micro-batch 1，累积 16；末尾不足 16 的样本保留，按实际样本数归一化，日志记录游标。每条回答先按 token 平均交叉熵，再按样本等权累积。
- 最大序列长度初始为 1536。审核后用真实 tokenizer 检查“完整提示＋理由＋Verdict＋EOS”，超过时在正式冻结前统一提高到下一个 256 倍数。禁止静默截断。只对完整回答（含结束符）计算损失。

## 划分和标注

划分种子 2026103016，按集合和机制保留完整场景组。在 512 个哈希排序候选中，按样本数及每类标签相对 60/20/20 的平方偏差最小选取，同分取较小候选编号；基础集候选 3，挑战集候选 278。

| 划分 | 基础 | 挑战 | 合计 | 场景组 |
|---|---:|---:|---:|---:|
| 训练（审核前） | 480 | 422 | 902 | 124 |
| 验证 | 120 | 139 | 259 | 37 |
| 开发保留评估 | 120 | 141 | 261 | 37 |

`train.jsonl`、`validation.jsonl`、`holdout.jsonl` 逐 ID 冻结于 `data_freeze.json`。完整性校验覆盖原开发数据哈希、ID、场景组、重复 evidence/claim 文本对及原字段一致性。部署包只包含开发数据，运行不依赖原测试文件。

同一未微调 BF16 27B 用 A0 原始提示词起草全部 902 条训练回答，模型不获得金标。Agent 逐条阅读证据、陈述、金标和初稿，修正并缩短为通常一句、不超过 60 英文词的理由；不是只保留模型答对的题。初稿及其哈希、逐条修改理由、审核状态永久保留。若标签含歧义，记录具体原因并排除整个训练场景组，不修改源数据、不补样本。验证和保留集不制作训练理由。

最终监督文本为 `审核理由 + 换行 + Verdict: 标签 + EOS`。这是 AI 辅助标注，不是独立人工标注。冻结前要求每条训练记录都有完整审核状态，禁止自动以预测与金标一致作为审核通过依据。

审核现已完成并冻结：实际保留 728 条、98 组，整组排除 174 条、26 组。最长完整序列为 851 tokens，仍使用 1536 上限。具体分布与排除记录见 [TRAINING_DATA.md](TRAINING_DATA.md)，审核口径及 PRESUP 训练覆盖缺失的限制见 [REVIEW_POLICY.md](REVIEW_POLICY.md)。正式完整 27B 单卡烟测已通过，回执见 [acceptance/full_27b_smoke.json](acceptance/full_27b_smoke.json)，峰值显存 52.58 GiB；训练和评测完成状态以运行回执为准。

## 执行与恢复

远端隔离目录 `/root/ab_finetune27b_20261030`，原始权重在 `models/Qwen3.8-27B`，隔离 Python 在 `venv/bin/python`。起草代码保留在 `revision_2_workspace`，正式训练代码部署到独立的 `revision_2_formal_workspace`，结果在 `revision_2_runs`。这样部署正式代码不会覆盖仍在运行的起草版本。在服 Python 环境不修改。

当前同架构计算使用 Transformers 的 eager attention 和可反向的 torch gated-delta reference 路径；两组生成路径一致。正式 smoke 必须使用完整 27B，覆盖最长审核样本、三个标签、前反向、优化器更新、仅 LoRA 改动、保存重载、优化器和 RNG 恢复以及关闭 LoRA 恢复基线。初步完整模型探针不能代替此项验收。

若单卡正式 smoke OOM，使用两卡 FULL_SHARD、每卡 micro-batch 1、累积 8，保持全局 batch 16；必须重新冻结执行拓扑并通过对应的完整模型 smoke 后才能训练。两卡仍失败则停止正式训练，报告实际异常，不改模型、精度或提示词。

用户补充授权：允许为缩短时长暂停现有推理服务，使用同型号设备并行起草及运行三个独立种子。五个起草 worker 使用设备 0、2、3、4、5，按冻结训练顺序取下标模 5 的不相交分片，每次仍为单样本。训练仍为每个种子单卡，不改变有效 batch。设备 1 的其他占用不处理。

暂停由 `finetune27b_service_guard.py` 管理：私有目录保存精确 argv/env/cwd、PID 启动时间，先检查服务健康；退出、失败或中断后恢复。独立 watchdog 在主监督进程意外消失时终止其任务进程组并恢复服务。恢复需同时通过模型列表和固定短生成。凭据和完整启动快照只保存在远端权限 700/600 的私有目录，日志不得打印。

checkpoint 保存 LoRA、优化器、CPU/NPU/Python RNG、epoch、数据游标及哈希；每 8 个更新和每轮末保存。恢复可重放尚未保存的最多 7 个更新；完整 checkpoint 目录先原子发布，再更新 latest 指针，能恢复这两步之间的中断。收到的评测答案（包括错误、非法或失败记录）不重试覆盖。

## 选型和一次保留评估

每轮 checkpoint 在固定验证集生成，基线验证只生成一次。优先满足基础准确率下降不超过 2 pp、两集合各类召回下降不超过 5 pp；随后按挑战准确率、基础准确率、挑战 Macro-F1、较早轮次排序。若均不满足，仍选择排序最优者并明确标记限制未通过。

必须核验三份 selection 回执及各自 adapter 哈希后才能读开发保留清单。对 261 题逐题运行基线和三个适配器，四臂调用顺序轮换平衡，输入 token 哈希逐题一致。基线关闭适配器，三个模型共享同一个加载对象与计算精度。

按最后非空行严格匹配 `Verdict: SUPPORTS|REFUTES|NOT ENOUGH INFO`。截断、非法格式、显式 thinking token 或请求失败都保留并计错；理由缺失单列统计。不用金标修补输出。记录原文、原始 token、输入 token 哈希、耗时及状态。

分别报告准确率、Macro-F1、各类召回、分机制指标、NEI→REFUTES、S/R→NEI、无效输出及理由缺失、token 和时间；展示每个种子及均值、样本标准差。每个场景组先汇总三种子正确数减去三倍基线正确数，再做精确双侧组符号置换，不能把三个种子当三倍独立题目。动态规划实现与小规模穷举核对，离线审计另用卷积复算并独立重算混淆矩阵、准确率、Macro-F1 和召回。

预设成功标准：挑战平均准确率至少提高 5 pp 且组检验 p≤0.05，三个种子各自满足全部幅度限制。幅度限制不构成统计非劣效证明。未提高也按相同标准完整报告，不修改阈值。

## 入口

本地设置 `PYTHONPATH=src` 后：

```text
python -m ab_factcheck.finetune27b_v2 prepare
python -m ab_factcheck.finetune27b_v2 verify
python scripts/sync_finetune27b_v2.py
python scripts/review_finetune27b_v2.py --start 0 --count 20
python scripts/append_finetune27b_reviews.py <Agent逐条撰写的决策JSON>
```

远端使用隔离 Python，以下动作均通过 `python -m ab_factcheck.finetune27b_run_v2 <action> --model <原始权重目录> --output <运行目录>`：

1. `draft` 起草（可传 `--shard-count`、`--shard-index`）。
2. `audit-tokens --reviews <审核JSONL> --drafts <初稿目录> --world-size 1`。
3. `finetune27b_v2 freeze --reviews ... --drafts ... --token-audit ...`，同步冻结文件。
4. `smoke` 完整模型验收；失败不能跳过。
5. `validate-baseline` 和 `train --seed 42/43/44`。
6. `select --seed 42/43/44`，三份回执全部完成后 `evaluate`。
7. 同步结果并运行 `python scripts/audit_finetune27b_v2.py <本地结果目录>`。

修订 2 的可部署包入口为 `scripts/package_finetune27b_v2.py`。代码、环境、原始模型、提示词、冻结数据或参数哈希不一致时拒绝恢复或混用结果。模型权重、适配器二进制、优化器缓存及凭据保存在忽略目录；版本化协议和审核文件用于复查。
