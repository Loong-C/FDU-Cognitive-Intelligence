# 第三轮：14B 非思考模型升级实验

本目录记录 A14 直接三分类与 B14 无示例双世界推理。内部键为 A2/B2，逐字复用 `prompts/v2` 与原始 maxLength=320 JSON Schema。挑战集 87 条/14组，基础集60条/7组，开发集 ID 和顺序不变。总计294次正式生成。无微调、额外示例或封存test推理。

## 模型与部署

官方仓库：[Qwen/Qwen3-14B-GGUF](https://huggingface.co/Qwen/Qwen3-14B-GGUF/tree/530227a7d994db8eca5ab5ced2fb692b614357fd)。

- 文件：`Qwen3-14B-Q4_K_M.gguf`
- revision：`530227a7d994db8eca5ab5ced2fb692b614357fd`
- 长度：9,001,752,960 bytes
- SHA-256：`500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0`
- [许可证 Apache-2.0](https://huggingface.co/Qwen/Qwen3-14B-GGUF/blob/530227a7d994db8eca5ab5ced2fb692b614357fd/LICENSE)
- [非思考模式说明](https://huggingface.co/Qwen/Qwen3-14B)

新权重、下载分块、完整响应、服务日志和遥测均位于被Git忽略的 `outputs/`。原4B模型、启动脚本、configs/experiment.json、configs/experiment_v2.json和历史结果保持原样。

先在仓库根目录执行（现有`.venv`和b11669后端沿用第二轮）：

```powershell
.venv\Scripts\python.exe scripts/bootstrap_14b.py --config configs/experiment_14b_v3.json
.venv\Scripts\python.exe scripts/server_14b.py precheck --config configs/experiment_14b_v3.json
.venv\Scripts\python.exe scripts/tune_14b.py --config configs/experiment_14b_v3.json --apply-selection
```

下载器核对官方固定revision的元数据，使用4连接、16MiB分块，检查HTTP Content-Range及最终整文件SHA-256；再次执行可继续下载。分块本身只有长度验证，整文件哈希才是最终校验。首次下载有提前断流，失败证据保存在runtime内。

资源预检要求至少12.5GiB可用物理内存（保守冷启动预算，不表示低于此值物理上必然不可行）、GPU专用显存余量768MiB、磁盘余量2GiB。候选12/16/20层依预声明次序测试；估计余量不足者跳过并留证。实际加载后仍检查显存和物理内存，单凭估算不能放行正式实验。选择通过技术检查的最大候选值，不依据答题准确率选择。上述命令的--apply-selection会在任何smoke/正式指纹冻结前保存选择值、证据路径及哈希；已有冻结运行则拒绝修改，须使用新run ID。省略该开关时只测量并输出选择建议。

## 非思考与Schema兼容

沿用llama.cpp b11669。生成与`/apply-template`均传`chat_template_kwargs={"enable_thinking":false}`；服务端使用`--reasoning off`。`reasoning_format=none`的真实探针发生空grammar栈错误，失败日志已保留；同后端`reasoning_format=deepseek`能够执行Schema，原始响应JSON整体保存，明确拒绝非空reasoning_content、reasoning、think标记及非零reasoning_tokens。这里的deepseek是后端响应解析格式，不是模型替换，也不表示开启思考。

必须验证开/关选项的实际`/apply-template`输出不同，并保存两者文本和哈希；关闭时的空think前缀必须已闭合。生成实测、token预检和fingerprint一致。模型判断错误、双IMPOSSIBLE不作为技术失败重试；正式格式失败、截断和逻辑无效均保存计错。非思考失效或实际token计数不一致则保存并停止。

## 正式流程

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_14b_server.ps1 -ConfigPath configs/experiment_14b_v3.json
.venv\Scripts\python.exe -m ab_factcheck.cli doctor --config configs/experiment_14b_v3.json
.venv\Scripts\python.exe -m ab_factcheck.cli smoke --config configs/experiment_14b_v3.json
.venv\Scripts\python.exe -m ab_factcheck.cli performance --config configs/experiment_14b_v3.json
.venv\Scripts\python.exe -m ab_factcheck.cli run --config configs/experiment_14b_v3.json
.venv\Scripts\python.exe scripts/server_14b.py stop --config configs/experiment_14b_v3.json
# 等待本次watchdog退出并完成遥测落盘后生成最终报告
.venv\Scripts\python.exe -m ab_factcheck.cli report --config configs/experiment_14b_v3.json
.venv\Scripts\python.exe scripts/audit_14b_run.py --config configs/experiment_14b_v3.json
```

启动命令返回创建结果后模型仍可能加载中；等本机`http://127.0.0.1:8084/health`返回200后执行doctor。doctor校验真实模型、backend、DLL、部分卸载日志，并遍历全部294个输入检查生成预算。smoke包含独立开关探针、5个Schema/长度对照以及三标签×两组的6次生成；performance固定取每数据集前2题×两组共8次，仅测技术可靠性与速度，完整保存在独立目录，不当作正式预测。

正式顺序是challenge/A2→challenge/B2→basic/A2→basic/B2，各组沿冻结ID顺序。temperature=0、seed=42、max_tokens=1024、context=8192、cache_prompt=false、stream=false、单槽单并发。只有确有资源问题才考虑4096，必须更换run ID并用全部294个输入证明输入加1024输出预算都适配；禁止截断证据。

每题原子保存，意外中断后同一命令续跑且不重生成已有正式回答。普通网络请求采用既有最多3次有界尝试；耗尽后记录失败计错。若非正常终止留下run.lock，先确认其中进程已退出再处理锁；不应盲目删除。任何推理源码、模型、配置、模板、backend变化都须新run ID，不能混合数据。旧运行的代码指纹须使用其冻结Git提交复现，不能用新代码覆盖旧run。

资源watchdog只持有并停止它自己启动的llama子进程。低于2GiB可用物理内存、低于768MiB专用显存余量，或启动60秒后持续严重换页且可用内存低于4GiB时停止本次服务，并保留诊断。不结束用户其他程序。手工停止本次服务：

```powershell
.venv\Scripts\python.exe scripts/server_14b.py stop --config configs/experiment_14b_v3.json
```

## 报告与审计

`report`要求完整两组原始记录，未运行数据不产生实验指标。每套数据分别报告准确率、三类召回、宏F1、混淆矩阵、错误方向、Schema/逻辑有效率、320字符上限、截断、耗时和吞吐，并提供机制与group关联。`upgrade_comparison.json`提供A14−A2、B14−B2、B14−A14及描述性交互差值。模型版本/训练阶段不同，因此不能声称参数量的严格因果效应。21个group内样本相关，不按147条独立试验声称显著性。

四个预指定错误ID见`typical_errors.csv`；每数据集每gold标签按冻结ID顺序取前3个B14回答，共18个，见`reason_consistency_review.csv`。复核理由是否否定相应世界但状态写POSSIBLE；复核单独记录，不自动改标签。报告重跑保留已有复核文件。

独立审计在独立Python进程重读原始响应，使用独立解析及统计实现；这不是外部人类审计。历史保护单独检查可执行：

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/audit_14b_run.py --config configs/experiment_14b_v3.json --integrity-only
```

仅历史哈希检查通过不等于实验完成。真实执行状态、性能结论和限制以本目录`RESULTS.md`及实际报告/审计文件为准。
