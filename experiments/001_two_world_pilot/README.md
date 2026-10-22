# 首轮双世界提示词对照实验

目标是在同一份本地开源小模型、相同开发样本和推理参数下，比较直接分类、双世界零样本、双世界单示例三个条件。此次不训练、不引入外部知识，也不运行 SAT/SMT 求解器。

首轮已实际完成，见 [结果摘要](RESULTS.md) 和 [自动评测报告](reports/pilot_qwen3_4b_q4_v1/pilot_report.md)。完整原文保存在本地 `outputs/runs/pilot_qwen3_4b_q4_v1/`。

## 冻结协议

原始开发集 / 测试集继续使用 `data/splits/v1`，划分种子仍为 42。只从开发集抽取 pilot：挑战集每机制 2 个完整组，基础集每机制 1 个完整组。

先最大化所选组对该机制已有标签的覆盖，再最小化所选样本标签比例与该机制完整开发集的平方偏差之和，同分时用种子 20261022、数据集、机制和组 ID 的 SHA-256 打破平局。选择过程不读取模型预测。

| 数据集 | 样本 | 组 | SUPPORTS | REFUTES | NOT ENOUGH INFO |
| --- | ---: | ---: | ---: | ---: | ---: |
| challenge | 87 | 14 | 33 | 14 | 40 |
| basic | 60 | 7 | 14 | 23 | 23 |

`pilot/*_manifest.json` 记录全部开发样本的 pilot 归属、父划分哈希与样本分布。pilot 是 dev 的子集，test 不用于本轮提示词调整和评测。

| 条件 | 提示词 | 主要比较 |
| --- | --- | --- |
| A0 | A 组原始零样本事实核查提示词，首句为 system，余文为 user | 基线 |
| B1 | 双世界零样本规则 | B1−A0 |
| C1 | B1 完整模板加一个虚构 NEI 示例 | C1−B1 |

模板保存在 `prompts/v1`，含来源文档哈希和逐文件哈希。C1 的示例插入位置与文本由代码验证，模型数据输入只允许 `claim` 与 `evidence`。C1 不称作 zero-shot。

## 环境和参数

- 模型：`bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF` 的 `Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf`，单个文件 2,497,280,736 字节。
- revision：`ae44f08e1392f39c0e474af10c3ff8355c8b6688`；SHA-256：`2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e`。
- 后端：llama.cpp `b11669` Windows x64 CUDA 12.4 便携包，校验哈希后解压到 `outputs/runtime`。
- 模型服务：`http://127.0.0.1:8081/v1`；串行单槽，8192 上下文、512 生成上限、temperature 0、请求 seed 42、stream false、prompt cache 关闭。
- 首选全部层 GPU offload；启动日志记录实际 offload。没有修改或停止其他应用，也没有更改显卡驱动。
- 请求使用模型服务实际返回的 model ID。种子不代表跨硬件或后端的逐位可复现保证。

模型卡：[Qwen 官方模型](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)；[量化文件来源](https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF)；[后端发行版](https://github.com/ggml-org/llama.cpp/releases/tag/b11669)。

## 从仓库根目录运行

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.venv\Scripts\python.exe -m pip install --no-deps -e .
.venv\Scripts\python.exe scripts/bootstrap_local.py
powershell -ExecutionPolicy Bypass -File scripts/start_local_server.ps1

.venv\Scripts\python.exe -m ab_factcheck.cli prepare
.venv\Scripts\python.exe -m ab_factcheck.cli doctor
.venv\Scripts\python.exe -m ab_factcheck.cli smoke
.venv\Scripts\python.exe -m ab_factcheck.cli run --dataset all --arm all
.venv\Scripts\python.exe -m ab_factcheck.cli report
.venv\Scripts\python.exe scripts/audit_pilot_run.py
.venv\Scripts\python.exe -m pytest -q
```

初次启动需等待 `/health` 就绪后再运行 doctor。可先执行 `Invoke-RestMethod http://127.0.0.1:8081/health` 检查。8081 已被占用时脚本会停止，不结束已有进程。所有 CLI 子命令均支持 `--config` 指定 JSON 配置。

已有虚拟环境无需重复创建。依赖版本锁文件由实际安装与测试环境产生，项目安装命令不会重新下载已锁定的依赖。无需 OpenAI API key，也不使用商业模型服务。

运行 `run --dataset challenge --arm A0` 可以单独运行一个条件；同一 run ID 的后续命令可接着执行其他条件。正式默认顺序为 challenge A0/B1/C1，再 basic A0/B1/C1。report 要求两套数据的全部三组均已有完整结果。

## 失败、恢复与输出解释

每条推理原子写入独立 JSON，再导出数据集 JSONL。中断时已完成记录保留，尚未运行的记录标为 `not_run`；重复运行同一命令继续未完成记录，不重新生成格式错误或错误答案。临时网络故障最多自动重试两次；再次执行命令可重试已记录的临时网络失败，并保留上次失败信息。

存在 `run.lock` 时不允许第二个写入者。强制终止进程后如果遗留锁，先确认锁内 PID 已退出，再仅删除该运行目录的锁文件。普通 Ctrl+C 会自动释放锁。修改模型、推理配置、推理代码或提示词后必须使用新 run ID，不覆盖旧实验。

输出目录为 `outputs/runs/<run_id>/`：

- `environment.json`、`environment_latest_check.json`：首次环境证据与最近检查，含 GPU、后端版本、offload、实际 chat template 和依赖。
- `fingerprint.json`：冻结配置、推理代码、数据清单、模型与模板哈希；`expected_*.json` 是应执行样本清单。
- `records/`：逐条完整返回；`challenge.jsonl` 和 `basic.jsonl`：统一导出，包含失败记录；smoke 使用单独的 `<run_id>_smoke` 目录。

报告目录为 `experiments/001_two_world_pilot/reports/<run_id>/`，包括 Markdown 报告、分数据集与分机制指标、混淆矩阵、逐题预测、配对变化、无效输出和人工复核队列。

报告目录另存 `configuration.json`、`run_fingerprint.json`。完成报告后运行 `scripts/audit_pilot_run.py`，离线核验记录完整性、同序配对、实际参数、输入 token 预检、混淆矩阵及配对增减；它不再向模型发请求，并保存 `execution_audit.json` 与 `environment_summary.json`。复核队列通过 `record_path` 指向本地完整响应，完整响应不提交到 Git。

严格准确率以全部预定样本为分母，无效输出、截断和请求失败计错。B1/C1 的世界状态缺失或双 IMPOSSIBLE 无效；普通逻辑不一致保留原始 Verdict 计分，另报不一致率。不把推导标签替代原始 Verdict。

模型的错误答案或不合规 smoke 输出如实保留，不据此改本轮提示词。程序单元测试使用模拟返回，仅验证程序行为，不是模型性能。基础能力集原始 `pending` 标记不修改；复核队列不等于重新裁决标签。

本阶段 CLI 只暴露 pilot，不开放测试集运行命令。首轮结果是探索性证据，不能把组内样本视作独立重复，也不能把双世界自然语言判断描述为数学证明。
