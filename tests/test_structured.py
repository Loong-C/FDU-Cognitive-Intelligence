"""v2 fixtures test infrastructure only; they are never model predictions."""

import copy
import json

import httpx
import pytest

from ab_factcheck.common import ROOT, STRUCTURED_ARMS, load_config, read_jsonl
from ab_factcheck.metrics import compute_metrics, paired_comparison
from ab_factcheck.model_client import LocalModelClient
from ab_factcheck.parsing import parse_response
from ab_factcheck.pilot import load_pilot, prepare
from ab_factcheck.prompts import PromptSet
from ab_factcheck.runner import RunSession
from ab_factcheck.structured import parse_structured, response_format_for, schema_for


def config_v2():
    return load_config(ROOT / "configs/experiment_v2.json")


def world(true="POSSIBLE", false="POSSIBLE", **overrides):
    return {"true_world": true, "false_world": false,
            "true_reason": "A compatible situation.", "false_reason": "Another situation.", **overrides}


@pytest.mark.parametrize("true,false,label", [("POSSIBLE", "IMPOSSIBLE", "SUPPORTS"),
    ("IMPOSSIBLE", "POSSIBLE", "REFUTES"), ("POSSIBLE", "POSSIBLE", "NOT ENOUGH INFO")])
def test_worlds_map_without_verdict_or_reason_keywords(true, false, label):
    parsed = parse_structured(json.dumps(world(true, false, true_reason="REFUTES SUPPORTS arbitrary words")), "B2", "stop")
    assert parsed["predicted_label"] == parsed["derived_label"] == label
    assert parsed["parse_status"] == "ok" and parsed["logic_valid"]


def test_both_impossible_is_logic_invalid_but_schema_valid():
    r = parse_structured(json.dumps(world("IMPOSSIBLE", "IMPOSSIBLE")), "C2", "stop")
    assert r["json_valid"] and r["fields_valid"] and r["protocol_valid"]
    assert r["parse_error"] == r["derived_label"] == "INVALID_LOGIC"
    assert r["predicted_label"] is None and r["logic_valid"] is False


@pytest.mark.parametrize("text,finish,error", [
    ("", "stop", "empty_output"), ("{", "stop", "invalid_json"),
    ('```json\n{}\n```', "stop", "invalid_json"), ('{} trailing', "stop", "invalid_json"),
    ('{"verdict":"SUPPORTS","verdict":"REFUTES","reason":"r"}', "stop", "invalid_json"),
    ('{"verdict":"SUPPORTS","reason":NaN}', "stop", "invalid_json"),
    ('{"verdict":"SUPPORTS"}', "stop", "invalid_fields"),
    ('{"verdict":"supports","reason":"r"}', "stop", "invalid_fields"),
    ('{"verdict":"SUPPORTS","reason":4}', "stop", "invalid_fields"),
    ('{"verdict":"SUPPORTS","reason":"r","extra":0}', "stop", "invalid_fields"),
    ('{"verdict":"SUPPORTS","reason":"r"}', "length", "truncated"),
    ('{"verdict":"SUPPORTS","reason":"r"}', None, "unexpected_finish_reason"),
])
def test_invalid_json_fields_and_finish_reason(text, finish, error):
    r = parse_structured(text, "A2", finish)
    assert r["parse_status"] == "invalid" and r["parse_error"] == error


def test_empty_explanation_is_separate_from_classification():
    r = parse_structured(json.dumps(world(true_reason=" ")), "B2", "stop")
    assert r["parse_status"] == "ok" and r["predicted_label"] == "NOT ENOUGH INFO"
    assert r["reason_quality_flags"] == ["empty_true_reason"]
    assert parse_structured(json.dumps({**world(), "verdict": "SUPPORTS"}), "B2", "stop")["parse_error"] == "invalid_fields"
    missing = world(); del missing["false_reason"]
    assert parse_structured(json.dumps(missing), "C2", "stop")["parse_error"] == "invalid_fields"
    assert parse_structured(json.dumps(world(false="maybe")), "B2", "stop")["parse_error"] == "invalid_fields"


def test_legacy_parser_keeps_original_verdict():
    text = "CLAIM-TRUE WORLD: POSSIBLE\nReason: r\nCLAIM-FALSE WORLD: POSSIBLE\nReason: r\nVerdict: REFUTES"
    r = parse_response(text, "B1", "stop")
    assert r["predicted_label"] == "REFUTES" and r["consistency_status"] == "inconsistent"


def test_schemas_prompts_and_historical_order(monkeypatch):
    prompts = PromptSet(ROOT / "prompts/v2")
    assert prompts.arms == STRUCTURED_ARMS
    assert schema_for("B2") == schema_for("C2")
    assert "verdict" not in schema_for("B2")["properties"]
    for arm in STRUCTURED_ARMS:
        schema = schema_for(arm)
        assert set(schema["required"]) == set(schema["properties"]) and schema["additionalProperties"] is False
        msg = prompts.render(arm, claim="{evidence} literal", evidence="{claim} {} literal")
        assert "{evidence} literal" in msg[1]["content"] and "{claim} {} literal" in msg[1]["content"]
        with pytest.raises(TypeError):
            prompts.render(arm, claim="c", evidence="e", label="SUPPORTS")
    assert "TWO-WORLD" not in prompts.templates["A2"]["user"]
    monkeypatch.setattr("ab_factcheck.pilot.choose_pilot", lambda *_: pytest.fail("v2 must not resample"))
    prepare(config_v2())
    for dataset in ("challenge", "basic"):
        assert load_pilot(config_v2(), dataset) == load_pilot(load_config(), dataset)


def test_request_contains_real_schema_and_retry_preserves_it():
    payloads = []
    def handler(request):
        if request.url.path == "/apply-template": return httpx.Response(200, json={"prompt": "mock"})
        if request.url.path == "/tokenize": return httpx.Response(200, json={"tokens": [1, 2]})
        payloads.append(json.loads(request.content))
        if len(payloads) == 1: raise httpx.ConnectError("fixture", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(world())}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 2}})
    client = LocalModelClient(config_v2()["model"], transport=httpx.MockTransport(handler), sleeper=lambda _: None)
    client.model_id = "fixture"
    result = client.complete([{"role": "user", "content": "evidence claim only"}], response_format=response_format_for("B2"))
    assert payloads[0] == payloads[1] == result["request_payload"]
    assert result["completion_request_attempts"] == 2
    assert payloads[0]["response_format"]["type"] == "json_schema"
    assert payloads[0]["response_format"]["json_schema"]["schema"] == schema_for("B2")
    assert "schema" not in payloads[0]["response_format"]
    assert payloads[0]["max_tokens"] == 1024
    client.close()


def test_protocol_failure_is_saved_and_stops_without_regeneration(tmp_path):
    class Client:
        model_id = "fixture"
        calls = 0
        def complete(self, messages, *, response_format):
            self.calls += 1
            return {"raw_response": "not json", "finish_reason": "stop", "usage": {}, "latency_seconds": 0.1}
    rows = [{"id": str(i), "group": "g", "mechanism": "fixture", "label": "SUPPORTS", "claim": "c", "evidence": "e"} for i in range(3)]
    client = Client()
    session = RunSession(tmp_path, config_v2(), PromptSet(ROOT / "prompts/v2"), client, {"fixture": 1})
    with pytest.raises(RuntimeError, match="protocol failure"):
        session.run("synthetic", rows, ("A2",))
    assert client.calls == 1 and not (tmp_path / "run.lock").exists()
    assert sum(r["status"] == "completed" for r in read_jsonl(tmp_path / "synthetic.jsonl")) == 1
    with pytest.raises(RuntimeError, match="Prior protocol failure"):
        session.run("synthetic", rows, ("A2",))
    assert client.calls == 1


def test_structured_metric_denominators_and_targeted_pairs():
    def row(i, gold, value):
        return {"id": i, "group": i, "gold_label": gold, "status": "completed", "finish_reason": "stop", **parse_structured(json.dumps(value), "B2", "stop")}
    before = [row("1", "NOT ENOUGH INFO", world("IMPOSSIBLE", "POSSIBLE")),
              row("2", "SUPPORTS", world("POSSIBLE", "IMPOSSIBLE")),
              row("3", "REFUTES", world("IMPOSSIBLE", "IMPOSSIBLE"))]
    m = compute_metrics(before)
    assert m["accuracy"] == 1 / 3 and m["fields_valid_rate"] == 1 and m["logic_valid_rate"] == 2 / 3
    after = copy.deepcopy(before)
    for r in after[:2]: r.update(parse_structured(json.dumps(world()), "B2", "stop"))
    p = paired_comparison(before, after)
    assert p["nei_refutes_corrected_ids"] == ["1"] and p["supports_correct_to_nei_ids"] == ["2"]
    assert p["improved"] == p["harmed"] == 1 and p["accuracy_delta"] == 0


def test_constraint_probe_rejects_json_only_and_freezes_failure(tmp_path):
    from ab_factcheck.gates import constraint_probe
    class Client:
        calls = 0
        def complete(self, messages, *, response_format=None):
            self.calls += 1
            return {"raw_response": "NOT_JSON" if response_format is None else '{"error":"wrong fields"}',
                    "finish_reason": "stop", "effective_request_parameters": {}}
    class Session:
        directory = tmp_path
        fingerprint_hash = "fixture"
        client = Client()
    session = Session()
    with pytest.raises(RuntimeError, match="probe failed"):
        constraint_probe(session)
    assert session.client.calls == 5
    with pytest.raises(ValueError, match="probe failed"):
        constraint_probe(session)
    assert session.client.calls == 5


def test_reason_length_bound_is_enforced_and_quality_is_separate():
    r = parse_structured(json.dumps(world(true_reason="x" * 320)), "B2", "stop")
    assert r["parse_status"] == "ok" and r["predicted_label"] == "NOT ENOUGH INFO"
    assert r["reason_quality_flags"] == ["at_length_limit_true_reason"]
    assert parse_structured(json.dumps(world(true_reason="x" * 321)), "C2", "stop")["parse_error"] == "invalid_fields"


def test_smoke_gate_rejects_missing_run(tmp_path, monkeypatch):
    from ab_factcheck.gates import verify_smoke
    from ab_factcheck.cli import SMOKE_ROWS
    monkeypatch.setattr("ab_factcheck.gates.ROOT", tmp_path)
    with pytest.raises(FileNotFoundError):
        verify_smoke(config_v2(), {"configuration": config_v2()}, SMOKE_ROWS)


def test_v2_report_reuses_shared_metrics_and_includes_invalid_logic(tmp_path, monkeypatch):
    from ab_factcheck.common import atomic_json, file_hash, write_jsonl
    from ab_factcheck.reporting import report
    config = config_v2()
    config["run_id"] = "fixture_not_model_predictions"
    source = [{"id": "one", "group": "g", "mechanism": "DENIAL", "label": "NOT ENOUGH INFO", "claim": "c", "evidence": "e"}]
    for module in ("ab_factcheck.reporting", "ab_factcheck.reporting_v2"):
        monkeypatch.setattr(module + ".ROOT", tmp_path)
        monkeypatch.setattr(module + ".load_pilot", lambda *_: source)
    directory = tmp_path / config["output_root"] / config["run_id"]
    atomic_json(directory / "fingerprint.json", {"configuration": config})
    fingerprint = file_hash(directory / "fingerprint.json")
    for dataset in ("challenge", "basic"):
        rows = []
        for arm in STRUCTURED_ARMS:
            value = {"verdict": "REFUTES", "reason": "r"} if arm == "A2" else world("IMPOSSIBLE", "IMPOSSIBLE") if arm == "C2" else world()
            rows.append({"id": "one", "group": "g", "mechanism": "DENIAL", "gold_label": "NOT ENOUGH INFO", "dataset": dataset,
                         "run_id": config["run_id"], "arm": arm, "run_fingerprint_sha256": fingerprint, "status": "completed",
                         "finish_reason": "stop", **parse_structured(json.dumps(value), arm, "stop")})
        write_jsonl(directory / f"{dataset}.jsonl", rows)
    result = report(config)
    m = result["datasets"]["challenge"]
    assert m["arms"]["B2"]["accuracy"] == 1 and m["arms"]["C2"]["invalid"] == 1
    assert m["arms"]["C2"]["protocol_valid_rate"] == 1
    assert m["paired"]["B2-A2"]["nei_refutes_corrected_ids"] == ["one"]
    destination = tmp_path / config["report_root"] / config["run_id"]
    assert "INVALID_LOGIC" in (destination / "predictions.csv").read_text(encoding="utf-8-sig")
    assert "字段有效" in (destination / "pilot_report.md").read_text(encoding="utf-8")
