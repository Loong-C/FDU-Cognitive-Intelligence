"""Two-arm model-upgrade report, paired to immutable round-two raw records."""

from collections import defaultdict
import json
import math
from statistics import mean, median
from pathlib import Path

from .common import DATASETS, LABELS, ROOT, atomic_bytes, atomic_json, file_hash, read_jsonl
from .metrics import compute_metrics, paired_comparison, prediction
from .pilot import load_pilot
from .resources_v3 import summarize


def performance(rows):
    latencies = sorted(r["latency_seconds"] for r in rows if r.get("status") == "completed")
    tokens = sum(r.get("usage", {}).get("completion_tokens", 0) for r in rows if r.get("status") == "completed")
    rates = [r["response_json"]["timings"]["predicted_per_second"] for r in rows
             if isinstance(r.get("response_json", {}).get("timings", {}).get("predicted_per_second"), (int, float))]
    return {"completed_requests": len(latencies), "request_seconds": sum(latencies), "completion_tokens": tokens,
            "end_to_end_completion_tokens_per_second": tokens / sum(latencies) if sum(latencies) else None,
            "backend_decode_tokens_per_second_mean": mean(rates) if rates else None,
            "latency_p50_seconds": median(latencies) if latencies else None,
            "latency_p95_seconds": latencies[math.ceil(len(latencies) * .95) - 1] if latencies else None,
            "quantile_method": "p50 median; p95 nearest rank; request throughput includes prompt processing"}


def select_review(config, records):
    chosen = []
    for dataset in DATASETS:
        for label in LABELS:
            candidates = sorted((r for r in records if r["dataset"] == dataset and r["arm"] == "B2" and r["gold_label"] == label), key=lambda r: r["id"])
            chosen.extend(candidates[:config.get("review", {}).get("per_label_per_dataset", 3)])
    return chosen


def write_upgrade_report(config, receipt, records, destination):
    from .reporting import csv_file, decimal, pct
    by_key = {(r["dataset"], r["arm"], r["id"]): r for r in records}
    pilot = {d: {r["id"]: r for r in load_pilot(config, d)} for d in DATASETS}
    history = {}
    baseline_report = ROOT / config.get("historical_report_root", "experiments/002_constrained_output/reports") / config["historical_run_id"]
    baseline_metrics = json.loads((baseline_report / "metrics.json").read_text(encoding="utf-8"))
    for dataset in DATASETS:
        path = ROOT / "outputs/runs" / config["historical_run_id"] / f"{dataset}.jsonl"
        if file_hash(path) != baseline_metrics["source_jsonl_sha256"][dataset]:
            raise ValueError("4B baseline raw record hash changed")
        history[dataset] = [r for r in read_jsonl(path) if r["arm"] in ("A2", "B2")]
    comparisons, costs, groups = {}, {}, []
    for dataset in DATASETS:
        new = {a: [r for r in records if r["dataset"] == dataset and r["arm"] == a] for a in ("A2", "B2")}
        old = {a: [r for r in history[dataset] if r["arm"] == a] for a in ("A2", "B2")}
        for a in new:
            if [r["id"] for r in new[a]] != [r["id"] for r in old[a]]:
                raise ValueError("Cross-model pairing requires identical pilot order")
        comparisons[dataset] = {"A14-A2": paired_comparison(old["A2"], new["A2"]), "B14-B2": paired_comparison(old["B2"], new["B2"]),
                                "B14-A14": paired_comparison(new["A2"], new["B2"]), "B2-A2": paired_comparison(old["A2"], old["B2"])}
        comparisons[dataset]["descriptive_interaction_accuracy_delta"] = comparisons[dataset]["B14-A14"]["accuracy_delta"] - comparisons[dataset]["B2-A2"]["accuracy_delta"]
        costs[dataset] = {name: performance(rows) for name, rows in (("A2", old["A2"]), ("B2", old["B2"]), ("A14", new["A2"]), ("B14", new["B2"]))}
        for group in sorted({r["group"] for r in new["A2"]}):
            for a in new:
                subset = [r for r in new[a] if r["group"] == group]
                groups.append({"dataset": dataset, "group": group, "mechanism": subset[0]["mechanism"], "arm": a, **compute_metrics(subset)})
    summary = {"run_id": config["run_id"], "baseline_run_id": config["historical_run_id"], "baseline_metrics_sha256": file_hash(baseline_report / "metrics.json"),
               "comparisons": comparisons, "performance": costs, "groups": groups,
               "interpretation": "Exploratory paired model upgrade, not parameter-count causality; 14 challenge/7 basic groups; no IID significance test."}
    environment_path = ROOT / config["output_root"] / config["run_id"] / "environment.json"
    if environment_path.exists():
        environment = json.loads(environment_path.read_text(encoding="utf-8"))
        telemetry = Path(environment["startup"]["log_directory"]) / "resources.jsonl"
        samples = read_jsonl(telemetry)
        summary["hardware"] = {"environment": environment, "sampled_resources": summarize(samples), "telemetry_sha256": file_hash(telemetry)}
    atomic_json(destination / "upgrade_comparison.json", summary)
    csv_file(destination / "metrics_by_group.csv", groups, ["dataset", "group", "mechanism", "arm", "n", "correct", "accuracy", "invalid", "both_impossible_count"])
    flat = [{**r, "display_arm": config.get("arm_labels", {}).get(r["arm"], r["arm"]),
             **{key: r.get("usage", {}).get(key) for key in ("prompt_tokens", "completion_tokens")},
             "reason_quality_flags": json.dumps(r.get("reason_quality_flags", []))} for r in records]
    fields = ["dataset", "arm", "display_arm", "id", "group", "mechanism", "gold_label", "predicted_label", "status", "parse_status", "parse_error",
              "protocol_valid", "fields_valid", "logic_valid", "claim_true_world", "claim_false_world", "world_reason_true", "world_reason_false", "direct_reason",
              "reason_quality_flags", "finish_reason", "latency_seconds", "prompt_tokens", "completion_tokens", "preflight_prompt_tokens", "completion_request_attempts"]
    csv_file(destination / "predictions.csv", flat, fields)
    selected = []
    for row in select_review(config, records):
        source = pilot[row["dataset"]][row["id"]]
        selected.append({**{key: row.get(key) for key in fields}, "evidence": source["evidence"], "claim": source["claim"],
                         "semantic_review_status": "pending_manual_review", "reason_state_contradiction": "", "review_note": ""})
    review_path = destination / "reason_consistency_review.csv"
    # Preserve authored adjudication if report is recomputed.
    if not review_path.exists():
        csv_file(review_path, selected, fields + ["evidence", "claim", "semantic_review_status", "reason_state_contradiction", "review_note"])
    typical = []
    for sample_id in config.get("review", {}).get("typical_ids", []):
        dataset = next(d for d in DATASETS if sample_id in pilot[d])
        source = pilot[dataset][sample_id]
        for a in ("A2", "B2"):
            old = next(r for r in history[dataset] if r["arm"] == a and r["id"] == sample_id)
            new = by_key[dataset, a, sample_id]
            typical.append({"dataset": dataset, "id": sample_id, "arm": a, "gold": source["label"], "evidence": source["evidence"], "claim": source["claim"],
                            "4b_prediction": prediction(old), "14b_prediction": prediction(new),
                            **{f"{model}_{key}": row.get(key) for model, row in (("4b", old), ("14b", new))
                               for key in ("claim_true_world", "claim_false_world", "world_reason_true", "world_reason_false", "direct_reason")}})
    csv_file(destination / "typical_errors.csv", typical, list(typical[0]) if typical else ["id"])
    lines = ["# 第三轮：14B 非思考模型升级配对实验", "", f"运行 `{config['run_id']}`；基线 `{config['historical_run_id']}`。",
             "", "A14/B14 内部使用 A2/B2 键；逐字复用 v2 Prompt 与 maxLength=320 Schema。未微调、未加示例、未使用 test 推理。",
             "", f"模型 `{config['model']['repository']}`，revision `{config['model']['revision']}`，SHA-256 `{config['model']['sha256']}`。",
             f"llama.cpp {config['model']['backend_release']}，context={config['model']['context_tokens']}，max_tokens=1024，temperature=0，seed=42，stream/cache=false，单并发。",
             "", "thinking 在请求和 /apply-template 均显式关闭；原始输出保留，检查 reasoning_content、think 标记及 reasoning_tokens。技术探针与每题证据见 outputs；环境指纹包含实际卸载与 DLL 哈希。",
             "", "这是模型升级比较。4B-Instruct-2507 与 Qwen3-14B 的训练阶段、模板有差异，不能将变化全归因于参数量。组内变体相关：挑战集 14 组、基础集 7 组；本报告仅作探索性描述，不做逐题独立性假设或显著性宣称。",
             "", "无效、截断、网络失败计错；双 IMPOSSIBLE 仍为逻辑无效。合法 JSON 不代表推理正确。每题一次正式生成，技术测量单独保存。", ""]
    for dataset in DATASETS:
        d = receipt["datasets"][dataset]
        lines += [f"## {dataset}", "", "| 条件 | 正确/全部 | 准确率 | 宏 F1 | S召回 | R召回 | NEI召回 | NEI→R | S→NEI | R→NEI |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        comparison_metrics = [(a, compute_metrics([r for r in history[dataset] if r["arm"] == a])) for a in ("A2", "B2")]
        comparison_metrics += [(name, d["arms"][a]) for a, name in (("A2", "A14"), ("B2", "B14"))]
        for name, m in comparison_metrics:
            lines.append(f"| {name} | {m['correct']}/{m['n']} | {pct(m['accuracy'])} | {decimal(m['macro_f1'])} | " + " | ".join(pct(m['classes'][label]['recall']) for label in LABELS) + f" | {m['nei_to_refutes']} | {m['supports_to_nei']} | {m['refutes_to_nei']} |")
        lines += ["", "| 比较 | 准确率差 pp | 错→对 | 对→错 |", "|---|---:|---:|---:|"]
        for name, pair in comparisons[dataset].items():
            if isinstance(pair, dict):
                lines.append(f"| {name} | {100*pair['accuracy_delta']:+.2f} | {pair['improved']} | {pair['harmed']} |")
        lines += ["", f"描述性交互差值 `(B14−A14)−(B2−A2)`：{100*comparisons[dataset]['descriptive_interaction_accuracy_delta']:+.2f} pp。", "",
                  "| 条件 | INVALID率 | 字段有效率 | 协议有效率 | 双IMPOSSIBLE | 理由达320字符 | 生成截断 |", "|---|---:|---:|---:|---:|---:|---:|"]
        for a, name in (("A2", "A14"), ("B2", "B14")):
            m = d["arms"][a]
            lines.append(f"| {name} | {pct(m['invalid_rate'])} | {pct(m['fields_valid_rate'])} | {pct(m['protocol_valid_rate'])} | {m['both_impossible_count']} | {m['reason_at_length_limit_count']} | {m['truncated_count']} |")
        for a, name in (("A2", "A14"), ("B2", "B14")):
            m = d["arms"][a]
            lines += ["", f"{name} 混淆矩阵（行 gold，列预测）：", "", "| gold | SUPPORTS | REFUTES | NEI | INVALID |", "|---|---:|---:|---:|---:|"]
            for label, cells in m["confusion_matrix"].items():
                lines.append(f"| {label} | " + " | ".join(str(cells[k]) for k in (*LABELS, "INVALID")) + " |")
            lines.append("")
        lines += ["| 机制 | 关联group | A14准确率 | B14准确率 |", "|---|---|---:|---:|"]
        for mechanism, values in d["mechanisms"].items():
            group_names = sorted({r['group'] for r in pilot[dataset].values() if r['mechanism'] == mechanism})
            lines.append(f"| {mechanism} | {', '.join(group_names)} | {pct(values['A2']['accuracy'])} | {pct(values['B2']['accuracy'])} |")
        lines += ["", "| 条件 | 总请求秒 | 延迟p50秒 | p95秒 | 端到端输出tokens/s | 后端解码tokens/s |", "|---|---:|---:|---:|---:|---:|"]
        for name, p in costs[dataset].items():
            lines.append(f"| {name} | {decimal(p['request_seconds'])} | {decimal(p['latency_p50_seconds'])} | {decimal(p['latency_p95_seconds'])} | {decimal(p['end_to_end_completion_tokens_per_second'])} | {decimal(p['backend_decode_tokens_per_second_mean'])} |")
        lines.append("")
    lines += ["## 硬件与复核", "", "完整硬件采样摘要及环境记录：`upgrade_comparison.json`。显存为整卡采样值，包含其他应用；采样峰值可能低于瞬时峰值。",
              "", "四个预指定案例的 4B/14B 原始世界状态和理由见 `typical_errors.csv`。固定每数据集每 gold 标签前三个 ID，共 18 个 B14 样本见 `reason_consistency_review.csv`；人工复核状态单独标明，不自动根据 gold 或关键词改判。",
              "", "`metrics.json` 为两组统计，`upgrade_comparison.json` 为跨模型配对和成本，`predictions.csv` 为逐题摘要；独立审计需运行 `scripts/audit_14b_run.py`。报告生成并不等于独立审计通过。", ""]
    atomic_bytes(destination / "pilot_report.md", "\n".join(lines).encode("utf-8"))
