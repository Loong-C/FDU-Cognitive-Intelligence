"""Frozen historical-dev sampling and one-shot, resumable extraction."""
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

from ..common import ROOT, atomic_json, file_hash, frozen_json, now, read_jsonl, sha256
from ..groq_client import GroqStop, exclusive, load_local_key
from ..worlds_v5.client import Halt
from .logic import InvalidAST, compile_document, parse, solve
from .schema import response_format

EXPERIMENT = "experiments/006_symbolic_z3"
CONFIG = "configs/experiment_symbolic_z3_v6.json"
BASELINE = "experiments/004_groq_27b/reports/pilot_groq_qwen38_27b_nonthink_v4_r2"
SEED = 20261028


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def selection(root=ROOT):
    rows, evaluation, sources = [], [], {}
    baseline_path = root / BASELINE / "predictions.csv"
    with baseline_path.open(encoding="utf-8-sig", newline="") as source:
        baseline = {(r["dataset"], r["id"]): r for r in csv.DictReader(source) if r["arm"] == "A2"}
    sources[str(baseline_path.relative_to(root)).replace("\\", "/")] = file_hash(baseline_path)
    for dataset in ("challenge", "basic"):
        pilot_path = root / f"experiments/001_two_world_pilot/pilot/{dataset}_manifest.json"
        dev_path = root / f"data/splits/v1/{dataset}/dev.jsonl"
        pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
        if file_hash(dev_path) != pilot["dev_sha256"]:
            raise GroqStop("Historical dev hash mismatch")
        for path in (pilot_path, dev_path):
            sources[path.relative_to(root).as_posix()] = file_hash(path)
        ids = {r["id"] for r in pilot["assignments"] if r["is_pilot"]}
        strata = defaultdict(list)
        for row in read_jsonl(dev_path):
            if row["id"] in ids:
                strata[row["mechanism"]].append(row)
        if len(strata) != 7:
            raise GroqStop("Expected seven pilot mechanisms per dataset")
        for mechanism, candidates in sorted(strata.items()):
            if len(candidates) < 3:
                raise GroqStop("Insufficient stratum")
            chosen = sorted(candidates, key=lambda r: (digest([SEED, dataset, mechanism, r["id"]]), r["id"]))[:3]
            for r in chosen:
                item = {k: r[k] for k in ("id", "group", "mechanism", "evidence", "claim")}
                item.update(dataset=dataset, input_sha256=digest({"evidence": r["evidence"], "claim": r["claim"]}))
                rows.append(item)
                old = baseline[(dataset, r["id"])]
                if old["gold_label"] != r["label"] or old["group"] != r["group"]:
                    raise GroqStop("Historical baseline alignment mismatch")
                evaluation.append({"id": r["id"], "dataset": dataset, "gold": r["label"],
                                   "baseline_A27": old["predicted_label"], "baseline_record": old})
    return ({"seed": SEED, "algorithm": "first_3_sha256_canonical_json_seed_dataset_mechanism_id",
             "purpose": "historical development feasibility, NOT independent validation",
             "source_sha256": sources, "rows": rows, "ordered_ids_sha256": digest([r["id"] for r in rows])},
            {"source": BASELINE, "rows": evaluation})


def freeze(root=ROOT):
    directory = root / EXPERIMENT
    manifest, evaluation = selection(root)
    frozen_json(directory / "selection.json", manifest)
    frozen_json(directory / "evaluation.json", evaluation)
    files = [root / CONFIG, *sorted((root / "prompts/v6").glob("*.txt")), root / "prompts/v6/schema.json",
             *[root / "src/ab_factcheck/symbolic_z3" / f for f in ("schema.py", "logic.py", "client.py", "experiment.py")],
             *[root / "src/ab_factcheck" / f for f in ("groq_client.py", "worlds_v5/client.py", "worlds_v5_continuation.py")]]
    frozen_json(directory / "freeze.json", {"selection_sha256": file_hash(directory / "selection.json"),
        "evaluation_sha256": file_hash(directory / "evaluation.json"),
        "source_sha256": {p.relative_to(root).as_posix(): file_hash(p) for p in files}})
    return manifest


def verify_freeze(root=ROOT):
    directory = root / EXPERIMENT
    fingerprint = json.loads((directory / "freeze.json").read_text(encoding="utf-8"))
    for relative, expected in fingerprint["source_sha256"].items():
        if file_hash(root / relative) != expected:
            raise GroqStop("Frozen source changed: " + relative)
    for name in ("selection", "evaluation"):
        if file_hash(directory / (name + ".json")) != fingerprint[name + "_sha256"]:
            raise GroqStop("Frozen manifest changed")
    manifest, evaluation = selection(root)
    if manifest != json.loads((directory / "selection.json").read_text(encoding="utf-8")):
        raise GroqStop("Selection no longer matches historical sources")
    if evaluation != json.loads((directory / "evaluation.json").read_text(encoding="utf-8")):
        raise GroqStop("Baseline no longer matches historical sources")
    return manifest


def messages(evidence, claim, root=ROOT):
    prompts = root / "prompts/v6"
    return [{"role": "system", "content": (prompts / "system.txt").read_text(encoding="utf-8") + "\n" +
            (prompts / "dsl.txt").read_text(encoding="utf-8")},
            {"role": "user", "content": (prompts / "user.txt").read_text(encoding="utf-8").format(evidence=evidence, claim=claim)}]


def receive(path, item, client, config, root=ROOT):
    expected_messages = messages(item["evidence"], item["claim"], root)
    request = {"messages": expected_messages, "response_format": response_format(root),
               "max_completion_tokens": config["completion_limit"]}
    signature = digest(request)
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached["request_sha256"] != signature or cached["input_sha256"] != item["input_sha256"]:
            raise GroqStop("Cached request identity mismatch")
        if digest(cached["completion"]) != cached["completion_sha256"]:
            raise GroqStop("Cached completion integrity mismatch")
        return cached
    inflight = path.with_suffix(".inflight.json")
    failure = path.with_suffix(".failure.json")
    if inflight.exists():
        raise GroqStop("Unresolved inflight request; automatic resend forbidden")
    if failure.exists() and not json.loads(failure.read_text())["retryable"]:
        raise GroqStop("Terminal prior request failure; automatic resend forbidden")
    frozen_json(inflight, {"request_sha256": signature, "started_at": now()})
    try:
        completion = client.complete(**request)
    except Halt as exc:
        atomic_json(failure, {"reason": str(exc), "retryable": exc.retryable,
                             "ambiguous": exc.ambiguous, "attempts": client.last_attempts})
        if not exc.ambiguous:
            inflight.unlink()
        raise
    record = {"id": item["id"], "input_sha256": item["input_sha256"], "request_sha256": signature,
              "completion_sha256": digest(completion), "completion": completion}
    frozen_json(path, record)  # Retain even malformed/truncated/incorrect answers; NEVER regenerate.
    inflight.unlink()
    return record


def process(record, evidence_text):
    completion = record["completion"]
    if completion["provider_validation_issues"] or completion["finish_reason"] != "stop":
        return {"label": "UNSUPPORTED", "reason": "provider_protocol_or_truncation", "ast": None}
    try:
        document = parse(completion["raw_response"])
    except InvalidAST as exc:
        return {"label": "UNSUPPORTED", "reason": str(exc), "ast": None}
    return {**solve(document, evidence_text), "ast": document}


def execute(*, probe=False, limit=None, root=ROOT):
    from .client import SymbolicClient
    manifest = verify_freeze(root)
    directory = root / EXPERIMENT
    config = json.loads((root / CONFIG).read_text(encoding="utf-8"))
    if not probe:
        gate = json.loads((directory / "probe_result.json").read_text(encoding="utf-8"))
        if not gate["protocol_passed"]:
            raise GroqStop("Technical probe did not pass")
    load_local_key(root)
    client = SymbolicClient(config["model"], root / "outputs/groq/quota.json", config["quota_policy"], free_plan_confirmed=True)
    try:
        with exclusive(directory / "run.lock"):
            if probe:
                evidence = "Alex won a regional award in 2021."
                claim = "Sam won a regional award in 2021."
                item = {"id": "synthetic_independent_awards", "evidence": evidence, "claim": claim,
                        "input_sha256": digest({"evidence": evidence, "claim": claim})}
                record = receive(directory / "probe.json", item, client, config, root)
                result = process(record, evidence)
                # A well-formed UNSUPPORTED answer is a semantic failure here,
                # not a provider/schema failure. Exercise nonempty AST separately.
                compile_document(parse(record["completion"]["raw_response"]), evidence)
                technical_evidence = "Alex was born in 1990."
                technical_item = {"id": "synthetic_birth_year", "evidence": technical_evidence,
                    "claim": technical_evidence,
                    "input_sha256": digest({"evidence": technical_evidence, "claim": technical_evidence})}
                technical = receive(directory / "probe_birth.json", technical_item, client, config, root)
                technical_result = process(technical, technical_evidence)
                passed = (not record["completion"]["provider_validation_issues"] and
                    record["completion"]["finish_reason"] == "stop" and
                    technical_result.get("constraints") is not None and
                    technical_result["label"] != "UNSUPPORTED")
                atomic_json(directory / "probe_result.json", {"protocol_passed": passed,
                    "semantic_passed": result["label"] == "NOT ENOUGH INFO", "result": result,
                    "nonempty_ast_probe": technical_result})
                print(json.dumps({"probe_protocol_passed": passed, "label": result["label"], "reason": result.get("reason")}))
            else:
                count = 0
                for item in manifest["rows"]:
                    path = directory / "records" / (item["id"] + ".json")
                    is_new = not path.exists()
                    if is_new and limit is not None and count >= limit:
                        break
                    record = receive(path, item, client, config, root)
                    result = process(record, item["evidence"])
                    atomic_json(directory / "solved" / (item["id"] + ".json"), result)
                    count += int(is_new)
                    print(json.dumps({"id": item["id"], "cached": not is_new, "label": result["label"],
                                      "reason": result.get("reason")}), flush=True)
    finally:
        client.close()
