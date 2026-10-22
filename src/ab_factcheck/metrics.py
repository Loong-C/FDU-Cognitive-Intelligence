"""Metrics with explicit invalid predictions and paired denominators."""

from statistics import mean, median

from .common import LABELS


def prediction(row: dict) -> str:
    return row["predicted_label"] if row.get("parse_status") == "ok" and row.get("predicted_label") in LABELS else "INVALID"


def correct(row: dict) -> bool:
    return prediction(row) == row["gold_label"]


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def compute_metrics(rows: list[dict]) -> dict:
    matrix = {gold: {pred: 0 for pred in (*LABELS, "INVALID")} for gold in LABELS}
    for row in rows:
        matrix[row["gold_label"]][prediction(row)] += 1
    n = len(rows)
    valid = sum(prediction(row) != "INVALID" for row in rows)
    right = sum(correct(row) for row in rows)
    classes = {}
    for label in LABELS:
        tp = matrix[label][label]
        gold = sum(matrix[label].values())
        predicted = sum(matrix[other][label] for other in LABELS)
        precision, recall = ratio(tp, predicted), ratio(tp, gold)
        f1 = ratio(2 * tp, gold + predicted)
        classes[label] = {"support": gold, "predicted_count": predicted,
                          "precision": precision if precision is not None else 0.0,
                          "recall": recall, "f1": f1 if gold else None}
    latencies = [row["latency_seconds"] for row in rows if isinstance(row.get("latency_seconds"), (int, float))]
    tokens = [row.get("usage", {}).get("completion_tokens") for row in rows]
    tokens = [value for value in tokens if isinstance(value, (int, float))]
    inconsistent = sum(row.get("consistency_status") == "inconsistent" for row in rows)
    world_available = sum(row.get("consistency_status") in ("consistent", "inconsistent", "both_impossible") for row in rows)
    result = {
        "n": n, "valid": valid, "invalid": n - valid, "correct": right,
        "accuracy": ratio(right, n), "valid_only_accuracy": ratio(right, valid),
        "invalid_rate": ratio(n - valid, n), "classes": classes,
        "macro_f1": mean([v["f1"] for v in classes.values() if v["f1"] is not None]) if n else None,
        "confusion_matrix": matrix,
        "nei_to_refutes": matrix["NOT ENOUGH INFO"]["REFUTES"],
        "nei_to_refutes_rate": ratio(matrix["NOT ENOUGH INFO"]["REFUTES"], sum(matrix["NOT ENOUGH INFO"].values())),
        "latency_mean_seconds": mean(latencies) if latencies else None,
        "latency_median_seconds": median(latencies) if latencies else None,
        "mean_completion_tokens": mean(tokens) if tokens else None,
        "inconsistent_count": inconsistent,
        "inconsistent_rate_all": ratio(inconsistent, n),
        "inconsistent_rate_world_available": ratio(inconsistent, world_available),
        "both_impossible_count": sum(row.get("consistency_status") == "both_impossible" for row in rows),
        "request_failed_count": sum(row.get("status") == "request_failed" for row in rows),
        "request_failure_rate": ratio(sum(row.get("status") == "request_failed" for row in rows), n),
        "not_run_count": sum(row.get("status") == "not_run" for row in rows),
    }
    if any(r.get("output_protocol") == "json_schema_v2" for r in rows):
        for field in ("json_valid", "fields_valid", "protocol_valid"):
            count = sum(r.get(field) is True for r in rows)
            result[field + "_count"] = count
            result[field + "_rate"] = ratio(count, n)
        available = sum(r.get("logic_valid") is not None for r in rows)
        logic_valid = sum(r.get("logic_valid") is True for r in rows)
        result.update(logic_available_count=available, logic_valid_count=logic_valid,
                      logic_valid_rate=ratio(logic_valid, available),
                      truncated_count=sum(r.get("finish_reason") == "length" for r in rows),
                      reason_quality_flag_count=sum(bool(r.get("reason_quality_flags")) for r in rows),
                      reason_at_length_limit_count=sum(any(f.startswith("at_length_limit_") for f in r.get("reason_quality_flags", [])) for r in rows),
                      empty_reason_count=sum(any(f.startswith("empty_") for f in r.get("reason_quality_flags", [])) for r in rows),
                      supports_to_nei=matrix["SUPPORTS"]["NOT ENOUGH INFO"],
                      refutes_to_nei=matrix["REFUTES"]["NOT ENOUGH INFO"])
    return result


def paired_comparison(before: list[dict], after: list[dict]) -> dict:
    left, right = {row["id"]: row for row in before}, {row["id"]: row for row in after}
    if len(left) != len(before) or len(right) != len(after) or left.keys() != right.keys():
        raise ValueError("Paired comparison requires unique identical ID sets")
    improved, harmed = [], []
    for sample_id in sorted(left):
        a, b = left[sample_id], right[sample_id]
        if a["gold_label"] != b["gold_label"] or a["group"] != b["group"]:
            raise ValueError("Paired sample metadata differs")
        if correct(a) != correct(b):
            (improved if correct(b) else harmed).append(sample_id)
    transitions = {}
    if any(r.get("output_protocol") == "json_schema_v2" for r in before):
        candidates = [i for i, r in left.items() if r["gold_label"] == "NOT ENOUGH INFO" and prediction(r) == "REFUTES"]
        transitions = {"nei_refuted_before_ids": sorted(candidates),
                       "nei_refutes_corrected_ids": sorted(i for i in candidates if prediction(right[i]) == "NOT ENOUGH INFO"),
                       "supports_correct_to_nei_ids": sorted(i for i, r in left.items() if r["gold_label"] == "SUPPORTS" and correct(r) and prediction(right[i]) == "NOT ENOUGH INFO"),
                       "refutes_correct_to_nei_ids": sorted(i for i, r in left.items() if r["gold_label"] == "REFUTES" and correct(r) and prediction(right[i]) == "NOT ENOUGH INFO")}
    return {"n": len(left), "improved_ids": improved, "harmed_ids": harmed, **transitions,
            "improved": len(improved), "harmed": len(harmed),
            "accuracy_delta": ratio(len(improved) - len(harmed), len(left))}
