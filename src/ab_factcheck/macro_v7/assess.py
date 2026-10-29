"""Group-paired uncertainty under the user's relaxed acceptance criterion."""
import argparse
import csv
from itertools import product
import json
import random

from ..common import ROOT, LABELS, atomic_json, atomic_bytes, file_hash
from ..metrics import compute_metrics
from .experiment import EXPERIMENT


def vector(rows):
    m = compute_metrics(rows)
    return {"accuracy": m["accuracy"], "macro_f1": m["macro_f1"],
            **{"recall_" + label: m["classes"][label]["recall"] for label in LABELS}}


def difference(before, after):
    a, b = vector(before), vector(after)
    return {k: None if a[k] is None or b[k] is None else b[k] - a[k] for k in a}


def paired_statistics(before, after, *, resamples=5000, seed=20261028):
    left, right = {r["id"]: r for r in before}, {r["id"]: r for r in after}
    if left.keys() != right.keys() or len(left) != len(before) or len(right) != len(after):
        raise ValueError("Statistics require unique, exactly paired samples")
    if any(left[k]["gold_label"] != right[k]["gold_label"] or left[k]["group"] != right[k]["group"] for k in left):
        raise ValueError("Pair metadata mismatch")
    groups = sorted({r["group"] for r in before})
    ids = {g: [r["id"] for r in before if r["group"] == g] for g in groups}
    observed = difference(before, after)
    rng = random.Random(seed)
    draws = {k: [] for k in observed}
    for _ in range(resamples):
        sampled = [i for g in rng.choices(groups, k=len(groups)) for i in ids[g]]
        delta = difference([left[i] for i in sampled], [right[i] for i in sampled])
        for k, v in delta.items():
            if v is not None:
                draws[k].append(v)
    result = {}
    for k, values in draws.items():
        values.sort()
        interval = [values[int(.025 * len(values))], values[min(len(values)-1, int(.975*len(values)))]] if values else None
        result[k] = {"delta": observed[k], "group_bootstrap_95": interval,
                     "defined_bootstrap_draws": len(values), "undefined_bootstrap_draws": resamples - len(values)}
    exact = len(groups) <= 16
    permutations = product((False, True), repeat=len(groups)) if exact else ([rng.choice((False, True)) for _ in groups] for _ in range(50000))
    extremes, nperm = {k: 0 for k in observed}, 0
    for flips in permutations:
        a, b = [], []
        for group, flip in zip(groups, flips):
            for i in ids[group]:
                a.append(right[i] if flip else left[i])
                b.append(left[i] if flip else right[i])
        d = difference(a, b)
        nperm += 1
        for k in extremes:
            if observed[k] is not None and d[k] is not None and abs(d[k]) >= abs(observed[k]) - 1e-12:
                extremes[k] += 1
    for k, value in result.items():
        p = (extremes[k] / nperm if exact else (extremes[k]+1)/(nperm+1)) if observed[k] is not None else None
        value.update(group_paired_two_sided_p=p, significant_regression=p is not None and observed[k] < 0 and p < .05,
                     significant_improvement=p is not None and observed[k] > 0 and p < .05)
    return {"groups": len(groups), "n": len(before), "resamples": resamples, "permutations": nperm,
            "exact_permutation": exact, "metrics": result,
            "interpretation": "Failure to detect regression is not evidence of noninferiority; no margin was specified. Tests are unadjusted; mechanism estimates with one group are descriptive."}


def assess(phase="confirm", root=ROOT):
    directory = root / EXPERIMENT / phase
    metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
    if not metrics["complete"]:
        raise ValueError("Refuse acceptance decisions on partial confirmation")
    with (directory / "predictions.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    output = {"phase": phase, "acceptance_amendment_sha256": file_hash(root / EXPERIMENT / "acceptance_amendment.json"),
              "metrics_sha256": file_hash(directory / "metrics.json"), "datasets": {}}
    for dataset in ("basic", "challenge"):
        selected = [r for r in rows if r["dataset"] == dataset]
        arms = {a: [{"id": r["id"], "group": r["group"], "gold_label": r["gold"], "predicted_label": r[a],
                      "parse_status": "ok" if r[a] in LABELS else "invalid"} for r in selected] for a in ("baseline", "nli")}
        output["datasets"][dataset] = paired_statistics(arms["baseline"], arms["nli"])
    values = [m for d in output["datasets"].values() for m in d["metrics"].values()]
    output["no_detected_significant_regression"] = not any(m["significant_regression"] for m in values)
    output["accuracy_gain_somewhere"] = any(d["metrics"]["accuracy"]["delta"] > 0 for d in output["datasets"].values())
    output["promising_under_relaxed_development_rule"] = output["no_detected_significant_regression"] and output["accuracy_gain_somewhere"]
    output["noninferiority_established"] = False
    output["test_generalization_established"] = False
    atomic_json(directory / "statistical_assessment.json", output)
    print(json.dumps(output, ensure_ascii=False))
    return output


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", default="confirm")
    assess(p.parse_args().phase)
