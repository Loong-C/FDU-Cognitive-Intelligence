# 本次归档验收（2026-10-29）

整理基于提交 `e3fec15`，在独立 worktree 和 `codex/import-pj-materials-20261029` 分支完成。原工作区的分支、索引、未提交实验代码和根 README 未由本次整理修改；已有文件仅在新分支的 `experiments/README.md` 增加归档导航，其余为新增文件。

## 完整性与取舍

- 来源清单覆盖 198 项：源码 ZIP 179 项、分享 ZIP 18 项、单独 PDF 1 项。
- 新保留 120 个原文件（1,918,753 字节）；15 项复用相同 SHA256 的文件；63 项仅在原包和被忽略的本地运行目录保留。另新增导航、恢复脚本、归档清单及换行保护规则。
- `python scripts/restore_imported_pj_20261029.py --check` 校验 124 个不同的保留目标（包含 4 个仓库已有文件）。原始数据和课题说明按字节去重。
- 单独 PDF 与分享 ZIP 内 PDF 的 SHA256 均为 `f50579204c9ebc7608243655468339368e5b240a3e9ddc831605a27d829ead5b`。PDF 为 11 页，查看首页及全页缩略图，未改变原件；Markdown 的全部 4 个 SVG 引用可解析。
- 来源快照列出的 15 份原始 JSONL 均与恢复后的文件哈希一致；归档文件保留 CRLF 等原始字节，Git 属性声明对应换行口径。
- 新增内容未发现实际密钥模式；`.env.example` 为空值。原始响应、逐题 CSV/JSONL 和运行目录不纳入 Git。

## 离线运行检查

在恢复后的原始运行目录执行：

```text
python baseline_eval.py audit
python -m unittest -v test_baseline test_general_full test_prompt_v2_full test_prompt_v3_full
python run_shared.py baseline --prepare-only
python run_shared.py general --out results/rerun-general-check --prepare-only
python run_shared.py v3 --out results/rerun-v3-check --prepare-only
```

27 项测试全部通过，三种方案均成功完成仅准备流程。测试包含评分分母、输入隔离、输出解析、HTTP 重试、恢复策略、配置一致性和断点续跑；HTTP 测试使用本机临时服务或模拟响应。没有请求真实模型，没有重跑全量实验。

恢复工具已核对原包哈希及成员集合，并验证路径越界输入会被拒绝；所有写入限定在本 worktree 的被忽略目录。恢复脚本本身不执行导入代码。新克隆若需原始响应及完整运行环境，仍须提供清单所列的原始 ZIP。

## 独立统计检查

核对分享 CSV 的 1,785 个唯一 ID、数据集、标签、证据、陈述及管理字段与原始数据一致；预测逐项与原始响应匹配。v3 的替换仅采用网络失败恢复记录，未按答案正确与否挑选。

| 方案 | 挑战集正确数 | 基础集正确数 |
| --- | ---: | ---: |
| Baseline | 605/885 | 893/900 |
| 通用草稿 | 653/885 | 886/900 |
| v3 原轮 | 756/885 | 未评测 |
| v3 复测 1 | 753/885 | 未评测 |
| v3 复测 2 | 757/885 | 未评测 |

上述数字与阶段报告一致；v3 基础集字段保持空白。没有对缺失实验作推断，也没有重写来源方的结论。

## 仓库原有数据

`python scripts/split_dataset.py --check` 通过：basic 为 dev 720 / test 180，challenge 为 dev 702 / test 183，冻结划分未改动。本次不修改主项目实现及依赖，未重新执行模型实验或重新生成报告。
