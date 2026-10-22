"""Exercise report provenance and arithmetic with clearly synthetic fixtures."""

import copy
import json

import pytest

from ab_factcheck.common import ARMS, atomic_json, file_hash, load_config, read_jsonl, write_jsonl
from ab_factcheck.reporting import report


def test_report_recomputes_separate_datasets_and_rejects_missing_or_forged_records(tmp_path, monkeypatch):
    config = copy.deepcopy(load_config())
    config["run_id"] = "unit_test_fixture_not_real_inference"
    monkeypatch.setattr("ab_factcheck.reporting.ROOT", tmp_path)
    source_rows = [
        {"id": "one", "group": "g1", "mechanism": "fixture", "label": "SUPPORTS", "claim": "synthetic", "evidence": "fixture"},
        {"id": "two", "group": "g2", "mechanism": "fixture", "label": "REFUTES", "claim": "synthetic", "evidence": "fixture"},
    ]
    monkeypatch.setattr("ab_factcheck.reporting.load_pilot", lambda *_: source_rows)
    run_dir = tmp_path / config["output_root"] / config["run_id"]
    atomic_json(run_dir / "fingerprint.json", {"configuration": config})
    fingerprint = file_hash(run_dir / "fingerprint.json")
    for dataset in ("challenge", "basic"):
        rows = []
        for arm in ARMS:
            for row in source_rows:
                rows.append({"run_id": config["run_id"], "dataset": dataset, "arm": arm,
                             "id": row["id"], "group": row["group"], "mechanism": row["mechanism"],
                             "gold_label": row["label"], "predicted_label": row["label"] if arm == "A0" else "SUPPORTS",
                             "status": "completed", "parse_status": "ok", "raw_response": "MOCK RESPONSE FOR UNIT TEST ONLY",
                             "run_fingerprint_sha256": fingerprint, "consistency_status": "not_applicable"})
        write_jsonl(run_dir / f"{dataset}.jsonl", rows)
    result = report(config)
    assert result["record_count"] == 12
    assert result["datasets"]["challenge"]["arms"]["A0"]["accuracy"] == 1
    assert result["datasets"]["basic"]["paired"]["B1-A0"]["harmed"] == 1
    report_dir = tmp_path / config["report_root"] / config["run_id"]
    assert (report_dir / "pilot_report.md").is_file()
    assert (report_dir / "metrics_challenge.csv").is_file()
    assert (report_dir / "metrics_basic.csv").is_file()
    assert json.loads((report_dir / "configuration.json").read_text(encoding="utf-8")) == config
    assert file_hash(report_dir / "run_fingerprint.json") == fingerprint
    review_csv = (report_dir / "review_queue.csv").read_text(encoding="utf-8-sig")
    assert "record_path" in review_csv
    assert "MOCK RESPONSE FOR UNIT TEST ONLY" not in review_csv
    original = read_jsonl(run_dir / "basic.jsonl")
    write_jsonl(run_dir / "basic.jsonl", original[:-1])
    with pytest.raises(ValueError, match="Incomplete"):
        report(config)
    original[0]["run_fingerprint_sha256"] = "forged"
    write_jsonl(run_dir / "basic.jsonl", original)
    with pytest.raises(ValueError, match="provenance"):
        report(config)
