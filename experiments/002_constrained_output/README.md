# 第二轮：约束输出与双世界推理

沿用第一轮模型、数据和运行基础设施，比较 A2 直接分类、B2 双世界规则、C2 双世界规则加一个 NEI 示例。主比较为 B2−A2、C2−B2，另报告 C2−A2 的同题变化。原始数据与第一轮冻结材料不改动。

最终 r2 已实际完成 441 条正式请求，见 [结果与研究结论](RESULTS.md) 和 [自动报告](reports/pilot_qwen3_4b_q4_struct_v2_r2/pilot_report.md)。

## 冻结设置

- 模型仍为 Qwen3-4B-Instruct-2507 Q4_K_M；本地文件校验 SHA-256 后复用，没有下载新模型。
- llama.cpp b11669 / CUDA 12.4；temperature=0、seed=42、max_tokens=1024、context=8192、单槽串行、关闭流式和 prompt cache。三个条件的每个理由字段统一设置 Schema `maxLength: 320`（字符）。
- 同一个 pilot：challenge 87 条 / 14 组、basic 60 条 / 7 组；直接引用第一轮 manifest 与有序 ID 哈希，不重新调用抽样算法。
- 正式顺序为 A2 challenge/basic → B2 challenge/basic → C2 challenge/basic，共 441 条请求。
- 模型只接收 claim、evidence 和该条件的提示词；输出后关联 gold/group/mechanism。两个世界状态映射标签，不请求 Verdict；双 IMPOSSIBLE 为 INVALID_LOGIC。
- B2 和 C2 的完整任务模板与 JSON Schema 相同，唯一差异是用户指定的单个虚构 NEI 示例及其结束提示。A2 不包含双世界规则。

## 实测后端兼容性

首次预检使用文档中的外层 schema 写法，服务返回 HTTP 200 和 JSON，但忽略了必填字段/枚举。失败运行 `pilot_qwen3_4b_q4_struct_v2_smoke` 已保留，未运行正式样本。其配置与说明在 `preflight_failures/`，完整请求、响应与精确源码快照在对应 outputs 目录。

[b11669 源码](https://github.com/ggml-org/llama.cpp/blob/b11669/tools/server/server-common.cpp) 实际读取以下格式：

```json
{"type":"json_schema","json_schema":{"name":"world_classification","strict":true,"schema":{"type":"object","properties":{},"required":[],"additionalProperties":false}}}
```

上面仅展示包装格式，完整必填字段、枚举和长度约束见 `prompts/v2/manifest.json`。嵌套格式版本 `pilot_qwen3_4b_q4_struct_v2_r1` 通过初始 smoke，但在正式第 165 条遇到理由反复自我修正、耗尽 1024 tokens，自动停止；165 条实际结果和 276 条未运行状态全部保留，没有拼入最终实验。对应实现提交为 `dd33bcb`，配置和停止说明在 `preflight_failures/`。

最终长度约束版本使用新 ID `pilot_qwen3_4b_q4_struct_v2_r2`，三组全部重新运行。每次 smoke 先运行一个无约束对照与两个含 Schema 独有枚举值的冲突输入探针，再用有/无 maxLength 的两条对照验证长度约束，最后运行 3 条独立合成题 × 3 条件。正式 pilot 要求探针和全部 smoke 的结构/逻辑组合有效，并核对运行指纹、真实请求 Schema、参数及原子记录。smoke 的分类错误保留，不因此调整任务提示词。

## 命令

复用现有 `.venv` 和 `requirements-lock.txt`，不需要新依赖。在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_local_server.ps1 -MaxTokens 1024
# 等待 http://127.0.0.1:8081/health 就绪
.venv\Scripts\python.exe -m ab_factcheck.cli prepare --config configs/experiment_v2.json
.venv\Scripts\python.exe -m ab_factcheck.cli smoke --config configs/experiment_v2.json
.venv\Scripts\python.exe -m ab_factcheck.cli run --config configs/experiment_v2.json
.venv\Scripts\python.exe -m ab_factcheck.cli report --config configs/experiment_v2.json
.venv\Scripts\python.exe scripts/audit_structured_run.py
.venv\Scripts\python.exe -m pytest -q
```

网络临时错误最多退避重试两次。格式、字段、生成截断或其他结束异常会保存原文并在第一条发生后停止正式运行；不自动修复、重生成或放宽解析。双 IMPOSSIBLE 单独计为逻辑无效，但不作为 Schema 故障停止其他样本。更改配置、模型、推理代码或提示词必须用新运行 ID。

理由严格检查字段类型和长度。空字符串及达到 320 字符上限均作为独立质量标记，不覆盖有效分类。理由触及字符上限可能导致句子不完整，需与后端生成截断分别报告。非空理由是否忠实、有逻辑根据、足以证明矛盾，仍需人工复核，不能由字符串关键词自动判断。

## 历史兼容与复现

第一轮结果、配置、模板和本地原始记录的 504 个文件已在修改前记录到 `historical_integrity.json`，最终审计逐个验证原始字节哈希。

v1 的文本解析规则保持不变；共享运行器增加 v2 后，推理源文件哈希会改变，因此不能用新版运行器续写旧 v1 运行目录。第一轮完整报告/审计源码保存在 Git 提交 `8ff873195277f604fe8e957567a8c24fdf4e913b`，第一轮实际推理源码对应 `c929550d2caa4fc17eeafb2c5b0f2f8b59f6d5b3`。需要复现旧审计时，在独立检出中使用该提交，并通过本地目录链接或复制提供原始 outputs；不要修改旧指纹以迁就新版代码。

本轮报告、CSV 和审计摘要纳入版本管理；模型、完整请求/响应和运行日志留在被忽略的 outputs。跨版本同时改变了提示词规则、输出协议、预算和标签生成方式，因此不能把跨版本提升全部归因于双世界推理。

`audit_structured_run.py` 从原始响应独立进行 JSON/字段检查、世界映射、混淆矩阵和指标计算，不调用生产解析器或指标函数；逐条核对真实请求、Schema、同序 ID、token 预算、CSV 和原子记录，并验证历史文件与旧 Git 源码的哈希。也核对当前服务日志中的全部生成次数，包含明确保留的失败探针和部分运行；只应在本次服务的专用日志仍可用时运行该计数检查。最终报告仅使用 r2 的 441 条正式输出。
