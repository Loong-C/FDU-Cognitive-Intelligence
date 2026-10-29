import itertools
import json

import pytest

from ab_factcheck.negation_v8.inference import FLIP, decide, messages, needs_negative, negate, request


def test_whole_proposition_negation_preserves_literal_input():
    claim = 'All A are B and C; "quoted" text and {evidence}.\nSecond clause.'
    wrapped = negate(claim)
    prefix = "It is not the case that the following statement holds: "
    assert json.loads(wrapped[len(prefix):]) == claim
    assert messages("negative", claim=claim, evidence="Original E")[1]["content"] == "PREMISE:\nOriginal E\n\nHYPOTHESIS:\n" + wrapped


def test_no_metadata_or_gold_interface():
    with pytest.raises(TypeError):
        messages("negative", claim="C", evidence="E", gold="SUPPORTS")
    for invalid in ("", " ", None):
        with pytest.raises(ValueError):
            negate(invalid)


@pytest.mark.parametrize("positive", list(FLIP))
def test_exact_polarity_and_neutral_mapping(positive):
    baseline = next(x for x in FLIP if x != positive)
    negative = FLIP[positive]
    assert FLIP[negative] == positive
    assert decide(baseline, positive, negative) == (positive, "negation_consistent_override")


def test_inconsistency_is_not_converted_to_neutral():
    assert decide("SUPPORTS", "REFUTES", "REFUTES") == ("SUPPORTS", "negation_inconsistent_fallback")
    assert decide("REFUTES", "NOT ENOUGH INFO", "SUPPORTS") == ("REFUTES", "negation_inconsistent_fallback")
    assert decide("SUPPORTS", "REFUTES") == ("INVALID", "pending_negative")


def test_adaptive_shortcut_equals_full_consensus_for_every_label_combination():
    for baseline, positive, negative in itertools.product(FLIP, repeat=3):
        expected = positive if positive == FLIP[negative] else baseline
        shortcut = decide(baseline, positive, negative if needs_negative(baseline, positive) else None)[0]
        assert shortcut == expected


def test_bad_negative_cannot_override_valid_baseline():
    assert decide("SUPPORTS", "REFUTES", "INVALID")[0] == "SUPPORTS"
    assert decide("SUPPORTS", "INVALID")[0] == "SUPPORTS"
    assert request("negative", claim="C", evidence="E")["max_completion_tokens"] == 512
