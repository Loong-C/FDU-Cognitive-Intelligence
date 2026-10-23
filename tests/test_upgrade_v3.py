"""Infrastructure fixtures only: none of these are experimental model results."""

import copy
import json

import httpx
import pytest

from ab_factcheck.common import ROOT, atomic_json, experiment_arms, file_hash, load_config, read_jsonl, write_jsonl
from ab_factcheck.model_client import LocalModelClient, nonthinking_check
from ab_factcheck.prompts import PromptSet
from ab_factcheck.runner import RunSession, make_fingerprint
from ab_factcheck.structured import parse_structured, response_format_for


def config():
    return load_config(ROOT / "configs/experiment_14b_v3.json")


def test_two_arms_do_not_change_legacy_defaults_or_prompt_bytes():
    assert experiment_arms(load_config()) == ("A0", "B1", "C1")
    assert experiment_arms(load_config(ROOT / "configs/experiment_v2.json")) == ("A2", "B2", "C2")
    assert experiment_arms(config()) == ("A2", "B2")
    all_prompts = PromptSet(ROOT / "prompts/v2")
    subset = PromptSet(ROOT / "prompts/v2", ("A2", "B2"))
    assert subset.arms == ("A2", "B2")
    for arm in subset.arms:
        assert subset.templates[arm] == all_prompts.templates[arm]
        assert subset.hashes[arm] == all_prompts.hashes[arm]


@pytest.mark.parametrize("arms", [[], ["B2", "A2"], ["A2", "A2"], ["A2", "C2"], ["A14", "B14"], "A2"])
def test_unsupported_arm_sets_fail(arms):
    with pytest.raises(ValueError):
        experiment_arms({**config(), "arms": arms})


@pytest.mark.parametrize("message,usage,passed", [
    ({"content": "{}"}, {}, True),
    ({"content": "<think>\n</think>{}"}, {}, True),
    ({"content": "<think>hidden</think>{}"}, {}, False),
    ({"content": "hidden</think>{}"}, {}, False),
    ({"content": "{}", "reasoning_content": "hidden"}, {}, False),
    ({"content": "{}"}, {"completion_tokens_details": {"reasoning_tokens": 4}}, False),
])
def test_raw_reasoning_is_detected_without_stripping(message, usage, passed):
    response = {"choices": [{"message": message}], "usage": usage}
    before = copy.deepcopy(response)
    assert nonthinking_check(response)["passed"] is passed
    assert response == before


def test_template_count_and_generation_share_nonthinking_options():
    seen = {}
    def handler(request):
        payload = json.loads(request.content)
        seen[request.url.path] = payload
        if request.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": "fixture<think>\n\n</think>\n\n"})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1, 2, 3]})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"verdict":"SUPPORTS","reason":"fixture"}'}, "finish_reason": "stop"}],
                                        "usage": {"prompt_tokens": 3, "completion_tokens": 4}})
    client = LocalModelClient(config()["model"], transport=httpx.MockTransport(handler))
    client.model_id = "fixture"
    result = client.complete([{"role": "user", "content": "fixture only"}], response_format=response_format_for("A2"))
    for route in ("/apply-template", "/v1/chat/completions"):
        assert seen[route]["chat_template_kwargs"] == {"enable_thinking": False}
        assert seen[route]["reasoning_format"] == "deepseek"
    assert result["nonthinking_validation"]["passed"] and result["prompt_count_matches"]
    assert len(result["applied_template"]["sha256"]) == 64
    client.close()


def test_fingerprint_binds_template_options_and_new_inference_sources():
    c = config()
    prompts = PromptSet(ROOT / c["prompts_dir"], experiment_arms(c))
    runtime = {"model_id": "fixture", "props": {"chat_template": "fixture", "default_generation_settings": {"n_ctx": 8192}}}
    a = make_fingerprint(c, prompts, runtime)
    changed = copy.deepcopy(c); changed["model"]["chat_template_kwargs"]["enable_thinking"] = True
    b = make_fingerprint(changed, prompts, runtime)
    assert a != b
    assert set(a["response_formats"]) == {"A2", "B2"}
    assert "preflight_v3.py" in a["inference_source_sha256"]


def test_v3_records_invalid_format_once_and_resume_skips_it(tmp_path):
    class Client:
        model_id = "fixture"
        calls = 0
        def complete(self, messages, *, response_format):
            self.calls += 1
            return {"raw_response": "not json", "finish_reason": "length", "usage": {}, "latency_seconds": 0.1,
                    "nonthinking_validation": {"passed": True}, "prompt_count_matches": True}
    rows = [{"id": str(i), "group": "fixture", "mechanism": "fixture", "label": "SUPPORTS", "claim": "c", "evidence": "e"} for i in range(2)]
    client = Client()
    session = RunSession(tmp_path, config(), PromptSet(ROOT / "prompts/v2", ("A2", "B2")), client, {"fixture": True})
    session.run("synthetic", rows)
    assert client.calls == 4
    session.run("synthetic", rows)
    assert client.calls == 4
    saved = read_jsonl(tmp_path / "synthetic.jsonl")
    assert len(saved) == 4 and all(r["parse_status"] == "invalid" for r in saved)
    changed = RunSession(tmp_path, config(), session.prompts, client, {"fixture": "changed"})
    with pytest.raises(ValueError, match="Frozen artifact differs"):
        changed.run("synthetic", rows)


def test_context_4096_requires_all_inputs_and_output_budget(tmp_path, monkeypatch):
    from ab_factcheck.preflight_v3 import context_preflight
    monkeypatch.setattr("ab_factcheck.preflight_v3.ROOT", tmp_path)
    monkeypatch.setattr("ab_factcheck.preflight_v3.load_pilot", lambda *_: [{"id": "fixture", "claim": "c", "evidence": "e"}])
    class Client:
        last_template_summary = {"options": {"chat_template_kwargs": {"enable_thinking": False}}}
        def count_prompt(self, messages): return 3073
    c = config(); c["model"]["context_tokens"] = 4096
    with pytest.raises(ValueError, match="exceed context"):
        context_preflight(c, PromptSet(ROOT / "prompts/v2", ("A2", "B2")), Client())
    saved = json.loads((tmp_path / c["output_root"] / c["run_id"] / "context_preflight.json").read_text())
    assert len(saved["records"]) == 4 and not saved["passed"]


def test_resource_screen_requires_ram_and_real_vram_margin():
    from ab_factcheck.resources_v3 import startup_issues
    resources = {"available_ram_bytes": 18 * 1024**3, "disk_free_bytes": 100 * 1024**3, "gpus": [{"free_mib": 5600}]}
    assert startup_issues(config(), resources, 16) == []
    assert startup_issues(config(), resources, 40)
    assert startup_issues(config(), {**resources, "available_ram_bytes": 8 * 1024**3}, 16)
    assert startup_issues(config(), {**resources, "gpus": [{"free_mib": 1000}]}, 16)


def test_two_arm_report_pairs_baseline_and_selects_review_without_c2(tmp_path, monkeypatch):
    from ab_factcheck.reporting import report
    c = config(); c["run_id"] = "fixture_not_model_predictions"
    c["review"]["typical_ids"] = ["one"]
    source = [{"id": "one", "group": "g", "mechanism": "DENIAL", "label": "NOT ENOUGH INFO", "claim": "c", "evidence": "e"}]
    for module in ("ab_factcheck.reporting", "ab_factcheck.reporting_v3"):
        monkeypatch.setattr(module + ".ROOT", tmp_path)
        monkeypatch.setattr(module + ".load_pilot", lambda *_: source)
    run = tmp_path / c["output_root"] / c["run_id"]
    atomic_json(run / "fingerprint.json", {"configuration": c})
    old_run = tmp_path / "outputs/runs" / c["historical_run_id"]
    old_metrics = {"source_jsonl_sha256": {}}
    for dataset in ("challenge", "basic"):
        rows = []
        for arm in ("A2", "B2"):
            value = {"verdict": "REFUTES", "reason": "fixture"} if arm == "A2" else {
                "true_world": "POSSIBLE", "false_world": "POSSIBLE", "true_reason": "fixture", "false_reason": "fixture"}
            rows.append({"id": "one", "group": "g", "mechanism": "DENIAL", "gold_label": "NOT ENOUGH INFO", "dataset": dataset,
                         "run_id": c["run_id"], "arm": arm, "run_fingerprint_sha256": file_hash(run / "fingerprint.json"), "status": "completed",
                         "finish_reason": "stop", "latency_seconds": 1., "usage": {"completion_tokens": 10}, **parse_structured(json.dumps(value), arm, "stop")})
        write_jsonl(run / f"{dataset}.jsonl", rows)
        write_jsonl(old_run / f"{dataset}.jsonl", rows)
        old_metrics["source_jsonl_sha256"][dataset] = file_hash(old_run / f"{dataset}.jsonl")
    atomic_json(tmp_path / c["historical_report_root"] / c["historical_run_id"] / "metrics.json", old_metrics)
    result = report(c)
    assert set(result["datasets"]["challenge"]["arms"]) == {"A2", "B2"}
    assert set(result["datasets"]["challenge"]["paired"]) == {"B2-A2"}
    dest = tmp_path / c["report_root"] / c["run_id"]
    upgrade = json.loads((dest / "upgrade_comparison.json").read_text())
    assert upgrade["comparisons"]["challenge"]["B14-A14"]["accuracy_delta"] == 1
    assert upgrade["comparisons"]["challenge"]["descriptive_interaction_accuracy_delta"] == 0
    assert "C2" not in (dest / "predictions.csv").read_text(encoding="utf-8-sig")
