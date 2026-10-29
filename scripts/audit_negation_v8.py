"""Independent raw-response and CSV audit for the completed V8 confirmation."""
import csv
from datetime import datetime
import json
from pathlib import Path
import re

from ab_factcheck.common import ROOT, atomic_json, file_hash, now
from ab_factcheck.negation_v8.experiment import EXPERIMENT, OUTPUT, verify
from ab_factcheck.negation_v8.inference import request
from ab_factcheck.macro_v7.inference import digest


def audit_manifest(manifest, freeze):
    """Join the frozen sample list directly to the two development files."""
    source = {}
    members = {}
    for dataset in ("basic", "challenge"):
        path = ROOT / f"data/splits/v1/{dataset}/dev.jsonl"
        assert file_hash(path) == freeze["source_sha256"][path.relative_to(ROOT).as_posix()]
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = (dataset, row["id"])
            assert key not in source
            source[key] = row
            members.setdefault((dataset, row["group"]), set()).add(row["id"])
    selected = {}
    seen = set()
    for item in manifest["rows"]:
        key = (item["dataset"], item["id"])
        assert key not in seen
        seen.add(key)
        original = source[key]
        assert set(item) == {"dataset", "id", "group", "mechanism", "claim", "evidence"}
        assert all(item[k] == original[k] for k in ("id", "group", "mechanism", "claim", "evidence"))
        selected.setdefault((item["dataset"], item["group"]), set()).add(item["id"])
    assert all(ids == members[group] for group, ids in selected.items())
    return source


def main():
    manifest, freeze = verify("confirm")
    source = audit_manifest(manifest, freeze)
    directory = ROOT / EXPERIMENT / "confirm"
    metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
    if not metrics["complete"]:
        raise ValueError("Final audit requires complete confirmation")
    labels = ("SUPPORTS", "REFUTES", "NOT ENOUGH INFO")
    map_nli = {"ENTAILMENT": "SUPPORTS", "CONTRADICTION": "REFUTES", "NEUTRAL": "NOT ENOUGH INFO"}
    inverse = {"SUPPORTS": "REFUTES", "REFUTES": "SUPPORTS", "NOT ENOUGH INFO": "NOT ENOUGH INFO"}
    with (directory / "predictions.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    lookup = {(r["dataset"], r["id"]): r for r in rows}
    assert len(lookup) == len(rows) == len(manifest["rows"])
    raw_count, attempts, total_tokens = 0, 0, 0
    fingerprints = set()
    raw_hashes = {}
    for item in manifest["rows"]:
        saved = lookup[item["dataset"], item["id"]]
        original = source[item["dataset"], item["id"]]
        assert saved["gold"] == original["label"]
        assert saved["group"] == original["group"] and saved["mechanism"] == original["mechanism"]
        preds = {}
        for node in ("baseline", "positive", "negative"):
            p = ROOT / OUTPUT / "confirm/records" / item["dataset"] / item["id"] / (node + ".json")
            if not p.exists():
                assert node == "negative"
                continue
            r = json.loads(p.read_text(encoding="utf-8"))
            assert digest({k:v for k,v in r.items() if k != "record_sha256"}) == r["record_sha256"]
            assert r["freeze_sha256"] == digest(freeze)
            expected = request(node, claim=item["claim"], evidence=item["evidence"])
            assert r["request_payload"] == {"model": "qwen/qwen3.8-27b", "temperature": 0, "seed": 42,
                "reasoning_effort": "none", "stream": False, **expected}
            assert r["actual_model_id"] == "qwen/qwen3.8-27b"
            assert datetime.fromisoformat(r["requested_at"]) >= datetime.fromisoformat(freeze["frozen_at"])
            assert r["nonthinking_validation"]["passed"] and not r["provider_validation_issues"]
            assert r["finish_reason"] == "stop"
            assert r["response_json"]["choices"][0]["message"]["content"] == r["raw_response"]
            if node != "baseline":
                hypothesis = item["claim"] if node == "positive" else (
                    "It is not the case that the following statement holds: "
                    + json.dumps(item["claim"], ensure_ascii=False))
                assert r["request_payload"]["messages"] == [
                    {"role": "system", "content": (ROOT / "prompts/v7/nli_system.txt").read_text(encoding="utf-8")},
                    {"role": "user", "content": "PREMISE:\n" + item["evidence"] + "\n\nHYPOTHESIS:\n" + hypothesis}]
            obj = json.loads(r["raw_response"])
            preds[node] = obj["verdict"] if node == "baseline" else map_nli[obj["relation"]]
            raw_count += 1
            attempts += len(r["attempts"])
            total_tokens += r["usage"]["total_tokens"]
            fingerprints.add(r.get("system_fingerprint"))
            raw_hashes[p.relative_to(ROOT).as_posix()] = file_hash(p)
        assert saved["baseline"] == preds["baseline"] and saved["positive"] == preds["positive"]
        if preds["baseline"] == preds["positive"]:
            assert "negative" not in preds
            expected_label = preds["baseline"]
        else:
            assert saved["negative"] == preds["negative"]
            assert saved["negative_as_original"] == inverse[preds["negative"]]
            expected_label = preds["positive"] if preds["positive"] == inverse[preds["negative"]] else preds["baseline"]
        assert saved["prediction"] == expected_label
    # Independently recompute accuracy, all class recalls, and macro F1 from CSV.
    for dataset in ("basic", "challenge"):
        subset = [r for r in rows if r["dataset"] == dataset]
        for arm, column in (("baseline", "baseline"), ("nli", "positive"), ("signed_consensus", "prediction")):
            saved = metrics["datasets"][dataset][arm]["metrics"]
            assert saved["n"] == len(subset)
            assert saved["correct"] == sum(r[column] == r["gold"] for r in subset)
            f1s = []
            for label in labels:
                tp = sum(r[column] == label and r["gold"] == label for r in subset)
                ng = sum(r["gold"] == label for r in subset)
                np = sum(r[column] == label for r in subset)
                assert saved["classes"][label]["support"] == ng
                assert abs(saved["classes"][label]["recall"] - tp/ng) < 1e-12
                f1s.append(2*tp/(ng+np))
            assert abs(saved["macro_f1"] - sum(f1s)/3) < 1e-12
    assert raw_count == sum(metrics["new_calls"].values())
    assert total_tokens == sum(metrics["new_tokens"].values())
    planned = json.loads((ROOT / EXPERIMENT / "planned_confirmation.json").read_text(encoding="utf-8"))
    assert planned["rows"] == manifest["rows"]
    newgroups = {(r["dataset"],r["group"]) for r in manifest["rows"]}
    excluded = set()
    for dataset in ("basic", "challenge"):
        p = ROOT / f"experiments/001_two_world_pilot/pilot/{dataset}_manifest.json"
        old = json.loads(p.read_text(encoding="utf-8"))
        excluded |= {(dataset,r["group"]) for r in old["assignments"] if r["is_pilot"]}
    old = json.loads((ROOT / "experiments/005_layered_worlds/fresh_dev_v5.json").read_text(encoding="utf-8"))
    for dataset, d in old["datasets"].items():
        excluded |= {(dataset,r["group"]) for r in d["rows"]}
    for p in (ROOT / "experiments/007_macro_inference").glob("*/manifest.json"):
        old = json.loads(p.read_text(encoding="utf-8"))
        excluded |= {(r["dataset"],r["group"]) for r in old["rows"]}
    assert not newgroups & excluded
    secrets = [s.split("=",1)[1].strip().strip("\"'") for s in (ROOT / ".env.local").read_text(encoding="utf-8-sig").splitlines() if s.startswith("GROQ_API_KEY=")]
    files = [ROOT / "configs/experiment_negation_v8.json", ROOT / "tests/test_negation_v8.py", Path(__file__)]
    for dirname in (EXPERIMENT, OUTPUT, "src/ab_factcheck/negation_v8"):
        files += [p for p in (ROOT / dirname).rglob("*") if p.is_file()]
    for p in files:
        content = p.read_bytes()
        assert not any(s and s.encode() in content for s in secrets)
        assert not re.search(rb"\bgsk_[A-Za-z0-9_-]{20,}", content)
    result = {"passed": True, "audited_at": now(), "n": len(rows), "groups": len(newgroups), "raw_responses": raw_count,
        "http_attempts_for_received_responses": attempts, "actual_tokens": total_tokens,
        "system_fingerprints": sorted(fingerprints), "exact_payloads_verified": True,
        "nonthinking_observable_checks_passed": True, "independent_polarity_and_decision_reconstruction": True,
        "independent_metric_recomputation": True, "historical_group_overlap": 0,
        "gold_and_metadata_joined_to_frozen_dev": True, "complete_group_membership_verified": True,
        "all_requests_after_protocol_freeze": True, "independent_nli_input_reconstruction": True,
        "metrics_sha256": file_hash(directory / "metrics.json"),
        "predictions_sha256": file_hash(directory / "predictions.csv"),
        "audit_script_sha256": file_hash(Path(__file__)),
        "secret_scan_files": len(files), "test_files_read": False, "raw_file_sha256": raw_hashes}
    atomic_json(directory / "audit.json", result)
    print(json.dumps({k:v for k,v in result.items() if k != "raw_file_sha256"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
