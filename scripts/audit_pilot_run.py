"""Audit a completed local pilot without issuing model requests or using the holdout."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ab_factcheck.common import ARMS, DATASETS, LABELS, atomic_json, file_hash, json_bytes, load_config, now, read_jsonl, sha256
from ab_factcheck.pilot import load_pilot, prepare
from ab_factcheck.prompts import PromptSet
from ab_factcheck.runner import source_hashes


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    run = ROOT / config["output_root"] / config["run_id"]
    reports = ROOT / config["report_root"] / config["run_id"]
    fingerprint = json.loads((run / "fingerprint.json").read_text(encoding="utf-8"))
    metrics = json.loads((reports / "metrics.json").read_text(encoding="utf-8"))
    environment = json.loads((run / "environment.json").read_text(encoding="utf-8"))
    prompts = PromptSet(ROOT / config["prompts_dir"])
    pilot_stats = prepare(config)
    require(fingerprint["configuration"] == config, "Configuration changed")
    require(fingerprint["inference_source_sha256"] == source_hashes(), "Inference code changed")
    require(fingerprint["prompts"] == prompts.hashes, "Prompts changed")
    require(file_hash(run / "fingerprint.json") == metrics["fingerprint_sha256"], "Report fingerprint mismatch")
    require(file_hash(ROOT / config["model"]["file"]) == fingerprint["model_sha256"], "Model changed")
    all_rows, conditions = [], {}
    for dataset in DATASETS:
        source_rows = load_pilot(config, dataset)
        source = {r["id"]: r for r in source_rows}
        rows = read_jsonl(run / f"{dataset}.jsonl")
        require(file_hash(run / f"{dataset}.jsonl") == metrics["source_jsonl_sha256"][dataset], "JSONL changed after report")
        require(len(rows) == len(source) * 3, "Wrong record count")
        expected_keys = {(arm, sample_id) for arm in ARMS for sample_id in source}
        require({(r["arm"], r["id"]) for r in rows} == expected_keys, "Wrong or duplicate keys")
        for row in rows:
            original = source[row["id"]]
            path = run / "records" / dataset / row["arm"] / f"{sha256(row['id'].encode())}.json"
            require(json.loads(path.read_text(encoding="utf-8")) == row, "JSONL differs from atomic record")
            require(row["run_id"] == config["run_id"] and row["dataset"] == dataset, "Wrong run provenance")
            require(row["run_fingerprint_sha256"] == metrics["fingerprint_sha256"], "Wrong record fingerprint")
            require(row["gold_label"] == original["label"] and row["group"] == original["group"] and row["mechanism"] == original["mechanism"], "Wrong source metadata")
            messages = prompts.render(row["arm"], claim=original["claim"], evidence=original["evidence"])
            require(row["messages_sha256"] == sha256(json_bytes(messages)), "Rendered input mismatch")
            require(row["model_sha256"] == fingerprint["model_sha256"] and row["model_id"] == fingerprint["model_id"], "Wrong model")
            require(row["status"] in ("completed", "request_failed"), "Unfinished result")
            if row["status"] == "completed":
                effective = row["effective_request_parameters"]
                for key in ("temperature", "seed", "max_tokens", "stream"):
                    require(effective[key] == config["model"][key], f"Changed parameter: {key}")
                require(effective["cache_prompt"] is False, "Prompt cache enabled")
                usage = row["usage"]
                require(row["preflight_prompt_tokens"] == usage["prompt_tokens"], "Token preflight mismatch")
                require(usage["prompt_tokens"] + effective["max_tokens"] <= fingerprint["context_tokens"], "Context overflow")
                require(usage["completion_tokens"] <= effective["max_tokens"], "Output budget exceeded")
                require(usage["prompt_tokens_details"]["cached_tokens"] == 0, "Unexpected cached input")
                require(row["response_json"]["choices"][0]["message"]["content"] == row["raw_response"], "Raw response mismatch")
        for arm in ARMS:
            subset = [r for r in rows if r["arm"] == arm]
            require([r["id"] for r in subset] == [r["id"] for r in source_rows], "Arms used different order")
            matrix = {gold: dict.fromkeys((*LABELS, "INVALID"), 0) for gold in LABELS}
            for row in subset:
                pred = row["predicted_label"] if row["parse_status"] == "ok" else "INVALID"
                matrix[row["gold_label"]][pred] += 1
            reported = metrics["datasets"][dataset]["arms"][arm]
            require(matrix == reported["confusion_matrix"], "Confusion matrix mismatch")
            correct = sum(matrix[label][label] for label in LABELS)
            invalid = sum(matrix[label]["INVALID"] for label in LABELS)
            require(reported["correct"] == correct and reported["n"] == len(subset), "Wrong denominator")
            require(reported["accuracy"] == correct / len(subset) and reported["invalid"] == invalid, "Accuracy mismatch")
            conditions[f"{dataset}/{arm}"] = {
                "records": len(subset), "valid": len(subset) - invalid,
                "invalid_reasons": dict(Counter(r["parse_error"] for r in subset if r["parse_status"] != "ok")),
                "prompt_tokens": sum(r.get("usage", {}).get("prompt_tokens", 0) for r in subset),
                "completion_tokens": sum(r.get("usage", {}).get("completion_tokens", 0) for r in subset),
                "latency_seconds": sum(r["latency_seconds"] for r in subset),
            }
        for before, after in (("A0", "B1"), ("B1", "C1")):
            correctness = {arm: {r["id"]: r["parse_status"] == "ok" and r["predicted_label"] == r["gold_label"] for r in rows if r["arm"] == arm} for arm in (before, after)}
            pair = metrics["datasets"][dataset]["paired"][f"{after}-{before}"]
            improved = sorted(i for i in source if not correctness[before][i] and correctness[after][i])
            harmed = sorted(i for i in source if correctness[before][i] and not correctness[after][i])
            require(improved == pair["improved_ids"] and harmed == pair["harmed_ids"], "Paired result mismatch")
        all_rows.extend(rows)
    with (reports / "predictions.csv").open(encoding="utf-8-sig", newline="") as f:
        csv_rows = list(csv.DictReader(f))
    require(len(csv_rows) == len(all_rows), "Wrong CSV count")
    require(len(list((run / "records").glob("*/*/*.json"))) == len(all_rows), "Unexpected atomic record")
    require(not (run / "run.lock").exists(), "Run still active")
    require(not list((run / "records").rglob("*.tmp")), "Uncommitted temporary record")
    expected_order = [f"{dataset}/{arm}" for dataset in DATASETS for arm in ARMS]
    require(metrics["observed_arm_start_order"] == expected_order, "Wrong execution order")
    smoke = read_jsonl(ROOT / config["output_root"] / (config["run_id"] + "_smoke") / "synthetic.jsonl")
    require(len(smoke) == 9 and len({(r["arm"], r["id"]) for r in smoke}) == 9, "Smoke is incomplete")
    audit = {
        "audited_at": now(), "run_id": config["run_id"], "passed": True,
        "pilot": pilot_stats, "formal_records": len(all_rows), "smoke_records": len(smoke),
        "smoke_valid": sum(r["parse_status"] == "ok" for r in smoke),
        "request_failures": sum(r["status"] == "request_failed" for r in all_rows + smoke),
        "completion_attempts": dict(Counter(str(r.get("completion_request_attempts")) for r in all_rows + smoke)),
        "maximum_prompt_tokens": max(r.get("preflight_prompt_tokens", 0) for r in all_rows),
        "maximum_completion_tokens": max(r.get("usage", {}).get("completion_tokens", 0) for r in all_rows),
        "observed_arm_start_order": metrics["observed_arm_start_order"], "conditions": conditions,
        "checks": ["frozen raw data and splits", "complete dev-only groups", "frozen inference sources and prompts", "model SHA-256", "identical IDs and order", "atomic records equal JSONL", "rendered input hashes", "effective inference parameters", "context budget and tokenizer", "uncached requests", "complete CSV", "independent confusion matrices and paired changes"],
    }
    atomic_json(reports / "execution_audit.json", audit)
    atomic_json(reports / "environment_summary.json", {
        "captured_at": environment["captured_at"], "python": environment["python"],
        "platform": environment["platform"], "gpu": environment["gpu"],
        "dependencies": environment["dependencies"], "backend_identity": fingerprint["backend_identity"],
        "model_id": fingerprint["model_id"], "model_sha256": fingerprint["model_sha256"],
        "chat_template": environment["runtime"]["props"]["chat_template"],
        "chat_template_sha256": fingerprint["chat_template_sha256"], "context_tokens": fingerprint["context_tokens"],
        "environment_record_sha256": file_hash(run / "environment.json"),
        "seed_note": environment["seed_note"],
    })
    print(json.dumps({"passed": True, "formal_records": len(all_rows), "smoke_records": len(smoke), "report_directory": str(reports)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
