"""Program tests use synthetic/mock responses, never reported as model accuracy."""

import copy
import json
from pathlib import Path

import httpx
import pytest

from ab_factcheck.common import ARMS, LABELS, ROOT, atomic_bytes, load_config, read_jsonl
from ab_factcheck.metrics import compute_metrics, paired_comparison
from ab_factcheck.model_client import LocalModelClient, RequestFailure, validate_endpoint
from ab_factcheck.parsing import parse_response, world_label
from ab_factcheck.pilot import choose_pilot, load_pilot
from ab_factcheck.prompts import EXAMPLE_CLAIM, PromptSet
from ab_factcheck.runner import RunSession


def world_output(true="POSSIBLE", false="POSSIBLE", verdict="NOT ENOUGH INFO"):
    return f"CLAIM-TRUE WORLD: {true}\nReason: A compatible scenario.\nCLAIM-FALSE WORLD: {false}\nReason: Another scenario.\nVerdict: {verdict}"


@pytest.mark.parametrize("text,label", [
    ("Mentions REFUTES and SUPPORTS first.\nVerdict: NOT ENOUGH INFO", "NOT ENOUGH INFO"),
    ("Example Verdict: REFUTES\nFinal explanation.\nVerdict: SUPPORTS\n\n", "SUPPORTS"),
    ("verdict : refutes  ", "REFUTES"),
    (" Verdict: not   enough info \n", "NOT ENOUGH INFO"),
])
def test_final_verdict(text, label):
    parsed = parse_response(text, "A0", "stop")
    assert parsed["parse_status"] == "ok"
    assert parsed["predicted_label"] == label


@pytest.mark.parametrize("text,finish", [
    ("Verdict: SUPPORTS\nExtra commentary", "stop"),
    ("I think SUPPORTS", "stop"),
    ("", "stop"),
    ("Verdict: UNKNOWN", "stop"),
    ("Verdict: SUPPORTS", "length"),
    ("Verdict: SUPPORTS", None),
])
def test_invalid_outputs_do_not_pass(text, finish):
    assert parse_response(text, "A0", finish)["parse_status"] == "invalid"


@pytest.mark.parametrize("true,false,label", [
    ("POSSIBLE", "IMPOSSIBLE", "SUPPORTS"),
    ("IMPOSSIBLE", "POSSIBLE", "REFUTES"),
    ("POSSIBLE", "POSSIBLE", "NOT ENOUGH INFO"),
])
def test_world_table(true, false, label):
    assert world_label(true, false) == label
    parsed = parse_response(world_output(true, false, label), "B1", "stop")
    assert parsed["parse_status"] == "ok"
    assert parsed["consistency_status"] == "consistent"
    assert parsed["world_reason_true"] == "A compatible scenario."


def test_inconsistency_never_rewrites_verdict():
    parsed = parse_response(world_output(verdict="REFUTES"), "C1", "stop")
    assert parsed["predicted_label"] == "REFUTES"
    assert parsed["derived_label"] == "NOT ENOUGH INFO"
    assert parsed["parse_status"] == "ok"
    assert parsed["consistency_status"] == "inconsistent"


def test_both_impossible_and_missing_world_are_invalid():
    parsed = parse_response(world_output("IMPOSSIBLE", "IMPOSSIBLE", "REFUTES"), "B1", "stop")
    assert parsed["derived_label"] is None
    assert parsed["consistency_status"] == "both_impossible"
    assert parsed["parse_status"] == "invalid"
    assert parse_response("Verdict: SUPPORTS", "B1", "stop")["parse_status"] == "invalid"


def test_echoed_example_does_not_override_final_world_block():
    text = world_output() + "\nNow the actual answer:\n" + world_output("IMPOSSIBLE", "POSSIBLE", "REFUTES")
    parsed = parse_response(text, "C1", "stop")
    assert parsed["predicted_label"] == parsed["derived_label"] == "REFUTES"


def test_frozen_prompts_single_pass_and_metadata_isolation():
    prompts = PromptSet(ROOT / "prompts/v1")
    for arm in ARMS:
        messages = prompts.render(arm, claim="literal {evidence} and {claim}", evidence="literal {claim} braces {}")
        assert "literal {evidence} and {claim}" in messages[1]["content"]
        assert "literal {claim} braces {}" in messages[1]["content"]
        with pytest.raises(TypeError):
            prompts.render(arm, claim="c", evidence="e", label="SUPPORTS")
    all_rows = [r for p in (ROOT / "data/raw/benchmark_1011").glob("*.jsonl") for r in read_jsonl(p)]
    prompts.validate_example(all_rows)
    with pytest.raises(ValueError, match="overlaps"):
        prompts.validate_example([{"claim": EXAMPLE_CLAIM, "evidence": "other", "id": "fixture"}])


def test_pilot_is_frozen_complete_groups_with_label_coverage():
    config = load_config()
    for dataset, expected_count, group_count in (("challenge", 87, 14), ("basic", 60, 7)):
        pilot = load_pilot(config, dataset)
        dev = read_jsonl(ROOT / "data/splits/v1" / dataset / "dev.jsonl")
        test = read_jsonl(ROOT / "data/splits/v1" / dataset / "test.jsonl")
        assert choose_pilot(list(reversed(dev)), dataset, 20261022) == pilot
        groups = {r["group"] for r in pilot}
        assert len(pilot) == expected_count and len(groups) == group_count
        assert {r["label"] for r in pilot} == set(LABELS)
        assert not groups & {r["group"] for r in test}
        assert {r["id"] for r in pilot} == {r["id"] for r in dev if r["group"] in groups}


def test_smoke_cases_are_independent_of_benchmark():
    from ab_factcheck.cli import SMOKE_ROWS
    all_rows = [r for p in (ROOT / "data/raw/benchmark_1011").glob("*.jsonl") for r in read_jsonl(p)]
    pairs = {(r["claim"].strip(), r["evidence"].strip()) for r in all_rows}
    assert not pairs & {(r["claim"], r["evidence"]) for r in SMOKE_ROWS}
    assert {r["label"] for r in SMOKE_ROWS} == set(LABELS)


@pytest.mark.parametrize("endpoint", [
    "https://api.openai.com/v1", "http://192.168.1.2:8081/v1", "http://127.0.0.1.evil.test/v1",
    "http://localhost@evil.test/v1", "http://127.0.0.1/v1?redirect=external", "file:///v1",
])
def test_reject_remote_endpoints(endpoint):
    with pytest.raises(ValueError):
        validate_endpoint(endpoint)


def test_retry_budget_and_redirect_rejection():
    config = load_config()["model"]
    calls = []
    def failing(request):
        calls.append(request)
        return httpx.Response(503, json={"error": "unavailable"})
    client = LocalModelClient(config, transport=httpx.MockTransport(failing), sleeper=lambda _: None)
    with pytest.raises(RequestFailure) as exc:
        client._request("GET", "/health")
    assert exc.value.transient and exc.value.attempts == 3 and len(calls) == 3
    client.close()
    calls.clear()
    def redirect(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://external.invalid/"})
    client = LocalModelClient(config, transport=httpx.MockTransport(redirect), sleeper=lambda _: None)
    with pytest.raises(RequestFailure):
        client._request("GET", "/health")
    assert len(calls) == 1
    client.close()


def test_local_api_success_retry_and_context_preflight():
    config = load_config()["model"]
    calls, completions = [], []
    def service(request):
        calls.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "actual-local-id"}]})
        if request.url.path == "/props":
            return httpx.Response(200, json={"default_generation_settings": {"n_ctx": 8192}, "chat_template": "template"})
        if request.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": "formatted"})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1, 2, 3]})
        payload = json.loads(request.content)
        completions.append(payload)
        if len(completions) == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Verdict: SUPPORTS"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}})
    client = LocalModelClient(config, transport=httpx.MockTransport(service), sleeper=lambda _: None)
    response = client.complete([{"role": "user", "content": "synthetic fixture"}])
    assert response["completion_request_attempts"] == 2
    assert completions[-1]["model"] == "actual-local-id"
    assert completions[-1]["cache_prompt"] is False
    client.count_prompt = lambda _: 8000
    with pytest.raises(RequestFailure, match="context_overflow"):
        client.complete([])
    assert len(completions) == 2
    client.close()


def metric_record(sample_id, gold, pred, valid=True):
    return {"id": sample_id, "group": "g" + sample_id, "gold_label": gold, "predicted_label": pred,
            "parse_status": "ok" if valid else "invalid", "status": "completed"}


def test_metrics_invalid_denominator_and_pairing():
    rows = [metric_record("1", "SUPPORTS", "SUPPORTS"), metric_record("2", "REFUTES", "SUPPORTS"),
            metric_record("3", "NOT ENOUGH INFO", "REFUTES"), metric_record("4", "NOT ENOUGH INFO", "NOT ENOUGH INFO", False)]
    m = compute_metrics(rows)
    assert m["accuracy"] == 0.25
    assert m["valid_only_accuracy"] == 1 / 3
    assert m["nei_to_refutes_rate"] == 0.5
    assert m["confusion_matrix"]["NOT ENOUGH INFO"]["INVALID"] == 1
    assert m["classes"]["SUPPORTS"]["precision"] == 0.5
    assert m["classes"]["SUPPORTS"]["recall"] == 1
    assert m["macro_f1"] == pytest.approx(2 / 9)
    after = copy.deepcopy(rows)
    after[0]["predicted_label"] = "REFUTES"
    after[2]["predicted_label"] = "NOT ENOUGH INFO"
    pairs = paired_comparison(rows, after)
    assert pairs["improved_ids"] == ["3"] and pairs["harmed_ids"] == ["1"]
    assert pairs["accuracy_delta"] == 0
    with pytest.raises(ValueError):
        paired_comparison(rows, after[:-1])


class FakePrompts:
    hashes = {arm: "fixture" for arm in ARMS}
    def render(self, arm, *, claim, evidence):
        return [{"role": "user", "content": claim + evidence}]


class FakeClient:
    model_id = "fixture-not-a-real-model"
    def __init__(self):
        self.calls = 0
        self.interrupt_on = None
        self.fail_on = None
    def complete(self, messages):
        self.calls += 1
        if self.calls == self.interrupt_on:
            raise KeyboardInterrupt
        if self.calls == self.fail_on:
            raise RequestFailure("fixture disconnected", transient=True, attempts=3)
        return {"raw_response": "Verdict: SUPPORTS", "finish_reason": "stop", "usage": {}, "latency_seconds": 0.01}


def fixture_rows():
    return [{"id": str(i), "group": f"g{i}", "mechanism": "synthetic", "label": "SUPPORTS", "claim": "c", "evidence": "e"} for i in range(2)]


def test_resume_after_interrupt_and_refuse_changed_fingerprint(tmp_path):
    client = FakeClient()
    client.interrupt_on = 2
    session = RunSession(tmp_path, load_config(), FakePrompts(), client, {"fixture": 1})
    with pytest.raises(KeyboardInterrupt):
        session.run("synthetic", fixture_rows(), ("A0",), split="smoke")
    assert not (tmp_path / "run.lock").exists()
    client.interrupt_on = None
    session.run("synthetic", fixture_rows(), ("A0",), split="smoke")
    assert client.calls == 3
    session.run("synthetic", fixture_rows(), ("A0",), split="smoke")
    assert client.calls == 3
    rows = read_jsonl(tmp_path / "synthetic.jsonl")
    assert len(rows) == 6 and len({(r["id"], r["arm"]) for r in rows}) == 6
    assert sum(r["status"] == "completed" for r in rows) == 2
    changed = RunSession(tmp_path, load_config(), FakePrompts(), client, {"fixture": 2})
    with pytest.raises(ValueError, match="Frozen artifact differs"):
        changed.run("synthetic", fixture_rows())


def test_transient_failure_can_resume_without_rerunning_completed_rows(tmp_path):
    client = FakeClient()
    client.fail_on = 1
    session = RunSession(tmp_path, load_config(), FakePrompts(), client, {"fixture": 1})
    session.run("synthetic", fixture_rows(), ("A0",), split="smoke")
    assert client.calls == 2
    session.run("synthetic", fixture_rows(), ("A0",), split="smoke")
    assert client.calls == 3
    saved = read_jsonl(tmp_path / "synthetic.jsonl")
    assert saved[0]["previous_failures"][0]["request_attempts"] == 3


def test_atomic_replace_failure_preserves_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "record.json"
    target.write_bytes(b"old")
    def fail_replace(*_):
        raise OSError("fixture interruption")
    monkeypatch.setattr("ab_factcheck.common.os.replace", fail_replace)
    with pytest.raises(OSError):
        atomic_bytes(target, b"new")
    assert target.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [target]
