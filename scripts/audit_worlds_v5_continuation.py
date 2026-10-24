"""Audit continuation lineage, unchanged parent artifacts and new-run metrics."""
import argparse
from collections import Counter
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
base = runpy.run_path(str(ROOT / "scripts/audit_worlds_v5.py"))
read, file_hash, digest = base["read"], base["file_hash"], base["digest"]
RUN = "layered_worlds_qwen38_27b_v5_r2_free"
LABELS = ("SUPPORTS", "REFUTES", "NOT ENOUGH INFO")


def audit():
    result = base["audit"](RUN)
    errors = result["errors"]
    snapshot = read(ROOT / "outputs/worlds_v5_history/before_free_continuation.json")
    for name, expected in snapshot["parent_files_sha256"].items():
        if not (ROOT / name).exists() or file_hash(ROOT / name) != expected:
            errors.append("r1_parent_changed:" + name)
    ledger = read(ROOT / "outputs/groq/quota.json")
    if ledger["attempts"][:snapshot["ledger_prefix_attempts"]] != snapshot["ledger_prefix"]:
        errors.append("precontinuation_ledger_changed")
    reuse = 0; new = 0; reused_tokens = 0; new_tokens = 0; requests = []
    for phase in ("smoke", "fresh"):
        directory = ROOT / "outputs/runs" / (RUN + "_" + phase)
        if not (directory / "fingerprint.json").exists(): continue
        fp = read(directory / "fingerprint.json")
        for name, expected in fp["continuation_source_sha256"].items():
            if file_hash(ROOT / name) != expected: errors.append("continuation_source_changed:" + name)
        parent = ROOT / "outputs/runs" / (fp["config"]["continuation_policy"]["parent_run_id"] + "_" + phase)
        if file_hash(parent / "fingerprint.json") != fp["parent_fingerprint_sha256"]:
            errors.append("parent_fingerprint_changed")
        for p in directory.rglob("*.json"):
            r = read(p)
            if not isinstance(r, dict) or "request_payload" not in r: continue
            if r.get("reused_from"):
                reuse += 1; reused_tokens += r["usage"]["total_tokens"]
                origin = r["reused_from"]
                source = ROOT / origin["path"]
                if file_hash(source) != origin["file_sha256"]: errors.append("lineage_source_hash:" + str(p))
                old = read(source)
                ignored = {"run_fingerprint_sha256", "upstream_sha256", "record_sha256", "reused_from"}
                if {k: v for k, v in r.items() if k not in ignored} != {k: v for k, v in old.items() if k not in ignored}:
                    errors.append("reused_response_changed:" + str(p))
                if origin["parent_record_sha256"] != old["record_sha256"] or origin["new_http_requests"] != 0:
                    errors.append("lineage_metadata:" + str(p))
            else:
                new += 1; new_tokens += r["usage"]["total_tokens"]
                requests.extend(a["request_sha256"] for a in r["attempts"] if a["status"] == "received")
        report_path = ROOT / "experiments/005_layered_worlds/reports" / (RUN + "_" + phase) / "metrics.json"
        if report_path.exists():
            report = read(report_path)
            sources = ({d: v["rows"] for d, v in read(ROOT / fp["config"]["manifest"])["datasets"].items()}
                       if phase == "fresh" else {"synthetic": [json.loads(s) for s in (ROOT / "experiments/005_layered_worlds/synthetic_smoke_cases.jsonl").read_text(encoding="utf-8").splitlines()]})
            for dataset, rows in sources.items():
                for arm in ("A27", "V5"):
                    matrix = {g: {v: 0 for v in (*LABELS, "INVALID")} for g in LABELS}
                    for row in rows:
                        path = directory / "records" / digest([dataset, row["id"]])
                        if arm == "V5":
                            path /= "verdict.json"
                            value = read(path)["label"] if path.exists() else None
                        else:
                            path /= "baseline_A27.json"
                            value = None
                            if path.exists():
                                r = read(path)
                                if r["validation"]["protocol_valid"] and not r["provider_validation_issues"]:
                                    value = json.loads(r["raw_response"])["verdict"]
                        matrix[row.get("label", row.get("gold"))][value if value in LABELS else "INVALID"] += 1
                    reported = report["datasets"][dataset][arm]
                    if matrix != reported["confusion_matrix"]: errors.append(f"confusion_matrix:{phase}:{dataset}:{arm}")
                    correct = sum(matrix[g][g] for g in LABELS)
                    if reported["scheduled"] != len(rows) or reported["accuracy_all_scheduled"] != correct/len(rows):
                        errors.append(f"all_scheduled_denominator:{phase}:{dataset}:{arm}")
                    f1s=[]
                    for label in LABELS:
                        n=sum(matrix[label].values()); predicted=sum(matrix[g][label] for g in LABELS); tp=matrix[label][label]
                        if reported["classes"][label]["recall"] != (tp/n if n else None): errors.append("recall")
                        f1s.append(2*tp/(n+predicted) if n+predicted else 0)
                    if reported["macro_f1"] != sum(f1s)/3: errors.append("macro_f1")
    if len(requests) != len(set(requests)): errors.append("duplicate_successful_request_payload")
    attempts = ledger["attempts"][snapshot["ledger_prefix_attempts"]:]
    received = [a for a in attempts if a["status"] == "received"]
    if new != len(received) or new_tokens != sum(a["usage"]["total_tokens"] for a in received): errors.append("new_cost_ledger_mismatch")
    summary_path = ROOT / "experiments/005_layered_worlds/continuation_summary.json"
    if summary_path.exists():
        summary = read(summary_path)
        manifest = read(ROOT / "experiments/005_layered_worlds/fresh_dev_v5.json")
        rows = []
        for dataset, data in manifest["datasets"].items():
            for row in data["rows"]:
                directory = ROOT / "outputs/runs" / (RUN + "_fresh") / "records" / digest([dataset, row["id"]])
                a = read(directory / "baseline_A27.json")["validation"]["parsed"]["verdict"] if (directory / "baseline_A27.json").exists() else None
                v = read(directory / "verdict.json")["label"] if (directory / "verdict.json").exists() else None
                rows.append({"dataset": dataset, "id": row["id"], "gold": row["label"], "A27": a, "V5": v})
        complete = [r for r in rows if r["A27"] is not None and r["V5"] is not None]
        for name, selected in (("all_scheduled", rows), ("complete_pairs", complete)):
            for arm in ("A27", "V5"):
                expected = summary["metrics"][name]["combined"][arm]
                correct = sum(r[arm] == r["gold"] for r in selected)
                valid = sum(r[arm] in LABELS for r in selected)
                if (expected["correct"], expected["valid"], expected["scheduled"]) != (correct, valid, len(selected)):
                    errors.append("extended_summary_counts:" + name + ":" + arm)
        if summary["new_successful_tokens"] != new_tokens or summary["new_attempts"] != len(attempts):
            errors.append("extended_summary_cost")
        reviewed = set()
        directory = ROOT / "experiments/005_layered_worlds"
        for note in read(directory / "continuation_review_notes.json")["notes"]:
            reviewed.add((note["dataset"], note["id"]))
            path = ROOT / "outputs/runs" / (RUN + "_fresh") / "records" / digest([note["dataset"], note["id"]])
            for name, expected in note["raw_sha256"].items():
                if file_hash(path / name) != expected: errors.append("semantic_note_source_changed")
        for group in read(directory / "continuation_group_reviews.json")["groups"]:
            for sample_id in group["reviewed_ids"]:
                reviewed.add((group["dataset"], sample_id))
                path = ROOT / "outputs/runs" / (RUN + "_fresh") / "records" / digest([group["dataset"], sample_id])
                for name, expected in group["source_sha256"][sample_id].items():
                    if file_hash(path / name) != expected: errors.append("semantic_group_source_changed")
        result["semantic_review_evidence"] = {
            "reviewer": "assistant, not external human", "complete_pairs": len(complete),
            "reviewed_complete_items": sum((r["dataset"], r["id"]) in reviewed for r in complete),
            "unreviewed_complete_ids": [r["id"] for r in complete if (r["dataset"], r["id"]) not in reviewed],
            "automatic_hash_checks_do_not_validate_semantic_judgments": True}
    result.update(passed=not errors, preserved_r1_files=len(snapshot["parent_files_sha256"]),
        preserved_precontinuation_ledger_entries=snapshot["ledger_prefix_attempts"],
        reused_responses=reuse, reused_tokens_not_charged_again=reused_tokens,
        new_responses=new, new_successful_tokens=new_tokens, new_http_attempts=len(attempts),
        new_attempt_statuses=dict(Counter(a["status"] for a in attempts)))
    return result


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path)
    args=p.parse_args()
    result=audit()
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_bytes(base["canonical"](result))
    print(json.dumps({k:v for k,v in result.items() if k!="checked_records"},ensure_ascii=False,indent=2))
    raise SystemExit(0 if result["passed"] else 1)
