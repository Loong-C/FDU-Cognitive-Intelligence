# 源码复现包使用说明

这个包对应目前Baseline、通用草稿与v3三套实验，以及11页组内报告。包含脚本、测试、A组原始数据包、原始课程要求、冻结提示词和参考实验输出。模型权重不在包内，评测通过内网API完成。

## 先区分两种操作

查看已有结果、执行数据审计和离线测试、重新生成报告，不会向模型发请求。下面标为“重新评测”的命令才会访问API，消耗模型服务时间。不要把参考结果目录当新实验目录；原始脚本中部分历史入口有固定输出路径，应优先用run_shared.py启动新实验。

## 环境和目录

Python 3.10以上；模型评测只依赖Python标准库。先解压整个包，不要只单独搬走一个.py文件。保持benchmark_1011(1).zip与PJ-事实判断Baseline目录同级，这是数据读取所需的结构。

进入PJ-事实判断Baseline目录：

```powershell
cd PJ-事实判断Baseline
python baseline_eval.py audit
python -m unittest -v test_baseline test_general_full test_prompt_v2_full test_prompt_v3_full
```

测试使用模拟响应或本机临时HTTP服务，不调用真实模型；部分测试会在work中生成临时文件。

## 配置密钥与模型服务

把.env.example复制为同目录的.env，再由各成员填入自己的QWEN_API_KEY；包内没有真实密钥。也可以设置同名环境变量，环境变量优先。接口地址和模型名在config-4096.json中，当前为http://10.176.30.103:20027/v1与qwen38-27b。需要能访问这台内网服务。

```powershell
Copy-Item .env.example .env
# 在编辑器中填写.env，不要在共享聊天里粘贴密钥
python baseline_eval.py check --config config-4096.json
```

当前冻结的优化实验会核对配置与参考实验一致性；若要更换服务或参数，应建立新实验版本并记录变化，不能把配置变化混作提示词效果。

## 只准备实验 不发请求

```powershell
python run_shared.py baseline --prepare-only
python run_shared.py general --out results/rerun-general-demo --prepare-only
python run_shared.py v3 --out results/rerun-v3-demo --prepare-only
```

通用版和v3的prepare会在新目录保存manifest；之后使用同一目录时加--resume。原始文件哈希保持不变，代码、数据或配置被修改后，旧实验可能按设计拒绝续跑。

## 重新评测 会调用模型API

```powershell
# Baseline：挑战885与基础900
python run_shared.py baseline --out results/rerun-baseline-new
# 通用版：挑战885与基础900，网络失败另存恢复记录
python run_shared.py general --out results/rerun-general-new
# v3原脚本：挑战885；本包没有已经跑好的v3基础集结果
python run_shared.py v3 --out results/rerun-v3-new
```

输出目录必须以rerun-开头，入口会阻止覆盖参考结果。断点续跑时，重复原命令并加--resume。上述三条是独立运行命令，无需同时启动。使用相同提示词、参数和数据仍可能产生服务输出波动，不应期待逐条完全一致。

v3主跑遇到网络失败可能停止，原记录保留；retry_v3_network_failures.py属于历史固定路径补跑工具，不要在新实验中不经检查直接调用。新实验需要按原先“只按网络失败选择”的规则另行恢复并保留原主结果，不能挑错题重跑。

## 离线重新生成组内报告

```powershell
python -m pip install -r requirements-report.txt
python work/build_group_report.py
```

这一步读取包内冻结参考实验，不访问API，也不会自动纳入rerun-下的新实验。输出到包根目录新生成的笔记/认知智能PJ-组内阶段分享-20261029，含PDF、独立HTML、Markdown、逐条对照CSV与图表。报告脚本目前使用Windows的C:/Windows/Fonts/simhei.ttf；其他系统需要先替换为可用的中文TrueType字体路径。

如需把PDF渲染成页图核对，Windows PowerShell 5.1可使用包根目录工具/render_pdf.ps1。渲染不是模型评测的前置条件。

## 脚本导航

- baseline_eval.py：A组原模板评测入口。
- general_full.py：冻结通用草稿的两份集合评测与网络恢复。
- prompt_v3_full.py：冻结v3挑战集评测；prompt_v2_full.py为历史参考工具。
- api_client.py：远程请求与瞬时错误重试；benchmark.py：原始数据、输入隔离、标签解析、评分。
- run_shared.py：新实验目录保护与统一启动入口。
- work/build_group_report.py：重算完整指标、混淆矩阵和阶段报告。
- work/repeat_v3_experiment.py：原两次复测的历史驱动，包含当时的固定路径与清单，不作为可迁移的新实验入口。
- work/verify_*与retry_*：历史实验验证与补跑脚本。

## 参考分数与研究口径

Baseline：挑战605/885（68.36%）、基础893/900（99.22%）。通用版：653/885（73.79%）、886/900（98.44%）。v3原轮及两次复测：756/753/757条正确，85.42%/85.08%/85.54%。v3基础集尚未评测。zero-shot表示没有示例；v3已经有针对机制优化的规则。当前挑战集已用于调优，参考分数不能表述为新数据盲测结果。

原README.md保留了实验发展的历史说明，包含早期1024设置；本入口使用的是config-4096.json。基础900条人工复核状态沿用A组pending；标签没有擅自更改。
