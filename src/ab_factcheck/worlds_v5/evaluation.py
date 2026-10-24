"""Paired all-scheduled metrics, trace receipts and semantic review queues."""
from collections import Counter, defaultdict
import csv
import io
import json

from ..common import atomic_bytes, atomic_json, file_hash, now, read_jsonl, write_jsonl
from .experiment import EXPERIMENT, STATIC_CASES
from .orchestrator import digest

LABELS = ("SUPPORTS", "REFUTES", "NOT ENOUGH INFO")
STAGES = ("generate_T", "generate_F", "verify_T", "verify_F", "baseline_A27")


def metrics(rows, arm):
    matrix = {g: {p: 0 for p in (*LABELS, "INVALID")} for g in LABELS}
    for r in rows:
        pred = r[arm] if r[arm] in LABELS else "INVALID"
        matrix[r["gold"]][pred] += 1
    n = len(rows)
    correct = sum(matrix[g][g] for g in LABELS)
    valid = sum(matrix[g][p] for g in LABELS for p in LABELS)
    classes = {}
    for label in LABELS:
        support = sum(matrix[label].values())
        predicted = sum(matrix[g][label] for g in LABELS)
        tp = matrix[label][label]
        classes[label] = {"support": support, "precision": tp / predicted if predicted else 0,
                          "recall": tp / support if support else None,
                          "f1": 2 * tp / (support + predicted) if support + predicted else 0}
    return {"scheduled": n, "correct": correct, "valid": valid,
            "completed": sum(r[arm] is not None for r in rows),
            "accuracy_all_scheduled": correct / n if n else None,
            "coverage": valid / n if n else None, "conditional_accuracy": correct / valid if valid else None,
            "macro_f1": sum(v["f1"] for v in classes.values()) / 3 if n else None,
            "classes": classes, "confusion_matrix": matrix,
            "nei_to_refutes": matrix["NOT ENOUGH INFO"]["REFUTES"],
            "supports_to_nei": matrix["SUPPORTS"]["NOT ENOUGH INFO"],
            "refutes_to_nei": matrix["REFUTES"]["NOT ENOUGH INFO"],
            "unresolved_by_gold": dict(Counter(r["gold"] for r in rows if r[arm] is not None and r[arm] not in LABELS)),
            "not_run_by_gold": dict(Counter(r["gold"] for r in rows if r[arm] is None))}


def paired(rows):
    complete = [r for r in rows if r["A27"] is not None and r["V5"] is not None]
    improved = [r["id"] for r in complete if r["V5"] == r["gold"] and r["A27"] != r["gold"]]
    harmed = [r["id"] for r in complete if r["V5"] != r["gold"] and r["A27"] == r["gold"]]
    return {"scheduled": len(rows), "complete_pairs": len(complete), "improved_ids": improved, "harmed_ids": harmed,
            "delta_on_complete_pairs": (len(improved) - len(harmed)) / len(complete) if complete else None,
            "complete_pair_subset_is_not_full_evaluation": len(complete) != len(rows)}


def csv_file(path, rows):
    if not rows:
        atomic_bytes(path, b"")
        return
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_bytes(path, buffer.getvalue().encode("utf-8-sig"))


def report(exp):
    out = exp.root / EXPERIMENT / "reports" / (exp.config["run_id"] + "_" + exp.phase)
    records, traces, review, rows = [], [], [], []
    if exp.phase == "fresh":
        sources = [(d, r) for d, v in exp.manifest["datasets"].items() for r in v["rows"]]
    else:
        sources = [("synthetic", {**r, "label": r["gold"], "mechanism": "synthetic", "group": r["id"]})
                   for r in read_jsonl(exp.root / EXPERIMENT / "synthetic_smoke_cases.jsonl")]
    for dataset, row in sources:
        base = exp.directory / "records" / digest([dataset, row["id"]])
        result = {"dataset": dataset, "id": row["id"], "group": row["group"], "mechanism": row["mechanism"],
                  "gold": row["label"], "A27": None, "V5": None, "T": None, "F": None,
                  "generate_T": None, "generate_F": None, "verify_T": None, "verify_F": None}
        for stage in STAGES:
            path = base / (stage + ".json")
            if not path.exists():
                continue
            r = json.loads(path.read_text(encoding="utf-8"))
            records.append((dataset, row, stage, r, path))
            validation = r["validation"]
            traces.append({"dataset": dataset, "id": row["id"], "stage": stage,
                "raw_record_path": path.relative_to(exp.root).as_posix(), "raw_record_sha256": file_hash(path),
                "request_sha256": r["request_sha256"], "upstream_sha256": r["upstream_sha256"],
                "protocol_valid": validation["protocol_valid"], "schema_valid": validation.get("schema_valid"),
                "errors": validation["errors"], "quality_flags": validation.get("quality_flags", []),
                "provider_validation_issues": r["provider_validation_issues"], "usage": r["usage"],
                "finish_reason": r["finish_reason"], "latency_seconds": r["latency_seconds"],
                "response_id_sha256": r.get("response_id_sha256"), "system_fingerprint": r.get("system_fingerprint"),
                "decision": (validation.get("parsed") or {}).get("decision"),
                "attempts": len(r["attempts"]), "nonthinking_validation": r["nonthinking_validation"]})
            good = validation["protocol_valid"] and not r["provider_validation_issues"]
            parsed = validation.get("parsed") or {}
            if stage == "baseline_A27":
                result["A27"] = parsed["verdict"] if good else "INVALID_PROTOCOL"
            else:
                result[stage] = "valid" if good else "invalid"
            if stage.startswith("verify_") and good:
                result[stage[-1]] = parsed["decision"]
        path = base / "verdict.json"
        if path.exists():
            result["V5"] = json.loads(path.read_text(encoding="utf-8"))["label"]
        rows.append(result)
    for dataset, row, stage, record, path in records:
        # Every non-WITNESS decision plus the first three IDs per gold/dataset.
        fixed = sorted(r["id"] for d, r in sources if d == dataset and r["label"] == row["label"])[:3]
        parsed = record["validation"].get("parsed") or {}
        selected = row["id"] in fixed or parsed.get("decision") in ("TARGET_CONTRADICTS_EVIDENCE", "CANDIDATE_INVALID", "UNDETERMINED")
        if selected:
            review.append({"dataset": dataset, "id": row["id"], "gold": row["label"], "stage": stage,
                "evidence": row["evidence"], "claim": row["claim"], "target_condition": parsed.get("target_condition", ""),
                "candidate_world": parsed.get("candidate_world", ""), "decision": parsed.get("decision", parsed.get("verdict", "")),
                "reason": parsed.get("reason", ""), "evidence_anchor": parsed.get("evidence_anchor", ""),
                "quality_flags": "|".join(record["validation"].get("quality_flags", [])),
                "raw_sha256": file_hash(path), "semantic_review_status": "pending"})
    by_dataset = {}
    for dataset in sorted({r["dataset"] for r in rows}):
        rs = [r for r in rows if r["dataset"] == dataset]
        by_dataset[dataset] = {"A27": metrics(rs, "A27"), "V5": metrics(rs, "V5"), "paired": paired(rs),
            "decision_pairs": dict(Counter(str((r["T"], r["F"])) for r in rs)),
            "by_mechanism": {m: {a: metrics([r for r in rs if r["mechanism"] == m], a) for a in ("A27", "V5")} for m in sorted({r["mechanism"] for r in rs})},
            "by_group": {g: {a: metrics([r for r in rs if r["group"] == g], a) for a in ("A27", "V5")} for g in sorted({r["group"] for r in rs})}}
    costs = {}
    for stage in STAGES:
        rs = [r for _, _, s, r, _ in records if s == stage]
        costs[stage] = {"received": len(rs), "schema_valid": sum(r["validation"].get("schema_valid", False) for r in rs),
            "protocol_valid": sum(r["validation"]["protocol_valid"] for r in rs),
            "prompt_tokens": sum(r["usage"].get("prompt_tokens", 0) for r in rs),
            "completion_tokens": sum(r["usage"].get("completion_tokens", 0) for r in rs),
            "client_seconds_including_throttle": sum(r["latency_seconds"] for r in rs),
            "length_limit_hits": sum(bool(r["validation"].get("quality_flags")) for r in rs),
            "decisions": dict(Counter((r["validation"].get("parsed") or {}).get("decision") for r in rs))}
    failures = []
    for p in exp.directory.rglob("*.errors.json"):
        failures.append({"path": p.relative_to(exp.root).as_posix(), "events": json.loads(p.read_text(encoding="utf-8"))})
    all_responses = []
    for p in exp.directory.rglob("*.json"):
        value = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(value, dict) and "request_payload" in value:
            all_responses.append(value)
    summary = {"generated_at": now(), "phase": exp.phase, "run_id": exp.config["run_id"],
        "state": "complete" if all(r["V5"] is not None and (exp.phase == "smoke" or r["A27"] is not None) for r in rows) else "partial_or_blocked",
        "planned_items": len(rows), "v5_completed": sum(r["V5"] is not None for r in rows),
        "baseline_completed": sum(r["A27"] is not None for r in rows), "datasets": by_dataset, "stage_costs": costs,
        "received_responses_all_phases": len(all_responses),
        "successful_usage_all_phases": sum(r["usage"].get("total_tokens", 0) for r in all_responses),
        "failures": failures, "ambiguous_inflight": [p.relative_to(exp.root).as_posix() for p in exp.directory.rglob("*.inflight")],
        "no_formal_metrics_claimed_when_unrun": True, "estimates_are_not_formal_satisfiability_proofs": True}
    atomic_json(out / "metrics.json", summary)
    atomic_json(out / "run_fingerprint.json", exp.dag.fingerprint)
    write_jsonl(out / "node_receipts.jsonl", traces)
    csv_file(out / "predictions.csv", rows)
    csv_file(out / "semantic_review_queue.csv", review)
    return summary
