# 2026-10-29 外部阶段材料归档

本目录整理用户提供的「认知智能PJ-脚本与复现包-20261029.zip」「认知智能PJ-组内阶段分享-20261029.zip」及「认知智能PJ阶段报告.pdf」。这是独立的历史全量开发评估材料，不接续仓库的编号实验，也不改变现有 `src/ab_factcheck`、数据划分和提示词版本。

## 阅读入口与目录

| 内容 | 位置 |
| --- | --- |
| 阶段报告、离线 HTML、PDF 与配图 | [报告入口](../../docs/reports/imported_pj_20261029/README.md) |
| 各轮结果摘要、冻结清单、预案及简短分析 | [runs/](runs/)（保留来源运行名称） |
| 总体、机制指标与来源快照 | [reports/](reports/) |
| 历史运行配置与空密钥示例 | [configs/imported_pj_20261029/](../../configs/imported_pj_20261029/) |
| 原始及冻结提示词（相同字节去重） | [prompts/imported_pj_20261029/](../../prompts/imported_pj_20261029/) |
| 原版评测、统计、报告脚本与随附离线测试 | [scripts/imported_pj_20261029/](../../scripts/imported_pj_20261029/) |
| 新增课程要求 | [PJ要求2026.docx](../../docs/references/PJ要求2026.docx) |
| 每个来源文件的 SHA256、去向与取舍 | [import_manifest.json](import_manifest.json) |
| 原包文件清单、验收记录和数据审计 | [provenance/](provenance/) |

## 保留与去重规则

- 三种阶段报告各保留一份；单独上传的 PDF 与分享包内 PDF 完全相同。
- 两份原始 JSONL、数据说明及 `AB对抗组选题说明.docx` 与仓库已有文件逐字节一致，复用 `data/raw/benchmark_1011/` 和 `docs/references/`。
- 配置、提示词、核心脚本、聚合指标、实验清单和简短说明进入 Git。源码中的历史哈希、路径及日期保持原样；各归档目录的 `.gitattributes` 防止换行转换破坏哈希。
- 原始响应、逐条预测 CSV/JSONL、较长的逐题分析和冗余打包工具保留在原 ZIP，并可恢复至被忽略的 `outputs/imported_pj_20261029/`。不提交 ZIP、密钥或模型权重。
- `import_manifest.json` 覆盖 198 个来源文件记录；`tracked` 为新增保留，`reused` 指向相同字节的已有文件，`local_only` 可从原包恢复。来源文件名、哈希及路径映射用于追溯，不包含本机微信目录。

## 结果口径

| 方案 | 挑战集正确数 | 基础集正确数 |
| --- | ---: | ---: |
| Baseline，4096 token 上限 | 605/885（68.36%） | 893/900（99.22%） |
| 通用草稿 | 653/885（73.79%） | 886/900（98.44%） |
| v3 原轮 | 756/885（85.42%） | 未评测 |
| v3 复测 1 | 753/885（85.08%） | 未评测 |
| v3 复测 2 | 757/885（85.54%） | 未评测 |

表中采用报告的网络失败恢复口径。通用版基础集净少答对 7 条；v3 三轮为同一批样本的重复调用。全量数据已参与错误分析和提示词优化，包含本仓库冻结划分中的测试样本，因此这些分数只能作为外部开发评估记录，不能作为独立盲测结果，也不能与仓库 dev pilot 分数直接比较。现有划分文件未修改；若后续使用这批全量错例继续优化，应另行安排未接触过的评测数据。

## 离线核对与恢复

在仓库根目录执行，Python 3.10+，恢复工具只使用标准库：

```powershell
python scripts/restore_imported_pj_20261029.py --check
python scripts/restore_imported_pj_20261029.py --source-zip '原文件所在目录/认知智能PJ-脚本与复现包-20261029.zip' --share-zip '原文件所在目录/认知智能PJ-组内阶段分享-20261029.zip'
```

恢复工具先核对 ZIP 和所有成员的 SHA256，拒绝覆盖已改变的运行文件；只恢复材料，不执行其中的命令。分享包的逐条对照表位于 `outputs/imported_pj_20261029/share/附件/`。

原脚本依赖同级数据 ZIP、固定相对路径和代码哈希。为保持可复现性，Git 中按仓库结构分开放置供审阅，**执行时使用恢复后的原始目录**，不要直接在归档脚本目录启动评测。随附测试留在脚本快照内，以免参与主项目的 pytest 自动收集。

```powershell
Set-Location 'outputs/imported_pj_20261029/source/认知智能PJ-源码复现包/PJ-事实判断Baseline'
python baseline_eval.py audit
python -m unittest -v test_baseline test_general_full test_prompt_v2_full test_prompt_v3_full
python run_shared.py baseline --prepare-only
python run_shared.py general --out results/rerun-general-check --prepare-only
python run_shared.py v3 --out results/rerun-v3-check --prepare-only
```

上述操作不请求模型。`prepare-only` 创建目录后，再次使用同一目录需加 `--resume`。如需重算报告，在独立环境安装运行目录内 `requirements-report.txt` 后执行 `python work/build_group_report.py`；它使用 Windows 中文字体，输出到原包根目录的 `笔记/`，不会覆盖 Git 中的报告。

实际重新评测需自行配置运行目录内的 `.env` 或 `QWEN_API_KEY`，并能访问配置中的内网服务；运行 `run_shared.py` 去掉 `--prepare-only` 才会发起评测。历史 README 中部分入口未随原包提供，固定路径补跑脚本也不适用于新实验；请以本页恢复流程和原包 `run_shared.py` 为入口。本次整理不调用模型服务。

本地验收见 [VALIDATION.md](VALIDATION.md)。原包内的“验收”JSON 属于来源方历史记录，与本次检查分开保留。
