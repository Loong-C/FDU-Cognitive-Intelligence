"""Offline summaries of immutable continuation records; never creates a client."""
from collections import Counter, defaultdict
import json
from pathlib import Path

from ab_factcheck.common import atomic_json, file_hash, now
from ab_factcheck.worlds_v5.evaluation import metrics, paired
from ab_factcheck.worlds_v5.orchestrator import digest

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/005_layered_worlds"
RUN = "layered_worlds_qwen38_27b_v5_r2_free"
LABELS = ("SUPPORTS", "REFUTES", "NOT ENOUGH INFO")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def summary():
    manifest = read(EXP / "fresh_dev_v5.json")
    rows, missing, node_counts, costs = [], [], Counter(), defaultdict(list)
    decisions, states, caps = Counter(), Counter(), Counter()
    model_ids, fingerprints, finishes, nonthinking = Counter(), Counter(), Counter(), Counter()
    provider_issues, invalid = [], []
    raw_index = {}
    for phase in ("smoke", "fresh"):
        directory = ROOT / "outputs/runs" / (RUN + "_" + phase)
        for p in directory.rglob("*.json"):
            r = read(p)
            if not isinstance(r, dict) or "request_payload" not in r:
                continue
            raw_index[p.relative_to(ROOT).as_posix()] = file_hash(p)
            costs[(phase, p.stem, bool(r.get("reused_from")))].append(r)
            model_ids[r["actual_model_id"]] += 1
            fingerprints[str(r["system_fingerprint"])] += 1
            finishes[r["finish_reason"]] += 1
            nonthinking[json.dumps(r["nonthinking_validation"], sort_keys=True)] += 1
            if r["provider_validation_issues"]:
                provider_issues.append(str(p.relative_to(ROOT)))
            # The deliberately invalid technical controls are retained separately.
            if not r["validation"]["protocol_valid"]:
                invalid.append(str(p.relative_to(ROOT)))
            if phase == "fresh":
                node_counts[p.stem] += 1
                for flag in r["validation"].get("quality_flags", []):
                    caps[p.stem + ":" + flag] += 1
                parsed = r["validation"].get("parsed") or {}
                if "decision" in parsed:
                    decisions[p.stem + ":" + parsed["decision"]] += 1
    for dataset, source in manifest["datasets"].items():
        for row in source["rows"]:
            directory = ROOT / "outputs/runs" / (RUN + "_fresh") / "records" / digest([dataset, row["id"]])
            a = read(directory / "baseline_A27.json") if (directory / "baseline_A27.json").exists() else None
            v = read(directory / "verdict.json") if (directory / "verdict.json").exists() else None
            item = {"dataset": dataset, "id": row["id"], "group": row["group"], "mechanism": row["mechanism"],
                    "gold": row["label"], "A27": a["validation"]["parsed"].get("verdict") if a and a["validation"]["protocol_valid"] and not a["provider_validation_issues"] else None,
                    "V5": v["label"] if v else None}
            rows.append(item)
            if v:
                states[str((v["true_state"], v["false_state"]))] += 1
            else:
                missing.append({**item, "saved_stages": [p.stem for p in directory.glob("*.json") if ".errors" not in p.stem]})
    complete = [r for r in rows if r["A27"] is not None and r["V5"] is not None]
    paired_costs = {}
    for arm, stages in (("A27", ("baseline_A27",)), ("V5", ("generate_T", "generate_F", "verify_T", "verify_F"))):
        values = []
        for row in complete:
            directory = ROOT / "outputs/runs" / (RUN + "_fresh") / "records" / digest([row["dataset"], row["id"]])
            values.extend(read(directory / (stage + ".json")) for stage in stages)
        paired_costs[arm] = {"items": len(complete), "calls": len(values),
            "tokens": sum(v["usage"]["total_tokens"] for v in values),
            "server_seconds": sum(v["usage"].get("total_time", 0) for v in values),
            "client_seconds_including_throttle": sum(v["latency_seconds"] for v in values)}
    subsets = {"all_scheduled": rows, "complete_pairs": complete}
    calculated = {}
    for name, subset in subsets.items():
        calculated[name] = {"combined": {a: metrics(subset, a) for a in ("A27", "V5")}, "paired": paired(subset),
            "datasets": {d: {a: metrics([r for r in subset if r["dataset"] == d], a) for a in ("A27", "V5")} for d in manifest["datasets"]},
            "mechanisms": {d + "/" + m: {a: metrics([r for r in subset if r["dataset"] == d and r["mechanism"] == m], a) for a in ("A27", "V5")} for d, m in sorted({(r["dataset"], r["mechanism"]) for r in rows})}}
    stage_costs = []
    for (phase, stage, reused), rs in sorted(costs.items()):
        stage_costs.append({"phase": phase, "stage": stage, "reused": reused, "responses": len(rs),
            "prompt_tokens": sum(r["usage"].get("prompt_tokens", 0) for r in rs),
            "completion_tokens": sum(r["usage"].get("completion_tokens", 0) for r in rs),
            "total_tokens": sum(r["usage"].get("total_tokens", 0) for r in rs),
            "server_seconds": sum(r["usage"].get("total_time", 0) for r in rs),
            "client_seconds_including_throttle": sum(r["latency_seconds"] for r in rs)})
    ledger = read(ROOT / "outputs/groq/quota.json")
    snapshot = read(ROOT / "outputs/worlds_v5_history/before_free_continuation.json")
    attempts = ledger["attempts"][snapshot["ledger_prefix_attempts"]:]
    stops = {phase: read(ROOT / "outputs/runs" / (RUN + "_" + phase) / "last_stop.json")
             for phase in ("smoke", "fresh") if (ROOT / "outputs/runs" / (RUN + "_" + phase) / "last_stop.json").exists()}
    return {"generated_at": now(), "run_id": RUN, "partial_subset_warning": len(complete) != len(rows),
        "manifest_sha256": file_hash(EXP / "fresh_dev_v5.json"), "metrics": calculated,
        "rows": rows, "incomplete_items": missing, "fresh_received_nodes": dict(node_counts),
        "fresh_decisions": dict(decisions), "fresh_state_pairs": dict(states), "fresh_quality_flags": dict(caps),
        "model_ids": dict(model_ids), "system_fingerprints": dict(fingerprints), "finish_reasons": dict(finishes),
        "nonthinking_checks": dict(nonthinking), "provider_issue_paths": provider_issues,
        "protocol_invalid_including_deliberate_controls": invalid, "stage_costs": stage_costs, "complete_pair_costs": paired_costs,
        "new_attempts": len(attempts), "new_attempt_statuses": dict(Counter(a["status"] for a in attempts)),
        "new_http_statuses": dict(Counter(str(a.get("http_status")) for a in attempts)),
        "new_successful_tokens": sum(a.get("usage", {}).get("total_tokens", 0) for a in attempts),
        "new_charged_tokens_including_unknown_reservations": sum(a["charged_tokens"] for a in attempts),
        "first_new_requested_at": attempts[0]["requested_at"] if attempts else None,
        "last_new_requested_at": attempts[-1]["requested_at"] if attempts else None,
        "last_rate_limit_headers": attempts[-1].get("rate_limits") if attempts else None,
        "stops": stops, "raw_files_sha256": raw_index}


def tables(result):
    lines = ["# 续跑统计表（由原始记录离线生成）", "", "生成时间：" + result["generated_at"], "",
             "主要分母为冻结的全部104题。完整配对子集另列，不能替代完整评测；未决和缺失均计错。", ""]
    def table(headers, rows):
        lines.extend(["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"])
        lines.extend("| " + " | ".join(str(v) for v in row) + " |" for row in rows)
        lines.append("")
    def pct(v):
        return "N/A" if v is None else f"{100*v:.2f}%"
    for subset, title in (("all_scheduled", "全部预定样本"), ("complete_pairs", "已完成配对子集（描述性）")):
        data = result["metrics"][subset]
        lines.extend(["## " + title, ""])
        rows = []
        for dataset, arms in {"combined": data["combined"], **data["datasets"]}.items():
            for arm, v in arms.items():
                rows.append([dataset, arm, f'{v["correct"]}/{v["scheduled"]}', pct(v["accuracy_all_scheduled"]),
                    f'{v["macro_f1"]:.4f}' if v["macro_f1"] is not None else "N/A", pct(v["coverage"]), pct(v["conditional_accuracy"])])
        table(["数据", "方法", "正确/分母", "准确率", "宏F1", "三分类覆盖率", "已给三分类条件准确率"], rows)
        rows = []
        for dataset, arms in data["datasets"].items():
            for arm, v in arms.items():
                for label, c in v["classes"].items():
                    rows.append([dataset, arm, label, c["support"], pct(c["precision"]), pct(c["recall"]), f'{c["f1"]:.4f}'])
        table(["数据", "方法", "类别", "支持数", "精确率", "召回率", "F1"], rows)
        rows = []
        for dataset, arms in data["datasets"].items():
            for arm, v in arms.items():
                for gold, matrix in v["confusion_matrix"].items():
                    rows.append([dataset, arm, gold, *[matrix[p] for p in (*LABELS, "INVALID")]])
        table(["数据", "方法", "gold", "预测S", "预测R", "预测NEI", "INVALID（未决/缺失）"], rows)
        table(["数据", "方法", "NEI→R", "NEI→S", "S→NEI", "R→NEI", "未决按gold", "未运行按gold"],
            [[d, a, v["nei_to_refutes"], v["confusion_matrix"]["NOT ENOUGH INFO"]["SUPPORTS"], v["supports_to_nei"], v["refutes_to_nei"],
              json.dumps(v["unresolved_by_gold"]), json.dumps(v["not_run_by_gold"])] for d, arms in data["datasets"].items() for a,v in arms.items()])
    lines.extend(["## 机制与场景组", "", "每个数据集/机制恰好冻结一个组；因此下表同时是按机制及完整group的统计，包含未完成组。", ""])
    groups = {(r["dataset"] + "/" + r["mechanism"]): r["group"] for r in result["rows"]}
    table(["数据/机制", "group", "预定题数", "完成配对", "A27正确", "V5正确", "V5未决"],
        [[m, groups[m], arms["A27"]["scheduled"], result["metrics"]["complete_pairs"]["mechanisms"][m]["A27"]["scheduled"],
          arms["A27"]["correct"], arms["V5"]["correct"], sum(arms["V5"]["unresolved_by_gold"].values())]
         for m, arms in result["metrics"]["all_scheduled"]["mechanisms"].items()])
    lines.extend(["## 节点成本与状态", "", "smoke 的 reused=true 行为旧响应谱系，不计入本次新增用量。客户端秒含节流；服务端秒来自 usage.total_time。", ""])
    table(["阶段", "节点", "复用", "响应", "输入token", "输出token", "总token", "客户端秒", "服务端秒"],
        [[r["phase"],r["stage"],r["reused"],r["responses"],r["prompt_tokens"],r["completion_tokens"],r["total_tokens"],f'{r["client_seconds_including_throttle"]:.2f}',f'{r["server_seconds"]:.2f}'] for r in result["stage_costs"]])
    lines.extend(["同一完整配对子集的成本：", ""])
    table(["方法", "题数", "调用数", "总token", "客户端秒", "服务端秒"],
        [[a,v["items"],v["calls"],v["tokens"],f'{v["client_seconds_including_throttle"]:.2f}',f'{v["server_seconds"]:.2f}'] for a,v in result["complete_pair_costs"].items()])
    for key, title in (("fresh_decisions", "正式验证器决策"), ("fresh_state_pairs", "正式最终状态对"), ("fresh_quality_flags", "正式字符限长标记"), ("model_ids", "实际模型ID"), ("system_fingerprints", "托管系统指纹")):
        lines.extend(["### " + title, ""])
        table(["项目", "数量"], result[key].items())
    lines.extend(["## 调用记账", ""])
    table(["项目", "值"], [[key, json.dumps(result[key], ensure_ascii=False)] for key in (
        "new_attempts", "new_attempt_statuses", "new_http_statuses", "new_successful_tokens", "new_charged_tokens_including_unknown_reservations",
        "first_new_requested_at", "last_new_requested_at", "last_rate_limit_headers", "stops")])
    lines.extend(["未完成逐题阶段、原始文件哈希、非思考检查及完整指标见 continuation_summary.json；正式逐题预测和审阅队列见 reports/ 下对应运行目录。", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    result = summary()
    atomic_json(EXP / "continuation_summary.json", result)
    (EXP / "continuation_tables.md").write_text(tables(result), encoding="utf-8")
    print(json.dumps({"pairs": result["metrics"]["complete_pairs"]["paired"],
        "new_attempts": result["new_attempts"], "new_successful_tokens": result["new_successful_tokens"],
        "stops": result["stops"]}, ensure_ascii=True))
