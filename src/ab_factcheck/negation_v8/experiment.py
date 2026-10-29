"""Frozen, resumable negation experiments. Only explicit dev loaders are used."""
import argparse
from collections import Counter
import json

from ..common import ROOT, atomic_json, file_hash, frozen_json, now
from ..groq_client import GroqStop, exclusive, load_local_key
from ..macro_v7.experiment import choose_rows, receive, source_hashes, verify as verify_v7
from ..macro_v7.inference import digest
from ..symbolic_z3.client import SymbolicClient
from .inference import FLIP, decide, label, needs_negative, request, synthetic_cases

EXPERIMENT = "experiments/008_negation_consistency"
OUTPUT = "outputs/negation_v8"
CONFIG = "configs/experiment_negation_v8.json"


def prepare(root=ROOT):
    """Freeze prospective groups before any new probe or benchmark response."""
    rows = choose_rows("negation_v8_confirm", 20261028, 1, root)
    frozen_json(root / EXPERIMENT / "planned_confirmation.json", {
        "seed": 20261028, "rows": rows, "selection": "First SHA256-ranked complete unused group per dataset/mechanism",
        "excludes": ["v1 pilot", "v5 fresh", "all v7 experiment groups"], "selection_uses_predictions": False})
    print(json.dumps({"planned": len(rows), "datasets": dict(Counter(r["dataset"] for r in rows)),
                      "groups": len({(r['dataset'], r['group']) for r in rows})}), flush=True)


def freeze(phase, root=ROOT):
    if phase not in ("probe", "scout", "bridge", "confirm"):
        raise ValueError("Unknown phase")
    config = json.loads((root / CONFIG).read_text(encoding="utf-8"))
    parent = json.loads((root / config["parent_config"]).read_text(encoding="utf-8"))
    if phase == "probe":
        cases = synthetic_cases()
        rows = [{"id": r["id"], "dataset": "synthetic", "group": r["id"], "mechanism": "synthetic", "claim": r["claim"], "evidence": r["evidence"]} for r in cases]
    elif phase in ("scout", "bridge"):
        rows = verify_v7("scout" if phase == "scout" else "confirm", root)[0]["rows"]
    else:
        rows = json.loads((root / EXPERIMENT / "planned_confirmation.json").read_text(encoding="utf-8"))["rows"]
    paths = [CONFIG, "src/ab_factcheck/negation_v8/inference.py", "src/ab_factcheck/negation_v8/experiment.py",
        "src/ab_factcheck/negation_v8/reporting.py", "src/ab_factcheck/macro_v7/assess.py", "src/ab_factcheck/metrics.py",
        "experiments/006_symbolic_z3/evaluation.json", "experiments/008_negation_consistency/planned_confirmation.json"]
    sources = source_hashes(root) | {p: file_hash(root / p) for p in paths}
    manifest = {"phase": phase, "rows": rows, "method": config["policy"], "test_access": False,
        "purpose": {"probe": "Independent synthetic negation check", "scout": "Historical development exploration",
                    "bridge": "Previously evaluated development: NOT independent confirmation", "confirm": "New group-separated development confirmation"}[phase]}
    directory = root / EXPERIMENT / phase
    frozen_json(directory / "manifest.json", manifest)
    frozen_json(directory / "freeze.json", {"manifest_sha256": file_hash(directory / "manifest.json"),
        "source_sha256": sources, "config": config, "transport": parent, "frozen_at": now()} if not (directory / "freeze.json").exists()
        else json.loads((directory / "freeze.json").read_text(encoding="utf-8")))
    verify(phase, root)
    print(json.dumps({"frozen": phase, "n": len(rows)}), flush=True)


def verify(phase, root=ROOT):
    if phase not in ("probe", "scout", "bridge", "confirm"):
        raise ValueError("Unknown phase")
    d = root / EXPERIMENT / phase
    f = json.loads((d / "freeze.json").read_text(encoding="utf-8"))
    if file_hash(d / "manifest.json") != f["manifest_sha256"]:
        raise GroqStop("Manifest integrity mismatch")
    for p, expected in f["source_sha256"].items():
        if file_hash(root / p) != expected:
            raise GroqStop("Frozen source changed: " + p)
    return json.loads((d / "manifest.json").read_text(encoding="utf-8")), f


def cache_record(path, node, item, root=ROOT):
    r = json.loads(path.read_text(encoding="utf-8"))
    if r["record_sha256"] != digest({k: v for k,v in r.items() if k != "record_sha256"}):
        raise GroqStop("Inherited response integrity mismatch")
    expected = request(node, claim=item["claim"], evidence=item["evidence"], root=root)
    payload = r["request_payload"]
    if payload != {"model": "qwen/qwen3.8-27b", "temperature": 0, "seed": 42,
                   "reasoning_effort": "none", "stream": False, **expected}:
        raise GroqStop("Inherited request differs from frozen inference protocol")
    if r["provider_validation_issues"] or not r["nonthinking_validation"]["passed"]:
        raise GroqStop("Inherited provider verification failed")
    return r


def inherited(phase, item, root=ROOT):
    if phase not in ("scout", "bridge"):
        raise ValueError("Only development parent reuse is allowed")
    parent_phase = "scout" if phase == "scout" else "confirm"
    verify_v7(parent_phase, root)
    parent_dir = root / "outputs/macro_v7" / parent_phase / "records" / item["dataset"] / item["id"]
    p = parent_dir / "nli.json"
    positive = label("positive", cache_record(p, "positive", item, root))
    provenance = {"positive": {"path": p.relative_to(root).as_posix(), "sha256": file_hash(p)}}
    if phase == "scout":
        p = root / "experiments/006_symbolic_z3/evaluation.json"
        old = json.loads(p.read_text(encoding="utf-8"))
        r = next(r for r in old["rows"] if r["dataset"] == item["dataset"] and r["id"] == item["id"])
        baseline = r["baseline_A27"]
        provenance["baseline"] = {"path": p.relative_to(root).as_posix(), "sha256": file_hash(p), "historical": True}
    else:
        p = parent_dir / "baseline.json"
        baseline = label("baseline", cache_record(p, "baseline", item, root))
        provenance["baseline"] = {"path": p.relative_to(root).as_posix(), "sha256": file_hash(p)}
    return baseline, positive, provenance


def probe_gate(root=ROOT):
    verify("probe", root)
    for case in synthetic_cases():
        for node in ("positive", "negative"):
            p = root / OUTPUT / "probe/records/synthetic" / case["id"] / (node + ".json")
            if not p.exists():
                return False
            r = cache_record(p, node, case, root)
            expected = case["gold"] if node == "positive" else FLIP[case["gold"]]
            if label(node, r) != expected:
                return False
    return True


def run(phase, max_new=None, root=ROOT):
    manifest, f = verify(phase, root)
    if phase != "probe" and not probe_gate(root):
        raise GroqStop("Synthetic negation gate failed or incomplete; no development calls allowed")
    load_local_key(root)
    parent = f["transport"]
    client = SymbolicClient(parent["model"], root / "outputs/groq/quota.json", parent["quota_policy"], free_plan_confirmed=True)
    directory = root / OUTPUT / phase
    receipt = {"phase": phase, "started": now(), "new_responses": 0}

    def get(node, item):
        p = directory / "records" / item["dataset"] / item["id"] / (node + ".json")
        cached = p.exists()
        if not cached and max_new is not None and receipt["new_responses"] >= max_new:
            raise GroqStop("Requested execution call limit reached")
        r = receive(client, p, request(node, claim=item["claim"], evidence=item["evidence"], root=root), digest(f))
        receipt["new_responses"] += int(not cached)
        if r["provider_validation_issues"]:
            raise GroqStop("Provider protocol failure; raw response retained")
        return label(node, r)

    try:
        with exclusive(directory / "run.lock"):
            for index, item in enumerate(manifest["rows"]):
                if phase == "probe":
                    for node in ("positive", "negative"):
                        prediction = get(node, item)
                        print(json.dumps({"item": index+1, "n": len(manifest["rows"]), "node": node, "label": prediction}), flush=True)
                    continue
                if phase in ("scout", "bridge"):
                    baseline, positive, provenance = inherited(phase, item, root)
                else:
                    baseline, positive, provenance = get("baseline", item), get("positive", item), {}
                negative = get("negative", item) if needs_negative(baseline, positive) else None
                prediction, route = decide(baseline, positive, negative)
                frozen_json(directory / "records" / item["dataset"] / item["id"] / "decision.json",
                    {"baseline": baseline, "positive": positive, "negative": negative, "prediction": prediction,
                     "route": route, "inherited": provenance, "freeze_sha256": digest(f)})
                print(json.dumps({"item": index+1, "n": len(manifest["rows"]), "route": route, "label": prediction}), flush=True)
            receipt["status"] = "complete"
    except (GroqStop, KeyboardInterrupt) as exc:
        receipt.update(status="stopped", reason=str(exc), error_type=type(exc).__name__)
        print(json.dumps(receipt), flush=True)
    finally:
        receipt.update(ended=now(), new_http_attempts=client.new_attempts)
        atomic_json(directory / "last_execution.json", receipt)
        client.close()
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("prepare", "freeze", "run", "report"))
    p.add_argument("--phase", choices=("probe", "scout", "bridge", "confirm"), default="probe")
    p.add_argument("--max-new", type=int)
    a = p.parse_args()
    if a.command == "prepare": prepare()
    elif a.command == "freeze": freeze(a.phase)
    elif a.command == "report":
        from .reporting import report
        report(a.phase)
    else:
        receipt = run(a.phase, a.max_new)
        if receipt["status"] != "complete":
            raise SystemExit(2)


if __name__ == "__main__":
    main()
