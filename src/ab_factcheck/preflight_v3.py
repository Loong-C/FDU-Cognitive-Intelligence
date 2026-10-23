"""Measured, fingerprint-bound technical gates; classification mistakes are data."""

import copy
import json

from .common import ROOT, atomic_json, experiment_arms, file_hash, frozen_json, json_bytes, now, sha256
from .model_client import nonthinking_check
from .pilot import load_pilot
from .structured import response_format_for


def validate_nonthinking_record(row, config):
    request = row["request_payload"]
    for key in ("chat_template_kwargs", "reasoning_format"):
        if request.get(key) != config["model"][key] or row["applied_template"]["options"].get(key) != config["model"][key]:
            raise ValueError("Token preflight and generation template options differ")
    if not nonthinking_check(row["response_json"])["passed"] or not row["nonthinking_validation"]["passed"]:
        raise ValueError("Unexpected reasoning in raw response")
    if not row["prompt_count_matches"]:
        raise ValueError("Actual prompt tokens differ from token preflight")


def context_preflight(config, prompts, client):
    records = []
    for dataset in ("challenge", "basic"):
        for arm in experiment_arms(config):
            for row in load_pilot(config, dataset):
                messages = prompts.render(arm, claim=row["claim"], evidence=row["evidence"])
                count = client.count_prompt(messages)
                records.append(dict(dataset=dataset, arm=arm, id=row["id"], prompt_tokens=count,
                                    messages_sha256=sha256(json_bytes(messages)), applied_template=client.last_template_summary,
                                    fits=count + config["model"]["max_tokens"] <= config["model"]["context_tokens"]))
    result = {"configuration_sha256": sha256(json_bytes(config)), "records": records,
              "max_prompt_tokens": max(r["prompt_tokens"] for r in records), "passed": all(r["fits"] for r in records)}
    directory = ROOT / config["output_root"] / config["run_id"]
    frozen_json(directory / "context_preflight.json", result)
    if not result["passed"]:
        raise ValueError("Some pilot inputs plus output budget exceed context; no truncation allowed")
    return result


def nonthinking_probe(session):
    path = session.directory / "nonthinking_probe.json"
    if path.exists():
        previous = json.loads(path.read_text())
        if previous["fingerprint_sha256"] != session.fingerprint_hash or not previous["passed"]:
            raise ValueError("Prior nonthinking probe failed or setup changed; inspect and use a new run")
        return previous
    messages = [{"role": "user", "content": "A fictional box has two stones. Return exactly the word READY."}]
    client = session.client
    disabled = client.apply_template(messages)
    enabled_response = client._request("POST", "/apply-template", {"messages": messages, "add_generation_prompt": True,
                    "chat_template_kwargs": {"enable_thinking": True}, "reasoning_format": client.config["reasoning_format"]})
    enabled = enabled_response.get("prompt", "")
    response = client.complete(messages)
    response["request_payload"] = {"messages": messages, **response["effective_request_parameters"]}
    # Qwen3's disabled prefix closes an empty thought before generation. Compare
    # both real rendered templates to catch a silently ignored request kwarg.
    template_valid = disabled != enabled and "<think>\n\n</think>" in disabled[-160:] and enabled.rstrip().endswith("<think>")
    valid = template_valid and response["nonthinking_validation"]["passed"] and response["prompt_count_matches"] and response["finish_reason"] == "stop"
    result = {"fingerprint_sha256": session.fingerprint_hash, "passed": valid, "template_valid": template_valid,
              "disabled_template": {"text": disabled, "sha256": sha256(disabled.encode())},
              "enabled_template": {"text": enabled, "sha256": sha256(enabled.encode())}, "response": response}
    frozen_json(path, result)
    if not valid:
        raise RuntimeError("Real nonthinking probe failed; preserved evidence, formal run blocked")
    return result


def performance_probe(config, prompts, client, fingerprint):
    from .runner import RunSession
    probe_config = copy.deepcopy(config)
    probe_config["run_id"] += "_performance"
    probe_fingerprint = copy.deepcopy(fingerprint)
    probe_fingerprint["configuration"] = probe_config
    session = RunSession(ROOT / config["output_root"] / probe_config["run_id"], probe_config, prompts, client, probe_fingerprint)
    records = []
    for dataset in ("challenge", "basic"):
        # Fixed before inspecting model answers; separate from formal generations.
        records += session.run(dataset, load_pilot(config, dataset)[:2], split="performance_only")
    for row in records:
        if row["status"] != "completed" or not row.get("protocol_valid"):
            raise ValueError("Performance probe technical failure; no answer-based retries")
        validate_nonthinking_record(row, config)
    receipt = {"fingerprint_sha256": sha256(json_bytes(fingerprint)), "passed": True, "records": len(records),
               "source_sha256": {d: file_hash(session.directory / f"{d}.jsonl") for d in ("challenge", "basic")},
               "latencies_seconds": [r["latency_seconds"] for r in records],
               "completion_tokens": sum(r["usage"]["completion_tokens"] for r in records),
               "elapsed_request_seconds": sum(r["latency_seconds"] for r in records)}
    frozen_json(session.directory / "receipt.json", receipt)
    return receipt


def formal_gate(config, fingerprint):
    tuning_path = ROOT / config["deployment"]["tuning_receipt"]
    if file_hash(tuning_path) != config["deployment"]["tuning_receipt_sha256"]:
        raise ValueError("Offload tuning evidence changed")
    tuning = json.loads(tuning_path.read_text())
    if tuning["selected_gpu_layers"] != config["deployment"]["gpu_layers"] or not any(r["passed"] and r["layers"] == config["deployment"]["gpu_layers"] for r in tuning["results"]):
        raise ValueError("No successful measured offload candidate for this configuration")
    base = ROOT / config["output_root"]
    smoke = base / (config["run_id"] + "_smoke")
    nonthinking = json.loads((smoke / "nonthinking_probe.json").read_text())
    if not nonthinking["passed"] or nonthinking["fingerprint_sha256"] != file_hash(smoke / "fingerprint.json"):
        raise ValueError("Missing matching nonthinking verification")
    performance_dir = base / (config["run_id"] + "_performance")
    perf = json.loads((performance_dir / "receipt.json").read_text())
    if not perf["passed"] or perf["fingerprint_sha256"] != sha256(json_bytes(fingerprint)):
        raise ValueError("Missing matching performance probe")
    for dataset, expected in perf["source_sha256"].items():
        if file_hash(performance_dir / f"{dataset}.jsonl") != expected:
            raise ValueError("Performance probe records changed")
    context = json.loads((base / config["run_id"] / "context_preflight.json").read_text())
    if not context["passed"] or len(context["records"]) != 294 or context["configuration_sha256"] != sha256(json_bytes(config)):
        raise ValueError("Missing full 294-prompt context preflight")
    return {"passed": True, "nonthinking_probe_sha256": file_hash(smoke / "nonthinking_probe.json"),
            "performance_receipt_sha256": file_hash(performance_dir / "receipt.json"),
            "context_preflight_sha256": file_hash(base / config["run_id"] / "context_preflight.json")}
