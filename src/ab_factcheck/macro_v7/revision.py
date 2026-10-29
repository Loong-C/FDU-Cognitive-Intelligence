"""Adaptive disagreement review. Scout reuses answers, confirmation reruns them."""
import argparse
import json
from collections import Counter, defaultdict

import jsonschema

from ..common import ROOT, LABELS, atomic_json, file_hash, frozen_json, now
from ..groq_client import GroqStop, exclusive, load_local_key
from ..metrics import compute_metrics, paired_comparison
from ..structured import strict_json
from ..symbolic_z3.client import SymbolicClient
from .experiment import CONFIG, EXPERIMENT, OUTPUT, load_dev, receive, source_hashes, verify
from .inference import digest, messages, parse, schema
from .report import cluster_interval, gate, metric_row


def review_schema():
    fields = {"evidence_assessment": {"type": "string"}, "verdict": {"type": "string", "enum": list(LABELS)}}
    return {"type": "json_schema", "json_schema": {"name": "independent_review", "strict": True,
        "schema": {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}}}


def review_messages(*, evidence, claim, root=ROOT):
    # Blind review: transmit only the authorized original input, never prior answers.
    user = "CLAIM:\n" + claim + "\n\nEVIDENCE:\n" + evidence
    return [{"role": "system", "content": (root / "prompts/v7/review_system.txt").read_text(encoding="utf-8")}, {"role": "user", "content": user}]


def parse_review(record):
    if record.get("provider_validation_issues") or record.get("finish_reason") != "stop":
        return "INVALID"
    try:
        obj = strict_json(record["raw_response"])
        jsonschema.validate(obj, review_schema()["json_schema"]["schema"])
        return obj["verdict"]
    except (ValueError, KeyError, TypeError, jsonschema.ValidationError):
        return "INVALID"


def freeze(phase, root=ROOT):
    if phase not in ("review_scout", "review_confirm"):
        raise ValueError("Unknown revision stage")
    original, original_freeze = verify("scout", root)
    rows = original["rows"] if phase == "review_scout" else json.loads((root / EXPERIMENT / "planned_confirmation.json").read_text(encoding="utf-8"))["rows"]
    sources = source_hashes(root)
    sources.update({p: file_hash(root / p) for p in ("src/ab_factcheck/macro_v7/revision.py", "experiments/006_symbolic_z3/evaluation.json",
        "experiments/007_macro_inference/planned_confirmation.json", "experiments/007_macro_inference/scout/metrics.json")})
    manifest = {"phase": phase, "rows": rows, "method": "baseline_plus_nli_then_blind_reading_comprehension_only_on_disagreement",
        "invalid_policy": "Keep valid baseline if alternative/reviewer is invalid; report every fallback separately.",
        "selection": "Scout failure: no original candidate passed; NLI chosen as the lower-cost single alternative with fewer basic errors than dual.",
        "historical_baseline": phase == "review_scout", "test_access": False}
    directory = root / EXPERIMENT / phase
    frozen_json(directory / "manifest.json", manifest)
    frozen_json(directory / "freeze.json", {"manifest_sha256": file_hash(directory / "manifest.json"), "source_sha256": sources,
        "config": json.loads((root / CONFIG).read_text(encoding="utf-8")), "parent_scout_freeze": digest(original_freeze)})
    print(json.dumps({"frozen": phase, "n": len(rows), "method": manifest["method"]}), flush=True)


def get_records(phase, item, root=ROOT):
    key = item["dataset"], item["id"]
    if phase == "review_scout":
        old = json.loads((root / "experiments/006_symbolic_z3/evaluation.json").read_text(encoding="utf-8"))
        b = next(r for r in old["rows"] if (r["dataset"], r["id"]) == key)
        nli_path = root / OUTPUT / "scout/records" / key[0] / key[1] / "nli.json"
        n = json.loads(nli_path.read_text(encoding="utf-8"))
        if digest({k:v for k,v in n.items() if k != "record_sha256"}) != n["record_sha256"]:
            raise GroqStop("Original NLI cache integrity mismatch")
        parsed = parse("nli", n)
        return {"baseline": {"verdict": b["baseline_A27"], "justification": b["baseline_record"]["direct_reason"]},
                "nli": {"verdict": parsed["label"], "justification": parsed.get("object", {}).get("justification", "")}}
    result = {}
    for arm in ("baseline", "nli"):
        p = root / OUTPUT / phase / "records" / key[0] / key[1] / (arm + ".json")
        if p.exists():
            record = json.loads(p.read_text(encoding="utf-8"))
            if digest({k:v for k,v in record.items() if k != "record_sha256"}) != record["record_sha256"]:
                raise GroqStop("Cache integrity mismatch")
            parsed = parse(arm, record)
            obj = parsed.get("object", {})
            result[arm] = {"verdict": parsed["label"], "justification": obj.get("justification", obj.get("reason", ""))}
    return result


def resolve(base, alternative, reviewer=None):
    if alternative not in LABELS or base == alternative:
        return base, "agreement" if base == alternative else "invalid_alternative_fallback"
    if reviewer is None:
        return "INVALID", "pending_review"
    return (reviewer, "review") if reviewer in LABELS else (base, "invalid_review_fallback")


def run(phase, root=ROOT):
    manifest, f = verify(phase, root)
    load_local_key(root)
    client = SymbolicClient(f["config"]["model"], root / "outputs/groq/quota.json", f["config"]["quota_policy"], free_plan_confirmed=True)
    directory = root / OUTPUT / phase
    receipt = {"started": now(), "phase": phase}
    try:
        with exclusive(directory / "run.lock"):
            for index, item in enumerate(manifest["rows"]):
                dest = directory / "records" / item["dataset"] / item["id"]
                if phase != "review_scout":
                    for arm in ("baseline", "nli"):
                        r = receive(client, dest / (arm + ".json"), {"messages": messages(arm, claim=item["claim"], evidence=item["evidence"], root=root),
                            "response_format": schema(arm), "max_completion_tokens": 1024 if arm == "baseline" else 512}, digest(f))
                        if r["provider_validation_issues"]:
                            raise GroqStop("Provider protocol failure")
                candidates = get_records(phase, item, root)
                b, n = candidates["baseline"], candidates["nli"]
                reviewer = None
                if b["verdict"] != n["verdict"] and n["verdict"] in LABELS:
                    r = receive(client, dest / "review.json", {"messages": review_messages(evidence=item["evidence"], claim=item["claim"], root=root),
                        "response_format": review_schema(), "max_completion_tokens": 512}, digest(f))
                    if r["provider_validation_issues"]:
                        raise GroqStop("Reviewer provider protocol failure")
                    reviewer = parse_review(r)
                prediction, route = resolve(b["verdict"], n["verdict"], reviewer)
                frozen_json(dest / "decision.json", {"label": prediction, "route": route, "baseline": b["verdict"], "nli": n["verdict"], "reviewer": reviewer,
                    "freeze_sha256": digest(f)})
                print(json.dumps({"item": index+1, "n": len(manifest["rows"]), "route": route, "label": prediction}), flush=True)
            receipt["status"] = "complete"
    except (GroqStop, KeyboardInterrupt) as exc:
        receipt.update(status="stopped", reason=str(exc), error_type=type(exc).__name__)
        print(json.dumps(receipt), flush=True)
    finally:
        receipt.update(ended=now(), new_http_attempts=client.new_attempts)
        atomic_json(directory / "last_execution.json", receipt)
        client.close()


def report(phase, root=ROOT):
    manifest, f = verify(phase, root)
    gold = {(d,r["id"]): r["label"] for d in ("basic", "challenge") for r in load_dev(d, root)}
    results, routes, calls, tokens, complete = defaultdict(lambda: defaultdict(list)), Counter(), Counter(), Counter(), True
    for item in manifest["rows"]:
        dest = root / OUTPUT / phase / "records" / item["dataset"] / item["id"]
        candidates = get_records(phase, item, root)
        base = candidates.get("baseline", {}).get("verdict", "INVALID")
        alt = candidates.get("nli", {}).get("verdict", "INVALID")
        reviewer = None
        if (dest / "review.json").exists():
            r = json.loads((dest / "review.json").read_text(encoding="utf-8"))
            reviewer = parse_review(r)
        label, route = resolve(base, alt, reviewer)
        if not (dest / "decision.json").exists():
            complete = False
            label, route = "INVALID", "not_finished"
        else:
            saved = json.loads((dest / "decision.json").read_text(encoding="utf-8"))
            if saved != {"label": label, "route": route, "baseline": base, "nli": alt, "reviewer": reviewer, "freeze_sha256": digest(f)}:
                raise ValueError("Decision cannot be independently reproduced")
        routes[route] += 1
        for arm, prediction in (("baseline", base), ("nli", alt), ("review", label)):
            results[item["dataset"]][arm].append(metric_row(item, prediction, gold[item["dataset"], item["id"]]))
        for arm in ("baseline", "nli", "review"):
            p = dest / (arm + ".json")
            if p.exists():
                r = json.loads(p.read_text(encoding="utf-8"))
                if r["record_sha256"] != digest({k:v for k,v in r.items() if k != "record_sha256"}) or r["freeze_sha256"] != digest(f):
                    raise ValueError("Response integrity failure")
                calls[arm] += 1
                tokens[arm] += r["usage"]["total_tokens"]
    out = {"phase": phase, "complete": complete, "routes": dict(routes), "new_calls": dict(calls), "new_tokens": dict(tokens),
           "baseline_provenance": "historical" if phase == "review_scout" else "contemporaneous", "datasets": {}}
    all_gates = []
    for dataset, arms in results.items():
        before = compute_metrics(arms["baseline"])
        out["datasets"][dataset] = {}
        for arm, rows in arms.items():
            m = compute_metrics(rows)
            entry = {"metrics": m, "mechanisms": {k: compute_metrics([r for r in rows if r["mechanism"] == k]) for k in sorted({r["mechanism"] for r in rows})},
                     "groups": {k: compute_metrics([r for r in rows if r["group"] == k]) for k in sorted({r["group"] for r in rows})}}
            if arm != "baseline":
                entry.update(gate=gate(before, m), paired=paired_comparison(arms["baseline"], rows), group_bootstrap=cluster_interval(arms["baseline"], rows))
                entry["mechanism_nonregression"] = all(v["accuracy"] >= compute_metrics([r for r in arms["baseline"] if r["mechanism"] == k])["accuracy"] for k,v in entry["mechanisms"].items())
            out["datasets"][dataset][arm] = entry
        all_gates.append(out["datasets"][dataset]["review"])
    out["passed_all_dimensions"] = complete and all(r["gate"]["no_regression"] and r["mechanism_nonregression"] for r in all_gates) and any(r["gate"]["accuracy_improved"] for r in all_gates)
    atomic_json(root / EXPERIMENT / phase / "metrics.json", out)
    print(json.dumps({"complete": complete, "scores": {d:{a:(v["metrics"]["correct"], v["metrics"]["n"]) for a,v in arms.items()} for d,arms in out["datasets"].items()},
                      "passed_all_dimensions": out["passed_all_dimensions"], "routes": dict(routes), "new_tokens": dict(tokens)}))
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("freeze", "run", "report"))
    p.add_argument("--phase", default="review_scout", choices=("review_scout", "review_confirm"))
    a = p.parse_args()
    {"freeze": freeze, "run": run, "report": report}[a.command](a.phase)
