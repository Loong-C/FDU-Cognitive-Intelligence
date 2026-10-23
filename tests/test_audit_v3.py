"""Independent auditor tests; fabricated fixtures never become run records."""
import importlib.util
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(scripts))
import audit_14b_run as audit


def test_independent_metric_counts_invalid_as_wrong():
    rows = [{"id": str(i), "group": "g", "gold_label": label, "audit_prediction": pred, "status": "completed"}
            for i, (label, pred) in enumerate(zip(audit.LABELS, ("SUPPORTS", "INVALID", "REFUTES")))]
    result = audit.measure(rows)
    assert result["accuracy"] == 1/3
    assert result["invalid"] == 1 and result["nei_to_refutes"] == 1
    assert result["classes"]["REFUTES"]["recall"] == 0


def test_independent_pairing_rejects_changed_gold_and_duplicate_ids():
    before = [{"id": "x", "group": "g", "gold_label": "SUPPORTS", "audit_prediction": "REFUTES"}]
    after = [{**before[0], "audit_prediction": "SUPPORTS"}]
    assert audit.pair(before, after)["improved_ids"] == ["x"]
    with pytest.raises(ValueError): audit.pair(before, after + after)
    with pytest.raises(ValueError): audit.pair(before, [{**after[0], "gold_label": "REFUTES"}])


def test_independent_reasoning_check_examines_hidden_field_and_usage():
    with pytest.raises(ValueError):
        audit.reasoning_clear({"choices": [{"message": {"content": "{}", "reasoning_content": "hidden"}}]})
    with pytest.raises(ValueError):
        audit.reasoning_clear({"choices": [], "usage": {"completion_tokens_details": {"reasoning_tokens": 1}}})
