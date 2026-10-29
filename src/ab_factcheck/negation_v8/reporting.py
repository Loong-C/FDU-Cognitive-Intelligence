"""Offline reconstruction, paired metrics and explicit deployment cost."""
from collections import Counter, defaultdict
import csv
import io
import json

from ..common import LABELS, ROOT, atomic_bytes, atomic_json
from ..macro_v7.assess import paired_statistics
from ..macro_v7.experiment import load_dev
from ..macro_v7.inference import digest
from ..macro_v7.report import metric_row
from ..metrics import compute_metrics, paired_comparison
from .experiment import EXPERIMENT, OUTPUT, cache_record, inherited, verify
from .inference import FLIP, decide, label, needs_negative, synthetic_cases


def report(phase, root=ROOT):
    manifest, f = verify(phase, root)
    directory = root / OUTPUT / phase / "records"
    calls, tokens, invalids, fingerprints = Counter(), Counter(), Counter(), Counter()

    def read(node, item):
        p = directory / item["dataset"] / item["id"] / (node + ".json")
        if not p.exists():
            return None
        r = cache_record(p, node, item, root)
        if r["freeze_sha256"] != digest(f):
            raise ValueError("Response belongs to another freeze")
        prediction = label(node, r)
        calls[node] += 1
        tokens[node] += r["usage"]["total_tokens"]
        invalids[node] += int(prediction not in LABELS)
        fingerprints[r.get("system_fingerprint")] += 1
        return prediction

    if phase == "probe":
        checks = []
        for case in synthetic_cases():
            for node in ("positive", "negative"):
                item = dict(case, dataset="synthetic")
                expected = case["gold"] if node == "positive" else FLIP[case["gold"]]
                actual = read(node, item)
                checks.append({"id": case["id"], "node": node, "expected": expected, "actual": actual, "passed": expected == actual})
        result = {"phase": phase, "complete": all(r["actual"] is not None for r in checks), "passed": all(r["passed"] for r in checks),
                  "checks": checks, "calls": dict(calls), "tokens": dict(tokens), "synthetic_only": True}
        atomic_json(root / EXPERIMENT / phase / "metrics.json", result)
        print(json.dumps(result), flush=True)
        return result

    gold = {(d, r["id"]): r["label"] for d in ("basic", "challenge") for r in load_dev(d, root)}
    rows, flat, routes = defaultdict(lambda: defaultdict(list)), [], Counter()
    complete = True
    for item in manifest["rows"]:
        if phase in ("scout", "bridge"):
            baseline, positive, provenance = inherited(phase, item, root)
        else:
            baseline, positive, provenance = read("baseline", item), read("positive", item), {}
        negative = read("negative", item)
        decision_path = directory / item["dataset"] / item["id"] / "decision.json"
        prediction, route = "INVALID", "not_finished"
        if decision_path.exists():
            prediction, route = decide(baseline, positive, negative)
            expected = {"baseline": baseline, "positive": positive, "negative": negative, "prediction": prediction,
                        "route": route, "inherited": provenance, "freeze_sha256": digest(f)}
            if json.loads(decision_path.read_text(encoding="utf-8")) != expected:
                raise ValueError("Saved decision differs from independent reconstruction")
            if not needs_negative(baseline, positive) and negative is not None:
                raise ValueError("Unexpected extra negative completion")
        else:
            complete = False
        routes[route] += 1
        target = gold[item["dataset"], item["id"]]
        for arm, pred in (("baseline", baseline), ("nli", positive), ("signed_consensus", prediction)):
            rows[item["dataset"]][arm].append(metric_row(item, pred or "INVALID", target))
        flat.append({"dataset": item["dataset"], "id": item["id"], "group": item["group"], "mechanism": item["mechanism"],
            "gold": target, "baseline": baseline, "positive": positive, "negative": negative,
            "negative_as_original": FLIP.get(negative), "prediction": prediction, "route": route})
    result = {"phase": phase, "purpose": manifest["purpose"], "complete": complete, "n": len(manifest["rows"]),
        "routes": dict(routes), "new_calls": dict(calls), "new_tokens": dict(tokens), "invalids": dict(invalids),
        "fingerprints": dict(fingerprints), "datasets": {},
        "cost_note": "Scout/bridge new-call costs exclude reused baseline/positive. Deployment requires baseline + positive for every item, plus negative on disagreement.",
        "test_access": False}
    for dataset, arms in rows.items():
        result["datasets"][dataset] = {}
        for arm, data in arms.items():
            entry = {"metrics": compute_metrics(data),
                "mechanisms": {m: compute_metrics([r for r in data if r["mechanism"] == m]) for m in sorted({r["mechanism"] for r in data})},
                "groups": {g: compute_metrics([r for r in data if r["group"] == g]) for g in sorted({r["group"] for r in data})}}
            if arm != "baseline":
                entry["paired"] = paired_comparison(arms["baseline"], data)
            if arm == "signed_consensus" and complete:
                entry["statistics"] = paired_statistics(arms["baseline"], data)
                entry["versus_nli"] = paired_comparison(arms["nli"], data)
            result["datasets"][dataset][arm] = entry
    if complete:
        selected = [v["signed_consensus"] for v in result["datasets"].values()]
        base = [v["baseline"] for v in result["datasets"].values()]
        result["dataset_accuracy_and_f1_nondecreasing"] = all(c["metrics"][k] >= b["metrics"][k] - 1e-12 for c,b in zip(selected,base) for k in ("accuracy", "macro_f1"))
        result["strict_accuracy_gain_somewhere"] = any(c["metrics"]["accuracy"] > b["metrics"]["accuracy"] for c,b in zip(selected,base))
        result["detected_significant_regression"] = any(m["significant_regression"] for c in selected for m in c["statistics"]["metrics"].values())
        result["passes_development_rule"] = result["dataset_accuracy_and_f1_nondecreasing"] and result["strict_accuracy_gain_somewhere"] and not result["detected_significant_regression"]
        result["eligible_as_independent_confirmation"] = phase == "confirm"
    destination = root / EXPERIMENT / phase
    atomic_json(destination / "metrics.json", result)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(flat[0]))
    writer.writeheader()
    writer.writerows(flat)
    atomic_bytes(destination / "predictions.csv", stream.getvalue().encode("utf-8"))
    lines = [f"# V8 {phase}", "", manifest["purpose"], "", f"Complete: {complete}; new calls: {dict(calls)}; new tokens: {dict(tokens)}.", "",
             "| Dataset | Method | Correct/n | Accuracy | Macro F1 | S recall | R recall | NEI recall |", "|---|---|---|---|---|---|---|---|"]
    for dataset, arms in result["datasets"].items():
        for arm, entry in arms.items():
            m = entry["metrics"]
            recalls = [m["classes"][l]["recall"] for l in LABELS]
            lines.append(f"| {dataset} | {arm} | {m['correct']}/{m['n']} | {m['accuracy']:.2%} | {m['macro_f1']:.4f} | " + " | ".join("N/A" if v is None else f"{v:.2%}" for v in recalls) + " |")
    lines += ["", "No test data was accessed. Missing/invalid final predictions count as errors. No-significant-loss does not establish noninferiority.",
              "Full class/ mechanism/ group metrics, paired changes and group uncertainty are in metrics.json."]
    atomic_bytes(destination / "RESULTS.md", ("\n".join(lines) + "\n").encode("utf-8"))
    print(json.dumps({"phase": phase, "complete": complete, "scores": {d: {a:(v["metrics"]["correct"],v["metrics"]["n"]) for a,v in arms.items()} for d,arms in result["datasets"].items()},
        "routes": dict(routes), "new_calls": dict(calls), "new_tokens": dict(tokens), "passes": result.get("passes_development_rule")}), flush=True)
    return result
