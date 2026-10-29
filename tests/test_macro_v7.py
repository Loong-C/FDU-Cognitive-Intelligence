import json
from pathlib import Path

import pytest

from ab_factcheck.groq_client import GroqStop
from ab_factcheck.macro_v7.experiment import load_dev, receive
from ab_factcheck.macro_v7.inference import conservative_consensus, messages, parse
from ab_factcheck.macro_v7.report import cluster_interval, gate
from ab_factcheck.metrics import compute_metrics
from ab_factcheck.macro_v7.revision import resolve, review_messages, parse_review
from ab_factcheck.macro_v7.assess import paired_statistics


def completion(value, finish="stop"):
    return {"raw_response": json.dumps(value), "finish_reason": finish, "provider_validation_issues": []}


@pytest.mark.parametrize("true,false,expected", [(True, False, "SUPPORTS"), (False, True, "REFUTES"),
    (False, False, "NOT ENOUGH INFO"), (True, True, "INVALID")])
def test_entailment_directions(true, false, expected):
    assert parse("dual", completion({"justification": "synthetic", "claim_entailed": true, "negation_entailed": false}))["label"] == expected


def test_invalid_output_never_guessed_or_repaired():
    assert parse("dual", completion({"justification": "x", "claim_entailed": "false", "negation_entailed": False}))["label"] == "INVALID"
    assert parse("certificate", completion({"justification": "x", "verdict": "SUPPORTS"}, "length"))["label"] == "INVALID"
    r = completion({})
    r["raw_response"] = '{"justification":"x","verdict":"SUPPORTS","verdict":"REFUTES"}'
    assert parse("certificate", r)["label"] == "INVALID"


def test_no_metadata_interface_or_test_loader():
    with pytest.raises(TypeError):
        messages("nli", claim="c", evidence="e", label="SUPPORTS")
    for name in ("test", "../test", "basic/test.jsonl"):
        with pytest.raises(ValueError):
            load_dev(name)


def test_literal_input_not_interpolated_twice():
    m = messages("baseline", claim="{evidence}", evidence="{claim}")
    assert "EVIDENCE:\n{claim}" in m[1]["content"]
    assert "CLAIM:\n{evidence}" in m[1]["content"]


def test_consensus_is_label_symmetric_and_invalid_cannot_override():
    for label in ("SUPPORTS", "REFUTES", "NOT ENOUGH INFO"):
        assert conservative_consensus("SUPPORTS", [label, label]) == label
    assert conservative_consensus("SUPPORTS", ["REFUTES", "NOT ENOUGH INFO"]) == "SUPPORTS"
    assert conservative_consensus("SUPPORTS", ["INVALID", "INVALID"]) == "SUPPORTS"


def test_received_answer_is_cached_and_tampering_fails(tmp_path):
    class Fake:
        calls = 0
        def complete(self, **request):
            self.calls += 1
            return completion({"verdict": "SUPPORTS", "reason": "synthetic"})
    client = Fake()
    p = tmp_path / "response.json"
    request = {"messages": [{"role": "user", "content": "synthetic"}]}
    first = receive(client, p, request, "freeze")
    assert receive(client, p, request, "freeze") == first
    assert client.calls == 1
    with pytest.raises(GroqStop):
        receive(client, p, {"messages": []}, "freeze")
    first["raw_response"] = "changed"
    p.write_text(json.dumps(first))
    with pytest.raises(GroqStop):
        receive(client, p, request, "freeze")


def test_ambiguous_request_not_automatically_resent(tmp_path):
    p = tmp_path / "response.json"
    p.with_suffix(".inflight").write_text("{}")
    with pytest.raises(GroqStop, match="Ambiguous"):
        receive(None, p, {}, "freeze")


def test_better_overall_accuracy_cannot_hide_a_recall_regression():
    gold = ["SUPPORTS", "REFUTES", "NOT ENOUGH INFO", "NOT ENOUGH INFO"]
    def metrics(pred):
        return compute_metrics([{"gold_label": g, "predicted_label": p, "parse_status": "ok"} for g, p in zip(gold, pred)])
    base = metrics(["SUPPORTS", "REFUTES", "REFUTES", "REFUTES"])
    candidate = metrics(["SUPPORTS", "NOT ENOUGH INFO", "NOT ENOUGH INFO", "NOT ENOUGH INFO"])
    result = gate(base, candidate)
    assert result["accuracy_improved"]
    assert not result["no_regression"]
    assert result["deltas"]["recall_REFUTES"] == -1.


def test_bootstrap_resamples_groups_as_paired_blocks():
    before = [{"id": str(i), "group": "a" if i < 3 else "b", "gold_label": "SUPPORTS", "predicted_label": "REFUTES"} for i in range(4)]
    after = [r | {"predicted_label": "SUPPORTS"} for r in before]
    result = cluster_interval(before, after, iterations=100)
    assert result["groups"] == 2
    assert result["delta_accuracy_percentile_95"] == [1., 1.]


def test_disagreement_review_never_uses_an_unreceived_answer():
    assert resolve("SUPPORTS", "SUPPORTS") == ("SUPPORTS", "agreement")
    assert resolve("SUPPORTS", "INVALID") == ("SUPPORTS", "invalid_alternative_fallback")
    assert resolve("SUPPORTS", "REFUTES") == ("INVALID", "pending_review")
    assert resolve("SUPPORTS", "REFUTES", "INVALID") == ("SUPPORTS", "invalid_review_fallback")
    assert resolve("SUPPORTS", "REFUTES", "NOT ENOUGH INFO") == ("NOT ENOUGH INFO", "review")


def test_blind_reviewer_sees_only_original_inputs():
    m = review_messages(evidence="Original evidence", claim="Original claim")
    assert "Original evidence" in m[1]["content"] and "Original claim" in m[1]["content"]
    assert m[1]["content"] == "CLAIM:\nOriginal claim\n\nEVIDENCE:\nOriginal evidence"
    with pytest.raises(TypeError):
        review_messages(evidence="e", claim="c", baseline={}, alternative={}, gold="SUPPORTS")
    assert parse_review(completion({"evidence_assessment": "x", "verdict": "SUPPORTS"}, "length")) == "INVALID"


def test_group_test_does_not_treat_related_variants_as_independent():
    # 60 changed variants, but all of them are in one group: no significant evidence.
    before = [{"id": str(i), "group": "one_group", "gold_label": "SUPPORTS", "predicted_label": "REFUTES", "parse_status": "ok"} for i in range(60)]
    after = [r | {"predicted_label": "SUPPORTS"} for r in before]
    result = paired_statistics(before, after, resamples=20)
    assert result["permutations"] == 2
    assert result["metrics"]["accuracy"]["group_paired_two_sided_p"] == 1.
    assert not result["metrics"]["accuracy"]["significant_improvement"]


def test_paired_significance_detects_consistent_group_losses():
    before = [{"id": str(i), "group": str(i), "gold_label": "SUPPORTS", "predicted_label": "SUPPORTS", "parse_status": "ok"} for i in range(7)]
    after = [r | {"predicted_label": "REFUTES"} for r in before]
    result = paired_statistics(before, after, resamples=20)
    assert result["metrics"]["accuracy"]["group_paired_two_sided_p"] == 2/128
    assert result["metrics"]["accuracy"]["significant_regression"]
