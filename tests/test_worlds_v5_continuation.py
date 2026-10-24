"""No network: provider-quota policy and immutable response-lineage tests."""
import copy
import json

import httpx
import pytest

from ab_factcheck.common import ROOT, atomic_json, file_hash
from ab_factcheck.groq_client import GroqStop
from ab_factcheck.worlds_v5.client import Halt
from ab_factcheck.worlds_v5.models import Problem
from ab_factcheck.worlds_v5.orchestrator import Orchestrator
from ab_factcheck.worlds_v5.prompts import FrozenPrompts
from ab_factcheck.worlds_v5_continuation import ProviderFreeClient, LineageOrchestrator, load_policy


class Clock:
    def __init__(self): self.t = 500000.0
    def __call__(self): return self.t
    def sleep(self, n): self.t += n


def handler(req):
    p = json.loads(req.content)
    schema = p.get("response_format", {}).get("json_schema", {}).get("schema")
    content = json.dumps({k: v["enum"][0] if "enum" in v else "fictional fixture" for k, v in schema["properties"].items()}) if schema else "NOT_JSON"
    return httpx.Response(200, json={"id": "fixture", "model": "qwen/qwen3.8-27b",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})


def make(tmp_path, monkeypatch, responder=handler, config=None):
    monkeypatch.setenv("GROQ_API_KEY", "fake-continuation-secret")
    config = config or load_policy(ROOT / "configs/continuation_worlds_v5_free.json")
    model = {**config["model"], "proxy_mode": "direct"}
    clock = Clock()
    return ProviderFreeClient(model, tmp_path / "ledger.json", config["continuation_policy"], free_plan_confirmed=True,
                              transport=httpx.MockTransport(responder), clock=clock, sleeper=clock.sleep)


def test_authorized_policy_keeps_same_model_and_throttle():
    c = load_policy(ROOT / "configs/continuation_worlds_v5_free.json")
    assert c["model"]["budget"]["tokens_24h"] == 200000
    assert c["continuation_policy"]["local_rolling_daily_stop"] is False
    assert c["limits"] == {"constructor": 384, "verifier": 384, "baseline": 1024, "probe": 384}


def test_old_daily_totals_do_not_fake_provider_exhaustion(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    old = [{"timestamp": c.clock()-120, "charged_tokens": 500, "status": "received"} for _ in range(1001)]
    atomic_json(c.ledger_path, {"attempts": old, "blocked_until": 0})
    c.complete([])
    assert c.ledger()["attempts"][:1001] == old
    assert len(c.ledger()["attempts"]) == 1002


def test_daily_429_stops_and_persists_without_retry_storm(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch, lambda req: httpx.Response(429, headers={"retry-after": "3600"}, json={"error": {"message": "TPD exhausted"}}))
    for _ in range(2):
        with pytest.raises(Halt, match="bounded wait"): c.complete([])
    assert len(c.ledger()["attempts"]) == 1
    assert c.ledger()["blocked_until"] > c.clock()


def test_minute_throttle_and_unknown_failures_keep_accounting(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    c.complete([]); t = c.clock()
    c.complete([])
    assert c.clock() >= t+3
    assert all(a["reservation_tokens"] > a["charged_tokens"] for a in c.ledger()["attempts"])


def test_large_byte_bound_not_misreported_as_actual_token_count(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    c.complete([{"role": "user", "content": "a" * 9000}])
    assert c.ledger()["attempts"][0]["reservation_tokens"] > 8000
    assert c.ledger()["attempts"][0]["charged_tokens"] == 120


def test_execution_cap_is_bounded(tmp_path, monkeypatch):
    config = load_policy(ROOT / "configs/continuation_worlds_v5_free.json")
    config["continuation_policy"]["max_new_attempts_per_execution"] = 1
    c = make(tmp_path, monkeypatch, config=config)
    c.complete([])
    with pytest.raises(Halt, match="attempt cap"): c.complete([])
    assert len(c.ledger()["attempts"]) == 1


def test_lineage_reuses_all_nodes_without_new_calls_or_parent_edits(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    config = load_policy(ROOT / "configs/continuation_worlds_v5_free.json")
    prompts = FrozenPrompts(ROOT / "prompts/v5")
    fp = {"config": config, "source_sha256": {}}
    parent = Orchestrator(tmp_path / "parent", prompts, fp, config["limits"], c)
    parent.initialize(); parent.item("d", "i", Problem("e", "c"))
    before = {p.name: file_hash(p) for p in parent.directory.rglob("*.json")}
    child = LineageOrchestrator(tmp_path / "child", prompts, {**fp, "continuation": True}, config["limits"],
                                parent_directory=parent.directory, root=tmp_path)
    child.initialize()
    assert child.item("d", "i", Problem("e", "c"))["label"] == "NOT ENOUGH INFO"
    assert len(c.ledger()["attempts"]) == 4
    assert before == {p.name: file_hash(p) for p in parent.directory.rglob("*.json")}
    records = [json.loads(p.read_text()) for p in child.directory.rglob("*.json")]
    assert sum("reused_from" in r for r in records) == 4
    child.item("d", "i", Problem("e", "c"))
    assert len(c.ledger()["attempts"]) == 4


def test_lineage_refuses_changed_input_and_ambiguous_parent(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    config = load_policy(ROOT / "configs/continuation_worlds_v5_free.json")
    prompts = FrozenPrompts(ROOT / "prompts/v5")
    fp = {"config": config, "source_sha256": {}}
    parent = Orchestrator(tmp_path / "parent", prompts, fp, config["limits"], c)
    parent.initialize(); parent.receive("node.json", [], None, limit=384)
    child = LineageOrchestrator(tmp_path / "child", prompts, fp, config["limits"],
                                parent_directory=parent.directory, root=tmp_path)
    with pytest.raises(GroqStop, match="differs"): child.receive("node.json", [{"role":"user","content":"changed"}], None, limit=384)
    (parent.directory / "other.inflight").write_text("{}")
    with pytest.raises(GroqStop, match="ambiguous"): child.receive("other.json", [], None, limit=384)


def test_no_free_confirmation_still_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake")
    c = load_policy(ROOT / "configs/continuation_worlds_v5_free.json")
    with pytest.raises(GroqStop, match="Free Plan"):
        ProviderFreeClient(c["model"], tmp_path / "q", c["continuation_policy"])
