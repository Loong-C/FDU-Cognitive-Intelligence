"""Offline dev reporting, with paired denominators and group bootstrap intervals."""
import argparse
from collections import defaultdict
import csv
import io
import itertools
import json
import random

from ..common import LABELS, ROOT, atomic_bytes, atomic_json, file_hash
from ..metrics import compute_metrics, paired_comparison
from .experiment import EXPERIMENT, OUTPUT, load_dev, verify
from .inference import conservative_consensus, digest, parse


def metric_row(item, label, gold):
    return {"id": item["id"], "group": item["group"], "mechanism": item["mechanism"],
            "gold_label": gold, "predicted_label": label, "parse_status": "ok" if label in LABELS else "invalid"}


def gate(base, candidate):
    """No scalar objective is allowed to conceal a class recall regression."""
    names = ["accuracy", "macro_f1"]
    differences = {k: candidate[k] - base[k] for k in names}
    for label in LABELS:
        a, b = base["classes"][label]["recall"], candidate["classes"][label]["recall"]
        differences["recall_" + label] = None if a is None or b is None else b - a
    return {"deltas": differences,
            "no_regression": all(x is not None and x >= -1e-12 for x in differences.values()),
            "accuracy_improved": differences["accuracy"] > 1e-12}


def cluster_interval(before, after, iterations=5000, seed=20261028):
    """Resample paired groups, not individual related variants."""
    by_group = defaultdict(list)
    b = {r["id"]: r for r in before}
    for row in after:
        by_group[row["group"]].append(int(row["predicted_label"] == row["gold_label"]) -
                                    int(b[row["id"]]["predicted_label"] == row["gold_label"]))
    groups = list(sorted(by_group))
    if len(groups) < 2:
        return {"available": False, "groups": len(groups)}
    rng = random.Random(seed)
    values = []
    for _ in range(iterations):
        draw = [g for selected in rng.choices(groups, k=len(groups)) for g in by_group[selected]]
        values.append(sum(draw) / len(draw))
    values.sort()
    return {"available": True, "groups": len(groups), "resamples": iterations,
            "delta_accuracy_percentile_95": [values[int(iterations * .025)], values[int(iterations * .975)]],
            "caution": "Descriptive group bootstrap; small strata and exploratory selection limit inference."}


def evaluate(phase, root=ROOT):
    manifest, f = verify(phase, root)
    if phase != "scout" and "baseline" not in manifest["arms"]:
        raise ValueError("Confirmation requires a contemporaneous baseline")
    gold = {(d, r["id"]): r["label"] for d in ("basic", "challenge") for r in load_dev(d, root)}
    historical = {}
    if phase == "scout":
        historical_directory = root / "experiments/006_symbolic_z3"
        historical_freeze = json.loads((historical_directory / "freeze.json").read_text(encoding="utf-8"))
        if file_hash(historical_directory / "evaluation.json") != historical_freeze["evaluation_sha256"]:
            raise ValueError("Historical baseline source integrity mismatch")
        e = json.loads((historical_directory / "evaluation.json").read_text(encoding="utf-8"))
        historical = {(r["dataset"], r["id"]): r for r in e["rows"]}
    rows = defaultdict(lambda: defaultdict(list))
    coverage = defaultdict(int)
    costs = defaultdict(lambda: {"calls": 0, "tokens": 0, "input_tokens": 0, "output_tokens": 0, "latency_seconds": 0., "invalid": 0})
    flat = []
    pairs = list(itertools.combinations([a for a in manifest["arms"] if a != "baseline"], 2))
    for item in manifest["rows"]:
        key = item["dataset"], item["id"]
        labels = {}
        for arm in manifest["arms"]:
            p = root / OUTPUT / phase / "records" / item["dataset"] / item["id"] / (arm + ".json")
            if not p.exists():
                continue
            r = json.loads(p.read_text(encoding="utf-8"))
            if r["record_sha256"] != digest({k: v for k, v in r.items() if k != "record_sha256"}) or r["freeze_sha256"] != digest(f):
                raise ValueError("Raw response integrity mismatch")
            labels[arm] = parse(arm, r)["label"]
            coverage[arm] += 1
            c = costs[arm]
            c["calls"] += 1
            c["tokens"] += r["usage"]["total_tokens"]
            c["input_tokens"] += r["usage"]["prompt_tokens"]
            c["output_tokens"] += r["usage"]["completion_tokens"]
            c["latency_seconds"] += r["latency_seconds"]
            c["invalid"] += int(labels[arm] == "INVALID")
        if historical:
            if historical[key]["gold"] != gold[key]:
                raise ValueError("Historical baseline gold mismatch")
            labels["baseline"] = historical[key]["baseline_A27"]
        # Report methods on the full frozen manifest; missing answers count as invalid.
        for arm in ["baseline"] + [a for a in manifest["arms"] if a != "baseline"]:
            rows[item["dataset"]][arm].append(metric_row(item, labels.get(arm, "INVALID"), gold[key]))
        for a, b in pairs:
            name = f"consensus_{a}_{b}"
            label = conservative_consensus(labels.get("baseline", "INVALID"), [labels.get(a, "INVALID"), labels.get(b, "INVALID")])
            rows[item["dataset"]][name].append(metric_row(item, label, gold[key]))
        flat.append({"dataset": item["dataset"], "id": item["id"], "group": item["group"], "mechanism": item["mechanism"], "gold": gold[key], **labels})
    result = {"phase": phase, "purpose": manifest["purpose"], "n": len(manifest["rows"]),
              "baseline_provenance": "historical_v4_not_contemporaneous" if historical else "contemporaneous_same_batch",
              "complete": all(coverage[a] == len(manifest["rows"]) for a in manifest["arms"]),
              "response_counts": dict(coverage), "costs": dict(costs), "datasets": {}, "gates": {}}
    for dataset, arms in rows.items():
        result["datasets"][dataset] = {}
        baseline = arms["baseline"]
        for arm, data in arms.items():
            metrics = compute_metrics(data)
            mechanisms = {m: compute_metrics([r for r in data if r["mechanism"] == m]) for m in sorted({r["mechanism"] for r in data})}
            groups = {g: compute_metrics([r for r in data if r["group"] == g]) for g in sorted({r["group"] for r in data})}
            report = {"metrics": metrics, "mechanisms": mechanisms, "groups": groups}
            if arm != "baseline":
                report["paired"] = paired_comparison(baseline, data)
                report["group_bootstrap"] = cluster_interval(baseline, data)
                report["gate"] = gate(compute_metrics(baseline), metrics)
                report["all_mechanism_accuracy_nondecreasing"] = all(mechanisms[m]["accuracy"] >= compute_metrics([r for r in baseline if r["mechanism"] == m])["accuracy"] for m in mechanisms)
            result["datasets"][dataset][arm] = report
    candidates = [a for a in next(iter(rows.values())) if a != "baseline"]
    for arm in candidates:
        reports = [v[arm] for v in result["datasets"].values()]
        result["gates"][arm] = {
            "dataset_and_class_dominance": result["complete"] and all(r["gate"]["no_regression"] for r in reports) and any(r["gate"]["accuracy_improved"] for r in reports),
            "also_every_mechanism": result["complete"] and all(r["gate"]["no_regression"] and r["all_mechanism_accuracy_nondecreasing"] for r in reports) and any(r["gate"]["accuracy_improved"] for r in reports)}
    directory = root / EXPERIMENT / phase
    atomic_json(directory / "metrics.json", result)
    fields = ["dataset", "id", "group", "mechanism", "gold", "baseline"] + [a for a in manifest["arms"] if a != "baseline"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(flat)
    atomic_bytes(directory / "predictions.csv", stream.getvalue().encode("utf-8"))
    lines = [f"# V7 {phase}", "", f"Purpose: {result['purpose']}. Complete: {result['complete']}.",
             f"Baseline: {result['baseline_provenance']}. Missing/invalid predictions count as errors.", "",
             "| Dataset | Method | Correct/n | Accuracy | Macro F1 | S recall | R recall | NEI recall |", "|---|---|---|---|---|---|---|---|"]
    for dataset, arms in result["datasets"].items():
        for arm, r in arms.items():
            m = r["metrics"]
            recalls = [m["classes"][l]["recall"] for l in LABELS]
            lines.append(f"| {dataset} | {arm} | {m['correct']}/{m['n']} | {m['accuracy']:.2%} | {m['macro_f1']:.4f} | " + " | ".join("N/A" if x is None else f"{x:.2%}" for x in recalls) + " |")
    lines += ["", "## Gates", "", "```json", json.dumps(result["gates"], indent=2), "```", "", "Per-mechanism, per-group, paired changes, bootstrap intervals and costs are in metrics.json.",
              "Exploratory comparisons are not independent test evidence. Test data was not read."]
    atomic_bytes(directory / "RESULTS.md", ("\n".join(lines) + "\n").encode("utf-8"))
    print(json.dumps({"phase": phase, "complete": result["complete"], "response_counts": result["response_counts"],
        "scores": {d: {a: (r["metrics"]["correct"], r["metrics"]["n"]) for a,r in arms.items()} for d,arms in result["datasets"].items()},
        "gates": result["gates"]}, ensure_ascii=False))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", default="scout")
    evaluate(p.parse_args().phase)
