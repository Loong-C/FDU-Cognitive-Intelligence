# 认知智能课程 PJ 事实判断 Baseline

本目录实现 B 组的第一轮远程 API 评测。目标是复现 A 方 zero-shot 设置，分别测量核心挑战集与基础能力集，保留可复查的逐条结果，作为后续优化的对照。

## 密钥和接口

在本目录 `.env` 中填写 `QWEN_API_KEY=你的密钥`，保存即可。已有进程环境变量 `QWEN_API_KEY` 非空时优先使用环境变量。程序不执行 `.env` 中的文字，不回显密钥，不记录 Authorization 头。

接口与生成参数位于 `config.json`：

- API：`http://10.176.30.103:20027/v1`
- 模型：`qwen38-27b`
- temperature：0
- thinking：通过 `chat_template_kwargs.enable_thinking=false` 关闭
- max_tokens：1024；每次请求超时120秒；瞬时网络错误、408、429、500、502、503、504最多重试2次
- 默认直连，不读取环境代理；不自动跟随重定向

API 兼容方式参考 [vLLM 官方接口说明](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/)。本次必须同时检查实际响应的推理字段和终止原因；请求参数本身不能证明服务端已关闭 thinking。

## 运行

Python 3.10及以上，无需安装第三方库。先进入本目录，再运行：

```powershell
python baseline_eval.py audit
python baseline_eval.py check
python -m unittest -v test_baseline
python baseline_eval.py run --phase smoke --workers 4 --out results/smoke-20261027
python baseline_eval.py run --phase full --workers 4 --out results/full-20261027
```

抽样默认每集合20条，固定随机种子20261027，按机制与标签分桶轮流抽取。抽样用于验证管线，不能替代总体分数。全量严格使用885条与900条，禁止在full阶段指定抽样数。两份集合不合并评分。

断点续跑必须保留相同的代码、参数、种子和抽样范围：

```powershell
python baseline_eval.py run --phase full --workers 4 --out results/full-20261027 --resume
```

如需补跑最终请求失败或格式错误的样本，增加 `--retry-failed`。补跑记录追加保存，统计时采用同一ID的最后一次记录；旧记录完整保留。已成功解析但预测错误的样本不会因该选项重跑。401等鉴权错误或重试耗尽会停止发送后续批次；当前在途批次会先保存结果。

本机当前可用 Python 为 `C:\Users\yusan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`。若终端中的 `python` 不可用，可用该完整路径调用。

## 数据与提示词

原件保留在课程目录：`benchmark_1011(1).zip`、`PJ要求2026.docx`、`AB对抗组选题说明.docx`。首次执行audit或run时，将ZIP中的两份JSONL与说明按原始字节复制到本目录 `data/`；发现已有副本与原件不同会停止。

提示词直接从 A 方 `数据说明.md` 的text代码块提取。首行 `System: ` 作为系统角色，后续段落作为用户角色；只替换 `{evidence}` 和 `{claim}`。标签、机制、group、variant和其他管理字段不会发送给模型，不使用外部检索或知识库。

| 集合 | 条数 | group数 | SUPPORTS | REFUTES | NOT ENOUGH INFO |
| --- | ---: | ---: | ---: | ---: | ---: |
| 核心挑战集 | 885 | 143 | 342 | 118 | 425 |
| 基础能力集 | 900 | 105 | 246 | 305 | 349 |

核心挑战集的7类机制为 DENIAL、TEMPSCOPE、PRESUP、SETCLOSE、UNIQUE、LOOKALIKE、AMBIGREF；基础能力集有自己的7类机制。两份集合无交叉group或ID、无重复输入。基础能力集的900条 `human_review_status` 均为pending，这是原件的管理状态；保留该事实，不擅自改为已审核。

## 输出与评分

每次运行在独立结果目录保存：

- `manifest.json`：提示词、数据与代码摘要、配置、样本ID、抽样种子、并发数。
- `challenge.jsonl`、`basic.jsonl`：逐样本原始响应、解析结果、真实标签、耗时、失败请求与补跑历史。
- `*-predictions.csv`：便于人工复查的逐条对照。
- `summary.json`、`report.md`：分别汇总两份集合；含Accuracy、三类Precision/Recall/F1、Macro-F1、混淆矩阵、机制分组、NEI召回、失败率和耗时。
- `run_status.json`：是否完成全部目标样本、是否所有输出均可解析、是否中止。

仅接受最后一条非空行严格符合 `Verdict: SUPPORTS`、`Verdict: REFUTES` 或 `Verdict: NOT ENOUGH INFO` 的输出。截断、空输出、不规范标签和未关闭thinking均单列为解析失败，不从理由中猜测标签。

Accuracy和Recall以全部目标样本为分母，请求失败、解析失败及未完成样本均保留。Macro-F1固定对三类取平均，失败会形成相应真实类别的漏判；某机制没有NEI样本时，其NEI召回率记为空值，不误记0%。另列有效输出上的Accuracy用于诊断，不以它替代正式指标。未完成时的分数仅用于观察进度。

模型量化格式据此前聊天为W8A8，A方参考为Q8_0；接口列表只能确认模型ID，不能独立核实量化格式。二者结果可以并列描述，不能将差异直接解释为优化效果或量化的因果效应。

## 后续工作

先冻结本轮Baseline结果，再按group划分开发集与保留测试集。后续提示词、证据边界识别或训练优化只在开发部分调试；同步检查基础能力是否退步。第一次全量评测接触过的数据不能再宣称为从未观察过的独立测试集。优化结果需与同模型、同量化配置的Baseline比较。

课程最终还要求期中与期末两次展示、正文不超过8页的报告、组员分工、模型和AI工具使用说明，以及完整源代码。当前目录交付的是Baseline阶段代码与实验记录，尚未代替最终课程报告或完成模型优化。

## 两轮输出长度对照

按用户要求，先完成1024上限首轮，再自动执行4096上限的第二轮。第二轮使用config-4096.json，结果保存为results/full-4096-20261027。两轮模型、数据、原始提示词、temperature、thinking参数和并发数均保持一致。

顺序执行入口为run_second_round.py；已运行时不要重复启动。它等首轮完成，执行第二轮，再自动运行analyze_results.py和compare_rounds.py。当前阶段可查看results/comparison_status.json，最终两轮对照位于results/comparison-20261027/两轮对照.md。

两轮均重新请求完整数据，不仅重跑被截断样本。比较Accuracy、召回率、Macro-F1、截断率、输出token与耗时，同时列出错误→正确和正确→错误的样本转移。考虑到独立重复请求已观察到输出波动，结果不直接归结为输出上限的单一因果效应。


## 阶段报告与规则提示开发验证

课程笔记目录已新增认知智能PJ-事实判断Baseline阶段报告.md及同名PDF；PDF共5页，汇总两轮Baseline与错例分析，单独保存，不混入优化结果。

提高反驳证据门槛的探索性开发实验由prompt_trial.py执行，固定挑战集88条/14组、基础集120条/14组；每个样本分别请求control原提示词与rules规则提示，共416次请求，维持4096上限与其余生成参数。选组依据固定哈希和mechanism，每类机制2组，不按预测筛选。

命令：python prompt_trial.py prepare；python prompt_trial.py run。相同目录下自动跳过已记录的样本与实验臂，数据、提示词、代码或配置摘要不一致时停止；如需新版本请另开目录。实验预案、两版提示词、分组和参数均已冻结在results/prompt-refutation-v1-20261027。完成后自动生成开发实验报告.md、summary.json、逐条配对CSV和预测变化JSON；run_status.json提供进度。主对照是本次新请求control，历史全量轮同ID结果仅作参考。

此实验保持zero-shot，不使用示例、不训练LoRA、不后处理标签。因原数据此前已被完整分析，只能称探索性开发，后续泛化验证仍需新保留数据。


## 反驳门槛v1挑战集全量结果

按用户要求，对冻结规则的885条挑战集全部重新请求，结果位于results/challenge-refutation-v1-full-20261027。正确数676/885（76.38%），比原提示词4096 Baseline的605/885（68.36%）净增71题、+8.02个百分点。全量对照报告.md、逐条对照.csv、prediction_changes.json和summary.json均已生成；885条全部正常解析。该结果为历史Baseline对照下的探索性全量复测，保留服务输出波动限制。

入口challenge_full.py，prepare冻结来源和参数，run执行或跳过已有ID续跑，summarize复算报告。小开发实验原88条预测未复用。该轮仅挑战集，未重新运行基础集。
