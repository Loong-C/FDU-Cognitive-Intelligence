"""Independently audit v2 raw JSON, labels, metrics, pairing and historical bytes."""

import argparse
from collections import Counter
import copy
import csv
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ab_factcheck.common import atomic_json, file_hash, json_bytes, load_config, now, read_jsonl, sha256
from ab_factcheck.pilot import load_pilot
from ab_factcheck.prompts import PromptSet

ARMS = ("A2", "B2", "C2")
DATASETS = ("challenge", "basic")
LABELS = ("SUPPORTS", "REFUTES", "NOT ENOUGH INFO")
MAPPING = {("POSSIBLE", "IMPOSSIBLE"): "SUPPORTS", ("IMPOSSIBLE", "POSSIBLE"): "REFUTES", ("POSSIBLE", "POSSIBLE"): "NOT ENOUGH INFO"}


def require(value, message):
    if not value: raise ValueError(message)


def compare(actual, expected, location="metric"):
    if isinstance(expected, dict):
        for key, value in expected.items(): compare(actual[key], value, location + "." + key)
    elif isinstance(expected, float):
        require(isinstance(actual, (float, int)) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), location)
    else:
        require(actual == expected, location)


def json_without_duplicates(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON field")
            result[key] = value
        return result
    def bad_constant(value): raise ValueError(value)
    return json.loads(text, object_pairs_hook=pairs, parse_constant=bad_constant)


def independently_parse(row, schema):
    try:
        value = json_without_duplicates(row["raw_response"])
        is_json = True
    except (ValueError, TypeError):
        value, is_json = None, False
    fields = (isinstance(value, dict) and set(value) == set(schema["required"]))
    if fields:
        fields = all(isinstance(value[k], str) and ("enum" not in spec or value[k] in spec["enum"])
                     and len(value[k]) <= spec.get("maxLength", float("inf")) for k, spec in schema["properties"].items())
    protocol = fields and row["finish_reason"] == "stop"
    compare(row, {"json_valid": is_json, "fields_valid": fields, "protocol_valid": protocol, "parsed_object": value})
    label, logic = None, None
    if protocol:
        if row["arm"] == "A2":
            label = value["verdict"]
            require(row["direct_reason"] == value["reason"], "A2 reason differs")
        else:
            label = MAPPING.get((value["true_world"], value["false_world"]))
            logic = label is not None
            compare(row, {"claim_true_world": value["true_world"], "claim_false_world": value["false_world"],
                          "world_reason_true": value["true_reason"], "world_reason_false": value["false_reason"],
                          "derived_label": label or "INVALID_LOGIC"})
    compare(row, {"predicted_label": label, "logic_valid": logic, "parse_status": "ok" if label else "invalid"})
    return label or "INVALID"


def independently_measure(rows):
    matrix = {label: dict.fromkeys((*LABELS, "INVALID"), 0) for label in LABELS}
    for r in rows: matrix[r["gold_label"]][r["audit_prediction"]] += 1
    n = len(rows); correct = sum(matrix[k][k] for k in LABELS)
    invalid = sum(matrix[k]["INVALID"] for k in LABELS)
    classes = {}
    for label in LABELS:
        tp = matrix[label][label]; support = sum(matrix[label].values()); predicted = sum(matrix[g][label] for g in LABELS)
        classes[label] = {"support": support, "predicted_count": predicted, "precision": tp / predicted if predicted else 0.0,
                          "recall": tp / support if support else None, "f1": 2 * tp / (support + predicted) if support else None}
    logic_available = sum(r.get("logic_valid") is not None for r in rows)
    logic_valid = sum(r.get("logic_valid") is True for r in rows)
    result = {"n": n, "correct": correct, "invalid": invalid, "valid": n-invalid, "accuracy": correct/n,
              "invalid_rate": invalid/n, "valid_only_accuracy": correct/(n-invalid) if n!=invalid else None,
              "confusion_matrix": matrix, "classes": classes, "macro_f1": statistics.mean(v["f1"] for v in classes.values() if v["f1"] is not None),
              "nei_to_refutes": matrix["NOT ENOUGH INFO"]["REFUTES"],
              "nei_to_refutes_rate": matrix["NOT ENOUGH INFO"]["REFUTES"] / sum(matrix["NOT ENOUGH INFO"].values()) if sum(matrix["NOT ENOUGH INFO"].values()) else None,
              "supports_to_nei": matrix["SUPPORTS"]["NOT ENOUGH INFO"], "refutes_to_nei": matrix["REFUTES"]["NOT ENOUGH INFO"],
              "truncated_count": sum(r["finish_reason"] == "length" for r in rows),
              "logic_available_count": logic_available, "logic_valid_count": logic_valid,
              "logic_valid_rate": logic_valid/logic_available if logic_available else None,
              "latency_mean_seconds": statistics.mean(r["latency_seconds"] for r in rows),
              "latency_median_seconds": statistics.median(r["latency_seconds"] for r in rows),
              "mean_completion_tokens": statistics.mean(r["usage"]["completion_tokens"] for r in rows)}
    for key in ("json_valid", "fields_valid", "protocol_valid"):
        result[key+"_count"] = sum(r.get(key) is True for r in rows)
        result[key+"_rate"] = result[key+"_count"]/n
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/experiment_v2.json")
    args = parser.parse_args(); config = load_config(args.config)
    run = ROOT / config["output_root"] / config["run_id"]
    reports = ROOT / config["report_root"] / config["run_id"]
    fingerprint = json.loads((run / "fingerprint.json").read_text(encoding="utf-8"))
    metrics = json.loads((reports / "metrics.json").read_text(encoding="utf-8"))
    environment = json.loads((run / "environment.json").read_text(encoding="utf-8"))
    baseline = json.loads((ROOT / "experiments/002_constrained_output/historical_integrity.json").read_text(encoding="utf-8"))
    for name, expected in baseline["sha256"].items(): require(file_hash(ROOT/name) == expected, "Historical file changed: " + name)
    require(fingerprint["configuration"] == config, "Configuration changed")
    require(file_hash(run/"fingerprint.json") == metrics["fingerprint_sha256"], "Report fingerprint mismatch")
    require(file_hash(ROOT/config["model"]["file"]) == fingerprint["model_sha256"], "Model changed")
    for name, expected in fingerprint["inference_source_sha256"].items():
        require(file_hash(ROOT/"src/ab_factcheck"/name) == expected, "Inference code changed: " + name)
        committed = subprocess.check_output(["git", "show", "2396ab8:src/ab_factcheck/" + name], cwd=ROOT)
        require(sha256(committed) == expected, "Frozen inference commit differs: " + name)
    old = ROOT/config["output_root"]/config["historical_run_id"]
    old_fingerprint = json.loads((old/"fingerprint.json").read_text(encoding="utf-8"))
    for name, expected in old_fingerprint["inference_source_sha256"].items():
        data = subprocess.check_output(["git", "show", baseline["historical_inference_commit"] + ":src/ab_factcheck/" + name], cwd=ROOT)
        require(sha256(data) == expected, "Historical source cannot reproduce its fingerprint")
    prompts = PromptSet(ROOT/config["prompts_dir"])
    require(prompts.hashes == fingerprint["prompts"], "Prompt mismatch")
    collected, conditions, changed_expected = [], {}, {}
    for dataset in DATASETS:
        rows = read_jsonl(run/f"{dataset}.jsonl"); source_rows = load_pilot(config,dataset); source = {r["id"]:r for r in source_rows}
        reference = config["pilot_reference"][dataset]
        require(file_hash(ROOT/config["pilot_dir"]/f"{dataset}_manifest.json") == reference["manifest_sha256"], "Pilot manifest changed")
        require(sha256(json_bytes([r["id"] for r in source_rows])) == reference["ordered_ids_sha256"], "Pilot order changed")
        old_order = json.loads((old/f"expected_{dataset}.json").read_text(encoding="utf-8"))["ids"]
        require(old_order == [r["id"] for r in source_rows], "Not the v1 executed order")
        require(len(rows) == 3*reference["n"] and len({(r["arm"],r["id"]) for r in rows}) == len(rows), "Missing/duplicate records")
        require(file_hash(run/f"{dataset}.jsonl") == metrics["source_jsonl_sha256"][dataset], "Report source changed")
        for r in rows:
            require(r["status"] == "completed", "Incomplete/failed run; inspect before claiming a completed audit")
            require(r["run_id"] == config["run_id"] and r["dataset"] == dataset and r["run_fingerprint_sha256"] == metrics["fingerprint_sha256"], "Wrong result provenance")
            original = source[r["id"]]
            compare(r, {"gold_label": original["label"], "group": original["group"], "mechanism": original["mechanism"]})
            path = run/"records"/dataset/r["arm"]/(sha256(r["id"].encode())+".json")
            require(json.loads(path.read_text(encoding="utf-8")) == r, "Atomic record/JSONL mismatch")
            request = r["request_payload"]; schema = fingerprint["response_formats"][r["arm"]]
            require(request["response_format"] == schema and r["effective_request_parameters"] == {k:v for k,v in request.items() if k!="messages"}, "Request parameters mismatch")
            compare(request, {key:config["model"][key] for key in ("temperature","seed","max_tokens","stream")})
            require(request["cache_prompt"] is False and request["model"] == fingerprint["model_id"], "Wrong model/cache")
            require(r["model_sha256"] == fingerprint["model_sha256"], "Wrong model hash")
            messages = prompts.render(r["arm"],claim=original["claim"],evidence=original["evidence"])
            require(request["messages"] == messages and r["messages_sha256"] == sha256(json_bytes(messages)), "Metadata leaked or input changed")
            response = r["response_json"]; choice=response["choices"][0]
            require(choice["message"]["content"] == r["raw_response"] and choice["finish_reason"] == r["finish_reason"] and response["usage"] == r["usage"], "Raw response changed")
            require(r["usage"]["prompt_tokens"] == r["preflight_prompt_tokens"], "Tokenizer mismatch")
            require(r["preflight_prompt_tokens"]+1024 <= 8192 and r["usage"]["completion_tokens"] <=1024, "Token budget exceeded")
            require(r["usage"]["prompt_tokens_details"]["cached_tokens"] == 0, "Prompt cached")
            r["audit_prediction"] = independently_parse(r,schema["json_schema"]["schema"])
        by_arm = {arm:[r for r in rows if r["arm"]==arm] for arm in ARMS}
        for arm, values in by_arm.items():
            require([r["id"] for r in values] == old_order, "Arms differ in ID/order")
            measured = independently_measure(values)
            compare(metrics["datasets"][dataset]["arms"][arm],measured, dataset+"/"+arm)
            conditions[dataset+"/"+arm] = {"records":len(values),"valid":measured["valid"],"correct":measured["correct"],
                "prompt_tokens":sum(r["usage"]["prompt_tokens"] for r in values),"completion_tokens":sum(r["usage"]["completion_tokens"] for r in values),
                "max_completion_tokens":max(r["usage"]["completion_tokens"] for r in values),"reason_length_bound_records":sum(any(len(r["parsed_object"].get(k,""))==320 for k in ("reason","true_reason","false_reason")) for r in values)}
            for mechanism in {r["mechanism"] for r in values}:
                compare(metrics["datasets"][dataset]["mechanisms"][mechanism][arm],independently_measure([r for r in values if r["mechanism"]==mechanism]))
        for before,after in (("A2","B2"),("B2","C2"),("A2","C2")):
            a={r["id"]:r for r in by_arm[before]}; b={r["id"]:r for r in by_arm[after]}
            correct_a={i for i in a if a[i]["audit_prediction"]==a[i]["gold_label"]}; correct_b={i for i in b if b[i]["audit_prediction"]==b[i]["gold_label"]}
            improved=sorted(correct_b-correct_a); harmed=sorted(correct_a-correct_b)
            pair=metrics["datasets"][dataset]["paired"][after+"-"+before]
            candidates=sorted(i for i in a if a[i]["gold_label"]=="NOT ENOUGH INFO" and a[i]["audit_prediction"]=="REFUTES")
            compare(pair,{"n":len(a),"improved_ids":improved,"harmed_ids":harmed,"improved":len(improved),"harmed":len(harmed),"accuracy_delta":(len(improved)-len(harmed))/len(a),
                          "nei_refuted_before_ids":candidates,"nei_refutes_corrected_ids":sorted(i for i in candidates if b[i]["audit_prediction"]=="NOT ENOUGH INFO"),
                          "supports_correct_to_nei_ids":sorted(i for i in correct_a if a[i]["gold_label"]=="SUPPORTS" and b[i]["audit_prediction"]=="NOT ENOUGH INFO"),
                          "refutes_correct_to_nei_ids":sorted(i for i in correct_a if a[i]["gold_label"]=="REFUTES" and b[i]["audit_prediction"]=="NOT ENOUGH INFO")})
            for i in a:
                if a[i]["audit_prediction"] != b[i]["audit_prediction"]:
                    changed_expected[(dataset,after+"-"+before,i)] = (a[i]["audit_prediction"],b[i]["audit_prediction"],"improved" if i in improved else "harmed" if i in harmed else "changed_but_both_wrong")
        collected.extend(rows)
    with (reports/"changed_predictions.csv").open(encoding="utf-8-sig",newline="") as f:
        changed=list(csv.DictReader(f))
    require(len(changed)==len(changed_expected),"Wrong changed CSV count")
    for r in changed: require((r["before"],r["after"],r["direction"]) == changed_expected[(r["dataset"],r["comparison"],r["id"])],"Changed CSV mismatch")
    with (reports/"predictions.csv").open(encoding="utf-8-sig",newline="") as f: csv_rows=list(csv.DictReader(f))
    require(len(csv_rows)==441 and len({(r["dataset"],r["arm"],r["id"]) for r in csv_rows})==441,"Wrong prediction CSV count")
    lookup={(r["dataset"],r["arm"],r["id"]):r for r in collected}
    for c in csv_rows:
        r=lookup[(c["dataset"],c["arm"],c["id"])]
        for key in ("gold_label","predicted_label","parse_status","claim_true_world","claim_false_world","derived_label"):
            require(c[key] == ("" if r.get(key) is None else str(r[key])),"Prediction CSV mismatch")
    require(not (run/"run.lock").exists() and not list((run/"records").rglob("*.tmp")),"Run not finalized")
    require(len(list((run/"records").glob("*/*/*.json")))==441,"Unexpected atomic records")
    expected_order=[f"{d}/{a}" for a in ARMS for d in DATASETS]
    require(metrics["observed_arm_start_order"]==expected_order,"Wrong run order")
    smoke=ROOT/config["output_root"]/(config["run_id"]+"_smoke")
    smoke_fingerprint=json.loads((smoke/"fingerprint.json").read_text(encoding="utf-8"))
    expected_smoke_fingerprint=copy.deepcopy(fingerprint)
    expected_smoke_fingerprint["configuration"]["run_id"]+="_smoke"
    require(smoke_fingerprint==expected_smoke_fingerprint,"Smoke fingerprint differs")
    smoke_rows=read_jsonl(smoke/"synthetic.jsonl")
    smoke_gold={"smoke_support":"SUPPORTS","smoke_refute":"REFUTES","smoke_nei":"NOT ENOUGH INFO"}
    require(len(smoke_rows)==9 and {(r["arm"],r["id"]) for r in smoke_rows}=={(a,i) for a in ARMS for i in smoke_gold},"Incomplete smoke")
    for r in smoke_rows:
        require(r["status"]=="completed" and r["gold_label"]==smoke_gold[r["id"]],"Invalid smoke provenance")
        require(r["run_fingerprint_sha256"]==file_hash(smoke/"fingerprint.json"),"Wrong smoke fingerprint")
        schema=fingerprint["response_formats"][r["arm"]]
        require(r["request_payload"]["response_format"]==schema,"Wrong smoke schema")
        require(independently_parse(r,schema["json_schema"]["schema"])!="INVALID","Smoke invalid")
        atomic=smoke/"records/synthetic"/r["arm"]/(sha256(r["id"].encode())+".json")
        require(json.loads(atomic.read_text(encoding="utf-8"))==r,"Smoke atomic export mismatch")
    gate={"passed":True,"smoke_records":9,"constraint_probe_sha256":file_hash(smoke/"constraint_probe.json"),"smoke_jsonl_sha256":file_hash(smoke/"synthetic.jsonl")}
    require(json.loads((run/"smoke_gate.json").read_text(encoding="utf-8"))==gate,"Gate receipt differs")
    probe=json.loads((smoke/"constraint_probe.json").read_text(encoding="utf-8"))
    require(len(probe["records"])==5 and all(r.get("valid",True) for r in probe["records"]),"Probe incomplete")
    require(probe["passed"] and probe["fingerprint_sha256"]==file_hash(smoke/"fingerprint.json"),"Wrong probe provenance")
    controls={p["condition"]:p["response"] for p in probe["records"]}
    require(controls["unconstrained_control"]["raw_response"].strip()=="NOT_JSON","Non-JSON control failed")
    require(len(json_without_duplicates(controls["length_unconstrained"]["raw_response"])["reason"])>16,"Length control failed")
    for p in probe["records"]:
        response=p["response"]; fmt=response["request_payload"].get("response_format")
        if fmt:
            value=json_without_duplicates(response["raw_response"]); schema=fmt["json_schema"]["schema"]
            require(set(value)==set(schema["required"]),"Probe required fields failed")
            for key,spec in schema["properties"].items():
                require(isinstance(value[key],str) and ("enum" not in spec or value[key] in spec["enum"]) and len(value[key])<=spec.get("maxLength",float("inf")),"Probe constraint failed")
    old_partial=ROOT/"outputs/runs/pilot_qwen3_4b_q4_struct_v2_r1"
    partial=list((old_partial/"records").glob("*/*/*.json")); require(len(partial)==165,"Partial run was changed")
    log=Path(environment["startup"]["log_directory"])/"stderr.log"
    generations=log.read_text(encoding="utf-8",errors="replace").count("new prompt, n_ctx_slot =")
    expected_generations=3+3+9+165+5+9+441
    require(generations==expected_generations,f"Unexpected backend generation count: {generations}")
    audit={"passed":True,"audited_at":now(),"run_id":config["run_id"],"formal_records":441,"smoke_records":9,"successful_constraint_probes":5,
           "preserved_historical_files":len(baseline["sha256"]),"preserved_partial_records":165,"server_generation_count":generations,
           "maximum_prompt_tokens":max(r["preflight_prompt_tokens"] for r in collected),"maximum_completion_tokens":max(r["usage"]["completion_tokens"] for r in collected),
           "request_attempt_counts":dict(Counter(str(r["completion_request_attempts"]) for r in collected)),"conditions":conditions,"observed_order":expected_order,
           "source_jsonl_sha256":metrics["source_jsonl_sha256"],"fingerprint_sha256":metrics["fingerprint_sha256"],"smoke_gate":gate,
           "inference_commit":subprocess.check_output(["git","rev-parse","2396ab8"],cwd=ROOT,text=True).strip(),
           "audit_and_report_source_sha256":{name:file_hash(ROOT/name) for name in ("scripts/audit_structured_run.py","src/ab_factcheck/metrics.py","src/ab_factcheck/reporting.py","src/ab_factcheck/reporting_v2.py")}}
    atomic_json(reports/"execution_audit.json",audit)
    atomic_json(reports/"environment_summary.json",{k:environment[k] for k in ("captured_at","python","platform","gpu","dependencies","backend_version","model_sha256","seed_note")}|{"backend_identity":fingerprint["backend_identity"],"model_id":fingerprint["model_id"],"chat_template":environment["runtime"]["props"]["chat_template"],"chat_template_sha256":fingerprint["chat_template_sha256"]})
    atomic_json(reports/"constraint_validation.json",{"passed":probe["passed"],"probe_sha256":file_hash(smoke/"constraint_probe.json"),"records":[{"condition":p["condition"],"request":p["response"]["request_payload"],"raw_response":p["response"]["raw_response"],"finish_reason":p["response"]["finish_reason"]} for p in probe["records"]]})
    print(json.dumps({"passed":True,"formal_records":441,"historical_files_unchanged":len(baseline["sha256"]),"backend_generations":generations},ensure_ascii=False))


if __name__=="__main__": main()
