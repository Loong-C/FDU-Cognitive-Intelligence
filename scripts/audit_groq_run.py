"""Independent recomputation of round-four report metrics; no model requests."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ab_factcheck.common import ROOT, LABELS, atomic_json
from ab_factcheck.groq_v4 import Experiment, load_config
from ab_factcheck.reporting_groq import audit, independent_parse, records_for


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/experiment_groq_27b_v4.json")
    args = parser.parse_args()
    exp = Experiment(load_config(args.config))
    receipt = audit(exp)
    rows = records_for(exp)
    attempt_keys = []
    for row in rows:
        for attempt in row["attempts"]:
            attempt_keys.append((attempt["timestamp"], attempt["request_sha256"]))
    assert len(attempt_keys) == len(set(attempt_keys)), "An HTTP attempt was reused across formal records"
    preflight_checks = []
    if receipt["gates"]["technical"]:
        def read(path):
            return json.loads(path.read_text(encoding="utf-8"))
        technical = exp.directory / "technical"
        assert read(technical / "control.json")["raw_response"].strip() == "NOT_JSON"
        for arm in ("A2", "B2"):
            r = read(technical / f"sentinel_{arm}.json")
            obj = json.loads(r["raw_response"])
            schema = r["request_payload"]["response_format"]["json_schema"]["schema"]
            assert set(obj) == set(schema["required"])
            for key, spec in schema["properties"].items():
                assert isinstance(obj[key], str)
                if "enum" in spec: assert obj[key] in spec["enum"]
                if "maxLength" in spec: assert len(obj[key]) <= spec["maxLength"]
            key = "verdict" if arm == "A2" else "true_world"
            assert obj[key] == "SCHEMA_SENTINEL_" + arm
            assert "SCHEMA_SENTINEL" not in json.dumps(r["request_payload"]["messages"])
            assert r["finish_reason"] == "stop"
        long = read(technical / "length_control.json")
        short = read(technical / "length_constrained.json")
        assert len(json.loads(long["raw_response"])["reason"]) > 320
        assert len(json.loads(short["raw_response"])["reason"]) <= 320
        assert short["finish_reason"] == "stop"
        preflight_checks.append("adversarial_schema_and_length_controls")
    if receipt["gates"]["smoke"]:
        smoke_paths = list((exp.directory / "smoke").glob("*.json"))
        assert len(smoke_paths) == 6
        for path in smoke_paths:
            r = json.loads(path.read_text(encoding="utf-8"))
            r["arm"] = path.stem.rsplit("_", 1)[1]
            assert independent_parse(r)[0]
            assert r["request_payload"]["response_format"] == exp.fp["response_formats"][r["arm"]]
            assert r["request_payload"]["reasoning_effort"] == "none"
        preflight_checks.append("six_smoke_records")
    dest = ROOT / exp.config["report_root"] / exp.config["run_id"]
    report = json.loads((dest / "metrics.json").read_text(encoding="utf-8"))
    assert report["record_count"] == len(rows)
    checks = []
    for dataset in ("challenge", "basic"):
        predictions = {}
        for arm in ("A2", "B2"):
            items = [r for r in rows if r["dataset"] == dataset and r["arm"] == arm]
            m = report["datasets"][dataset]["arms"][arm]
            assert m["completed"] == len(items)
            assert m["n"] == len(exp.rows[dataset])
            if len(items) != len(exp.rows[dataset]):
                assert m["accuracy"] is None
                continue
            matrix = {label: {col: 0 for col in (*LABELS, "INVALID")} for label in LABELS}
            predictions[arm] = {}
            for row in items:
                valid, logic, label = independent_parse(row)
                pred = label if valid and label else "INVALID"
                predictions[arm][row["id"]] = (row["gold_label"], pred)
                matrix[row["gold_label"]][pred] += 1
            correct = sum(matrix[label][label] for label in LABELS)
            assert matrix == m["confusion_matrix"]
            assert correct == m["correct"]
            assert m["accuracy"] == correct / len(items)
            f1s = []
            for label in LABELS:
                support = sum(matrix[label].values())
                predicted = sum(matrix[gold][label] for gold in LABELS)
                tp = matrix[label][label]
                assert m["classes"][label]["recall"] == tp / support
                f1s.append(2 * tp / (support + predicted))
            assert abs(m["macro_f1"] - sum(f1s) / 3) < 1e-12
            assert m["nei_to_refutes"] == matrix["NOT ENOUGH INFO"]["REFUTES"]
            assert m["supports_to_nei"] == matrix["SUPPORTS"]["NOT ENOUGH INFO"]
            assert m["refutes_to_nei"] == matrix["REFUTES"]["NOT ENOUGH INFO"]
            checks.append(dataset + "/" + arm)
        if len(predictions) == 2:
            a, b = predictions["A2"], predictions["B2"]
            improved = sorted(k for k in a if a[k][0] != a[k][1] and b[k][0] == b[k][1])
            harmed = sorted(k for k in a if a[k][0] == a[k][1] and b[k][0] != b[k][1])
            p = report["datasets"][dataset]["paired"]["B2-A2"]
            assert p["improved_ids"] == improved and p["harmed_ids"] == harmed
    receipt.update(independent_metric_groups_checked=checks, independent_preflight_checks=preflight_checks,
                   distinct_formal_http_attempts=len(attempt_keys), independent_statistics_passed=True)
    atomic_json(dest / "independent_statistics_audit.json", receipt)
    print("Independent statistics audit passed; complete =", receipt["formal_complete"])


if __name__ == "__main__":
    main()
