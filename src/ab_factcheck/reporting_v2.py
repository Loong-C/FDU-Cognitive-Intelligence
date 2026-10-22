"""v2 presentation built on the shared record validation and metrics framework."""

from collections import Counter
import json

from .common import DATASETS, LABELS, ROOT, STRUCTURED_ARMS, atomic_bytes, atomic_json
from .metrics import prediction
from .pilot import load_pilot


def write_structured_report(config, receipt, records, destination):
    from .reporting import csv_file, decimal, pct
    arms = STRUCTURED_ARMS
    flat = [{**r, **{key: r.get("usage", {}).get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
             "reason_quality_flags": json.dumps(r.get("reason_quality_flags", []))} for r in records]
    fields = ["run_id", "dataset", "arm", "id", "group", "mechanism", "gold_label", "predicted_label",
              "status", "parse_status", "parse_error", "json_valid", "fields_valid", "protocol_valid", "logic_valid",
              "claim_true_world", "claim_false_world", "derived_label", "world_reason_true", "world_reason_false",
              "direct_reason", "reason_quality_status", "reason_quality_flags", "finish_reason", "latency_seconds",
              "prompt_tokens", "completion_tokens", "total_tokens", "preflight_prompt_tokens", "completion_request_attempts", "messages_sha256"]
    csv_file(destination / "predictions.csv", flat, fields)
    source = {d: {r["id"]: r for r in load_pilot(config, d)} for d in DATASETS}
    review = []
    expected_worlds = {"SUPPORTS": ("POSSIBLE", "IMPOSSIBLE"), "REFUTES": ("IMPOSSIBLE", "POSSIBLE"), "NOT ENOUGH INFO": ("POSSIBLE", "POSSIBLE")}
    for r in records:
        if r["arm"] == "A2": continue
        gold_true, gold_false = expected_worlds[r["gold_label"]]
        review.append({**{k: r.get(k) for k in ("dataset", "arm", "id", "group", "mechanism", "gold_label", "predicted_label", "parse_status", "claim_true_world", "claim_false_world", "world_reason_true", "world_reason_false", "reason_quality_status")},
                       "evidence": source[r["dataset"]][r["id"]]["evidence"], "claim": source[r["dataset"]][r["id"]]["claim"],
                       "true_state_disagrees_with_gold": r.get("claim_true_world") is not None and r["claim_true_world"] != gold_true,
                       "false_state_disagrees_with_gold": r.get("claim_false_world") is not None and r["claim_false_world"] != gold_false,
                       "human_review": "pending; gold-based disagreement is not semantic adjudication"})
    csv_file(destination / "world_reason_review.csv", review, list(review[0]) if review else ["id"])
    lines = ["# 第二轮：约束输出与双世界推理", "", f"运行 ID：`{config['run_id']}`。", "",
             f"模型为第一轮同一文件 `{config['model']['repository']}` / Q4_K_M，SHA-256 `{config['model']['sha256']}`。后端固定为 llama.cpp `{config['model']['backend_release']}`；temperature=0、seed=42、max_tokens=1024、context=8192、单槽串行、关闭流式与 prompt cache。", "",
             "使用第一轮的同序 pilot：挑战集 87 条 / 14 组，基础集 60 条 / 7 组。未重新抽样，未使用封存测试集。", "",
             "实际顺序：" + " → ".join(receipt["observed_arm_start_order"]) + "。", "",
             "## 实际约束协议", "",
             "当前固定版本实际需要 `response_format = {\"type\":\"json_schema\",\"json_schema\":{\"name\":...,\"strict\":true,\"schema\":...}}`。外层直接放 schema 的首次探针失败，虽然收到 HTTP 200 和合法 JSON，但必填字段与枚举未被约束；已保留失败配置、源码快照和原始响应，没有启动该配置的正式 pilot。", "",
             "依据：[b11669 服务端源码](https://github.com/ggml-org/llama.cpp/blob/b11669/tools/server/server-common.cpp)。成功版本另用运行 ID，先验证无约束输入返回 NOT_JSON，而两个有约束请求必须返回仅在 Schema 中出现的不同枚举值及必填字段；随后 9 条三分类 smoke 全部格式有效。smoke 仅检验运行链路，分类正确性另行记录，不用于优化本轮提示词。", "",
             "B2/C2 没有 Verdict 字段，最终标签只由世界状态映射；双 IMPOSSIBLE 为 INVALID_LOGIC。不得根据理由关键词或正确答案修复结果。格式完整但理由为空只作理由质量标记，不改变标签；非空理由的语义质量尚待人工复核。", "",
             "## 统计口径", "",
             "主要准确率以全部预定样本为分母，无效和失败计错；混淆矩阵含 INVALID 列。JSON、字段、完整协议有效率均以全部预定样本为分母；逻辑组合有效率只在已解析出世界组合的 B2/C2 输出上计算，A2 为 N/A。截断即使恰好留下可解析 JSON 也计无效。有效输出条件准确率有选择偏差，不能代替主要准确率。", "",
             "主要对照为 B2−A2 和 C2−B2；C2−A2 是补充对照。v1→v2 同时改变格式约束、输出预算、提示词规则和最终映射，不单独归因于推理方法。样本小且组内相关，不作显著性或最终泛化断言。基础集原始标签审核状态仍为 pending；自然语言世界判断不是 SAT 证明。", ""]
    for dataset in DATASETS:
        d = receipt["datasets"][dataset]
        lines += [f"## {'核心挑战集' if dataset == 'challenge' else '基础能力集'}", "",
                  "| 条件 | 正确 / 全部 | 准确率 | 宏 F1 | S 召回 | R 召回 | NEI 召回 | NEI→R | S→NEI | R→NEI | 有效条件准确率 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for arm in arms:
            m = d["arms"][arm]
            lines.append(f"| {arm} | {m['correct']}/{m['n']} | {pct(m['accuracy'])} | {decimal(m['macro_f1'])} | " + " | ".join(pct(m["classes"][label]["recall"]) for label in LABELS) + f" | {m['nei_to_refutes']} | {m['supports_to_nei']} | {m['refutes_to_nei']} | {pct(m['valid_only_accuracy'])} |")
        lines += ["", "### 有效率与成本", "", "| 条件 | JSON有效 | 字段有效 | 协议有效 | 逻辑有效 / 可解析组合 | 无效数 | 截断 | 平均tokens | 平均秒 | 网络失败 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for arm in arms:
            m = d["arms"][arm]
            logic = f"{m['logic_valid_count']}/{m['logic_available_count']} ({pct(m['logic_valid_rate'])})" if arm != "A2" else "N/A"
            lines.append(f"| {arm} | {pct(m['json_valid_rate'])} | {pct(m['fields_valid_rate'])} | {pct(m['protocol_valid_rate'])} | {logic} | {m['invalid']} | {m['truncated_count']} | {decimal(m['mean_completion_tokens'])} | {decimal(m['latency_mean_seconds'])} | {m['request_failed_count']} |")
        lines += ["", "### 同题配对变化", "", "| 比较 | 准确率差（百分点） | 错→对 | 对→错 | 原 NEI→R 中纠正 / 原条数 | 原正确 S→NEI | 原正确 R→NEI |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for name, pair in d["paired"].items():
            lines.append(f"| {name} | {100*pair['accuracy_delta']:+.2f} | {pair['improved']} | {pair['harmed']} | {len(pair['nei_refutes_corrected_ids'])}/{len(pair['nei_refuted_before_ids'])} | {len(pair['supports_correct_to_nei_ids'])} | {len(pair['refutes_correct_to_nei_ids'])} |")
        lines += ["", "### 分机制结果", "", "| 机制 | 样本 / NEI | A2 准确率 / NEI召回 | B2 准确率 / NEI召回 | C2 准确率 / NEI召回 |", "| --- | ---: | --- | --- | --- |"]
        for mechanism, values in d["mechanisms"].items():
            cells = [f"{pct(values[a]['accuracy'])} / {pct(values[a]['classes']['NOT ENOUGH INFO']['recall'])}" for a in arms]
            lines.append(f"| {mechanism} | {values['A2']['n']} / {values['A2']['classes']['NOT ENOUGH INFO']['support']} | {' | '.join(cells)} |")
        lines += ["", "DENIAL、SETCLOSE、UNIQUE、TEMPSCOPE 应结合逐题记录复核；每机制仅少数组，不把表中差异视为稳定能力排名。", ""] if dataset == "challenge" else [""]
        for arm in arms:
            lines += [f"### {arm} 混淆矩阵", "", "行是真实标签，列是最终预测。", "", "| 真实标签 | SUPPORTS | REFUTES | NOT ENOUGH INFO | INVALID |", "| --- | ---: | ---: | ---: | ---: |"]
            for gold, counts in d["arms"][arm]["confusion_matrix"].items():
                lines.append(f"| {gold} | " + " | ".join(str(counts[p]) for p in (*LABELS, "INVALID")) + " |")
            lines.append("")
        a, b, c = (d["arms"][arm] for arm in arms)
        lines += ["### 本数据集的直接观察", "",
                  f"B2−A2 净变化 {100*(b['accuracy']-a['accuracy']):+.2f} 个百分点，C2−B2 为 {100*(c['accuracy']-b['accuracy']):+.2f} 个百分点。这是本轮同协议对照的观察结果。", "",
                  "NEI 召回的 A2/B2/C2 序列为 " + " / ".join(pct(x["classes"]["NOT ENOUGH INFO"]["recall"]) for x in (a,b,c)) + "；SUPPORTS 为 " + " / ".join(pct(x["classes"]["SUPPORTS"]["recall"]) for x in (a,b,c)) + "；REFUTES 为 " + " / ".join(pct(x["classes"]["REFUTES"]["recall"]) for x in (a,b,c)) + "。改善与误伤必须同时解释。", ""]
    history_path = ROOT / "experiments/001_two_world_pilot/reports" / config["historical_run_id"] / "metrics.json"
    if history_path.exists():
        history = json.loads(history_path.read_text(encoding="utf-8"))
        lines += ["## 历史输出失败对照", "", "| 数据集 | 历史条件 | 历史无效 / 全部 | 新条件 | 新无效 / 全部 | 新截断 |", "| --- | --- | ---: | --- | ---: | ---: |"]
        for dataset in DATASETS:
            for old, new in zip(("A0", "B1", "C1"), arms):
                a = history["datasets"][dataset]["arms"][old]; b = receipt["datasets"][dataset]["arms"][new]
                lines.append(f"| {dataset} | {old} | {a['invalid']}/{a['n']} | {new} | {b['invalid']}/{b['n']} | {b['truncated_count']} |")
        lines += ["", "此表只说明整体输出方案的可靠性变化；未单独控制 Schema 与 1024-token 预算，不能拆出各自的因果贡献。", ""]
    disagreements = Counter((r["dataset"], r["arm"]) for r in records if r["parse_status"] == "ok" and prediction(r) != r["gold_label"])
    lines += ["## 哪些问题已不是格式失败", "", "| 数据集 | A2 合规但错 | B2 合规但错 | C2 合规但错 |", "| --- | ---: | ---: | ---: |"]
    for dataset in DATASETS:
        lines.append(f"| {dataset} | " + " | ".join(str(disagreements[dataset,a]) for a in arms) + " |")
    lines += ["", "这些是相对冻结标签的分类错误。B2/C2 的标签完全由有效世界状态计算，因而其错误可定位为世界兼容性判断与标签的冲突，而非最后 Verdict 写错或格式解析失败。`world_reason_review.csv` 标出具体哪个世界状态与标签隐含的状态不同，并保留理由；它不自动裁决数据标签或解释语义。", "",
              "`predictions.csv` 可复算分类、有效率、耗时和 token 统计；`changed_predictions.csv` 与 `metrics.json` 保存完整配对 ID；`review_queue.csv` 指向本地完整响应。所有请求和响应留在 outputs 中，模型权重不提交。", "",
              "完整环境、实际 Schema 参数、失败探针、成功探针、smoke 和独立审计证据见运行说明与本目录审计文件。历史材料保持原样，旧推理环境按旧提交复现。", ""]
    atomic_bytes(destination / "pilot_report.md", "\n".join(lines).encode("utf-8"))
