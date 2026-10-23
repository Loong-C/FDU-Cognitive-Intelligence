"""Real backend constraint probes and a fingerprint-bound smoke gate."""

import copy
import json

from .common import ROOT, experiment_arms, file_hash, frozen_json, json_bytes, read_jsonl, sha256
from .structured import matches_schema, parse_structured, response_format_for, strict_json


def constraint_probe(session):
    path = session.directory / "constraint_probe.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous["fingerprint_sha256"] != session.fingerprint_hash or not previous["passed"]:
            raise ValueError("Constraint probe failed or belongs to another setup")
        return previous
    messages = [{"role": "user", "content": "Reply with exactly NOT_JSON and nothing else. Do not output JSON."}]
    records = []
    control = session.client.complete(messages)
    control["request_payload"] = {"messages": messages, **control["effective_request_parameters"]}
    records.append({"condition": "unconstrained_control", "response": control})
    passed = control["raw_response"].strip() == "NOT_JSON" and control["finish_reason"] == "stop"
    # The schema-only sentinel is absent from the prompt. Two required fields,
    # exact enums and no extra keys exercise actual constrained decoding.
    for sentinel in ("SCHEMA_ONLY_ALPHA", "SCHEMA_ONLY_BETA"):
        schema = {"type": "object", "properties": {
            "gate": {"type": "string", "enum": [sentinel]},
            "required_field": {"type": "string", "enum": ["PRESENT"]}},
            "required": ["gate", "required_field"], "additionalProperties": False}
        response = session.client.complete(messages, response_format={"type": "json_schema", "json_schema": {
            "name": "constraint_probe", "strict": True, "schema": schema}})
        try:
            valid = matches_schema(strict_json(response["raw_response"]), schema) and response["finish_reason"] == "stop"
        except ValueError:
            valid = False
        passed = passed and valid
        records.append({"condition": sentinel, "valid": valid, "response": response})
    bounded_messages = [{"role": "user", "content": 'Return exactly this JSON object and nothing else: {"reason":"' + "x" * 100 + '"}'}]
    length_control = session.client.complete(bounded_messages)
    length_control["request_payload"] = {"messages": bounded_messages, **length_control["effective_request_parameters"]}
    length_schema = {"type": "object", "properties": {"reason": {"type": "string", "maxLength": 16}},
                     "required": ["reason"], "additionalProperties": False}
    length_result = session.client.complete(bounded_messages, response_format={"type": "json_schema", "json_schema": {
        "name": "length_probe", "strict": True, "schema": length_schema}})
    try:
        long_value = strict_json(length_control["raw_response"])
        short_value = strict_json(length_result["raw_response"])
        length_valid = (isinstance(long_value.get("reason"), str) and len(long_value["reason"]) > 16
                        and matches_schema(short_value, length_schema) and length_result["finish_reason"] == "stop")
    except (ValueError, AttributeError):
        length_valid = False
    passed = passed and length_valid
    records.extend([{"condition": "length_unconstrained", "response": length_control},
                    {"condition": "length_constrained", "valid": length_valid, "response": length_result}])
    if getattr(session, "config", {}).get("model_upgrade_v3"):
        from .preflight_v3 import validate_nonthinking_record
        for record in records:
            try:
                validate_nonthinking_record(record["response"], session.config)
            except ValueError:
                passed = False
    receipt = {"fingerprint_sha256": session.fingerprint_hash, "passed": passed, "records": records}
    frozen_json(path, receipt)
    if not passed:
        raise RuntimeError("Real schema probe failed; formal pilot is blocked")
    return receipt


def verify_smoke(config, fingerprint, smoke_rows):
    directory = ROOT / config["output_root"] / (config["run_id"] + "_smoke")
    expected = copy.deepcopy(fingerprint)
    expected["configuration"]["run_id"] += "_smoke"
    saved = json.loads((directory / "fingerprint.json").read_text(encoding="utf-8"))
    if expected != saved:
        raise ValueError("Smoke fingerprint differs from the formal run")
    probe = json.loads((directory / "constraint_probe.json").read_text(encoding="utf-8"))
    if not probe["passed"] or probe["fingerprint_sha256"] != file_hash(directory / "fingerprint.json"):
        raise ValueError("No matching successful constraint probe")
    rows = read_jsonl(directory / "synthetic.jsonl")
    wanted = {(arm, row["id"]) for arm in experiment_arms(config) for row in smoke_rows}
    if len(rows) != len(wanted) or {(r["arm"], r["id"]) for r in rows} != wanted:
        raise ValueError("Smoke must cover all three labels in every configured arm")
    for row in rows:
        if row["status"] != "completed" or row["run_fingerprint_sha256"] != probe["fingerprint_sha256"]:
            raise ValueError("Smoke request/provenance failure")
        parsed = parse_structured(row["raw_response"], row["arm"], row["finish_reason"])
        valid = parsed["protocol_valid"] if config.get("model_upgrade_v3") else parsed["parse_status"] == "ok"
        if not valid or any(row.get(k) != v for k, v in parsed.items()):
            raise ValueError("Smoke contains invalid or modified output")
        if row["request_payload"]["response_format"] != response_format_for(row["arm"]):
            raise ValueError("Smoke did not use the intended schema")
        for key in ("temperature", "seed", "max_tokens", "stream"):
            if row["request_payload"][key] != config["model"][key]:
                raise ValueError("Smoke used different inference parameters")
        if config.get("model_upgrade_v3"):
            from .preflight_v3 import validate_nonthinking_record
            validate_nonthinking_record(row, config)
        path = directory / "records" / "synthetic" / row["arm"] / f"{sha256(row['id'].encode())}.json"
        if json.loads(path.read_text(encoding="utf-8")) != row:
            raise ValueError("Smoke export differs from its atomic record")
    return {"smoke_records": len(rows), "constraint_probe_sha256": file_hash(directory / "constraint_probe.json"),
            "smoke_jsonl_sha256": file_hash(directory / "synthetic.jsonl"), "passed": True}
