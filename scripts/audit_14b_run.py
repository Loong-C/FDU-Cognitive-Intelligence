"""Independent raw-response recomputation; does not use production metrics/parser."""

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ab_factcheck.common import atomic_json, file_hash, json_bytes, load_config, now, read_jsonl, sha256
# These are the separate round-two auditor's implementation, not inference code.
from audit_structured_run import compare, independently_parse, json_without_duplicates, require

LABELS = ("SUPPORTS", "REFUTES", "NOT ENOUGH INFO")
ARMS = ("A2", "B2")


def measure(rows):
    matrix = {g: dict.fromkeys((*LABELS, "INVALID"), 0) for g in LABELS}
    for row in rows:
        matrix[row["gold_label"]][row["audit_prediction"]] += 1
    n = len(rows)
    right = sum(matrix[g][g] for g in LABELS)
    invalid = sum(matrix[g]["INVALID"] for g in LABELS)
    classes = {}
    for label in LABELS:
        tp = matrix[label][label]; support = sum(matrix[label].values()); predicted = sum(matrix[g][label] for g in LABELS)
        classes[label] = dict(support=support, predicted_count=predicted, precision=tp/predicted if predicted else 0.,
                              recall=tp/support if support else None, f1=2*tp/(support+predicted) if support else None)
    result = dict(n=n, correct=right, invalid=invalid, valid=n-invalid, accuracy=right/n, invalid_rate=invalid/n,
                  valid_only_accuracy=right/(n-invalid) if n>invalid else None, classes=classes, confusion_matrix=matrix,
                  macro_f1=statistics.mean(v["f1"] for v in classes.values() if v["f1"] is not None),
                  nei_to_refutes=matrix[LABELS[2]][LABELS[1]], supports_to_nei=matrix[LABELS[0]][LABELS[2]], refutes_to_nei=matrix[LABELS[1]][LABELS[2]],
                  both_impossible_count=sum(r.get("claim_true_world")==r.get("claim_false_world")=="IMPOSSIBLE" for r in rows),
                  truncated_count=sum(r.get("finish_reason")=="length" for r in rows),
                  request_failed_count=sum(r["status"]=="request_failed" for r in rows))
    for field in ("json_valid", "fields_valid", "protocol_valid"):
        result[field+"_count"] = sum(r.get(field) is True for r in rows)
        result[field+"_rate"] = result[field+"_count"]/n
    latencies = [r["latency_seconds"] for r in rows if isinstance(r.get("latency_seconds"), (int,float))]
    tokens = [r.get("usage",{}).get("completion_tokens") for r in rows]
    tokens = [v for v in tokens if isinstance(v,(int,float))]
    available = sum(r.get("logic_valid") is not None for r in rows)
    logic_valid = sum(r.get("logic_valid") is True for r in rows)
    result.update(latency_mean_seconds=statistics.mean(latencies) if latencies else None,
                  latency_median_seconds=statistics.median(latencies) if latencies else None,
                  mean_completion_tokens=statistics.mean(tokens) if tokens else None,
                  logic_available_count=available, logic_valid_count=logic_valid,
                  logic_valid_rate=logic_valid/available if available else None)
    reason_limits = 0
    for row in rows:
        value = row.get("parsed_object")
        if row.get("protocol_valid") and isinstance(value, dict) and any(len(value.get(key, ""))==320 for key in ("reason", "true_reason", "false_reason")):
            reason_limits += 1
    result["reason_at_length_limit_count"] = reason_limits
    return result


def cost(rows):
    completed=[r for r in rows if r.get("status")=="completed"]
    times=sorted(r["latency_seconds"] for r in completed)
    tokens=sum(r.get("usage",{}).get("completion_tokens",0) for r in completed)
    rates=[r["response_json"]["timings"]["predicted_per_second"] for r in completed if isinstance(r.get("response_json",{}).get("timings",{}).get("predicted_per_second"),(int,float))]
    return dict(completed_requests=len(completed),request_seconds=sum(times),completion_tokens=tokens,
                end_to_end_completion_tokens_per_second=tokens/sum(times) if sum(times) else None,
                backend_decode_tokens_per_second_mean=statistics.mean(rates) if rates else None,
                latency_p50_seconds=statistics.median(times) if times else None,
                latency_p95_seconds=times[math.ceil(len(times)*.95)-1] if times else None)


def pair(before, after):
    left, right = {r["id"]: r for r in before}, {r["id"]: r for r in after}
    require(left.keys()==right.keys() and len(left)==len(before)==len(after), "Unpaired IDs")
    improved, harmed = [], []
    for key in sorted(left):
        a, b = left[key], right[key]
        require((a["group"],a["gold_label"])==(b["group"],b["gold_label"]), "Paired metadata differs")
        ca, cb = a["audit_prediction"]==a["gold_label"], b["audit_prediction"]==b["gold_label"]
        if ca != cb: (improved if cb else harmed).append(key)
    return dict(n=len(left), improved=len(improved), harmed=len(harmed), improved_ids=improved, harmed_ids=harmed,
                accuracy_delta=(len(improved)-len(harmed))/len(left))


def reasoning_clear(response):
    for choice in response.get("choices", []):
        msg = choice["message"]
        require(not msg.get("reasoning_content") and not msg.get("reasoning"), "Unexpected reasoning field")
        text = re.sub(r"<think>\s*</think>", "", msg.get("content") or "", flags=re.I)
        require(not re.search(r"</?think\b", text, re.I), "Nonempty/unclosed thinking")
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("reasoning_tokens", "thinking_tokens"): require(item in (None,0), "Hidden reasoning tokens")
                walk(item)
        if isinstance(value, list):
            for item in value: walk(item)
    walk(response.get("usage", {}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT/"configs/experiment_14b_v3.json")
    parser.add_argument("--integrity-only", action="store_true")
    args = parser.parse_args(); config = load_config(args.config)
    baseline = json.loads((ROOT/"experiments/003_model_scaling_14b/historical_baseline.json").read_text(encoding="utf-8"))
    for name, expected in baseline["sha256"].items():
        require(file_hash(ROOT/name)==expected, "Historical bytes changed: "+name)
    report_dir = ROOT/config["report_root"]/config["run_id"]
    receipt = dict(audited_at=now(), historical_files_unchanged=len(baseline["sha256"]), experiment_completed=False,
                   audit_method="separate Python process and independent parser/metric implementation; not an external human audit")
    if args.integrity_only:
        receipt["scope"]="historical_integrity_only"
        atomic_json(ROOT/"experiments/003_model_scaling_14b/integrity_audit.json", receipt)
        print(json.dumps(receipt,indent=2)); return
    run = ROOT/config["output_root"]/config["run_id"]
    fingerprint = json.loads((run/"fingerprint.json").read_text(encoding="utf-8"))
    metrics = json.loads((report_dir/"metrics.json").read_text(encoding="utf-8"))
    upgrade = json.loads((report_dir/"upgrade_comparison.json").read_text(encoding="utf-8"))
    require(fingerprint["configuration"]==config, "Configuration mismatch")
    require(file_hash(run/"fingerprint.json")==metrics["fingerprint_sha256"], "Report fingerprint mismatch")
    require(file_hash(ROOT/config["model"]["file"])==config["model"]["sha256"], "Model hash mismatch")
    require((ROOT/config["model"]["file"]).stat().st_size==config["model"]["size_bytes"], "Model length mismatch")
    for name, expected in fingerprint["inference_source_sha256"].items():
        require(file_hash(ROOT/"src/ab_factcheck"/name)==expected, "Inference source changed: "+name)
    env = json.loads((run/"environment.json").read_text(encoding="utf-8"))
    backend = fingerprint["backend_identity"]
    exe = Path(env["startup"]["executable"])
    require(file_hash(exe)==backend["executable_sha256"], "Backend executable changed")
    for name, expected in backend["library_sha256"].items():
        require(file_hash(exe.parent/name)==expected, "Backend DLL changed")
    manifest = json.loads((ROOT/config["prompts_dir"]/"manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["sha256"].items():
        require(file_hash(ROOT/config["prompts_dir"]/name)==expected, "Frozen prompt changed")
    collected=[]
    for dataset in ("challenge","basic"):
        pilot_manifest = ROOT/config["pilot_dir"]/f"{dataset}_manifest.json"
        require(file_hash(pilot_manifest)==config["pilot_reference"][dataset]["manifest_sha256"], "Pilot changed")
        pm=json.loads(pilot_manifest.read_text(encoding="utf-8"))
        dev=ROOT/"data/splits"/config["split_version"]/dataset/"dev.jsonl"
        require(file_hash(dev)==pm["dev_sha256"], "Dev changed")
        ids=sorted(r["id"] for r in pm["assignments"] if r["is_pilot"])
        require(sha256(json_bytes(ids))==config["pilot_reference"][dataset]["ordered_ids_sha256"], "Pilot ID order changed")
        source={r["id"]:r for r in read_jsonl(dev) if r["id"] in ids}
        rows=read_jsonl(run/f"{dataset}.jsonl")
        require([(r["arm"],r["id"]) for r in rows]==[(a,i) for a in ARMS for i in ids], "Formal IDs/order/count mismatch")
        require(file_hash(run/f"{dataset}.jsonl")==metrics["source_jsonl_sha256"][dataset], "Report source mismatch")
        for row in rows:
            require(row["status"] in ("completed","request_failed"), "Unrun row is not a result")
            require(row["run_fingerprint_sha256"]==metrics["fingerprint_sha256"], "Record fingerprint mismatch")
            src=source[row["id"]]
            for field,original in (("gold_label","label"),("group","group"),("mechanism","mechanism")):
                require(row[field]==src[original], "Metadata mismatch")
            record_path=run/"records"/dataset/row["arm"]/(sha256(row["id"].encode())+".json")
            require(json.loads(record_path.read_text(encoding="utf-8"))==row, "Atomic record/export mismatch")
            fmt=manifest["response_formats"][row["arm"]]
            require(fmt==fingerprint["response_formats"][row["arm"]], "Schema changed")
            if row["status"]=="completed":
                request=row["request_payload"]
                user=(ROOT/config["prompts_dir"]/f"{row['arm']}_user.txt").read_text(encoding="utf-8")
                user=re.sub(r"\{(claim|evidence)\}", lambda m:src[m[1]], user)
                messages=[{"role":"system","content":(ROOT/config["prompts_dir"]/f"{row['arm']}_system.txt").read_text(encoding="utf-8")},{"role":"user","content":user}]
                require(request["messages"]==messages and row["messages_sha256"]==sha256(json_bytes(messages)), "Input leakage or prompt mutation")
                require(request["response_format"]==fmt and request["cache_prompt"] is False, "Wrong schema/cache setting")
                for key in ("temperature","seed","max_tokens","stream","chat_template_kwargs","reasoning_format"):
                    require(request[key]==config["model"][key], "Sampling/template mismatch: "+key)
                require(row["applied_template"]["options"]=={k:config["model"][k] for k in ("chat_template_kwargs","reasoning_format")}, "Token template mismatch")
                require(row["response_json"]["choices"][0]["message"]["content"]==row["raw_response"], "Raw response altered")
                reasoning_clear(row["response_json"])
                require(row["usage"]["prompt_tokens"]==row["preflight_prompt_tokens"], "Prompt count differs")
                require(row["usage"].get("prompt_tokens_details",{}).get("cached_tokens",0)==0,"Prompt cache reused")
                require(row["preflight_prompt_tokens"]+1024<=config["model"]["context_tokens"], "Input budget overflow")
                row["audit_prediction"]=independently_parse(row,fmt["json_schema"]["schema"])
            else:
                require(row.get("predicted_label") is None, "Failed request got a label")
                row["audit_prediction"]="INVALID"
        arms={a:[r for r in rows if r["arm"]==a] for a in ARMS}
        for a in ARMS: compare(metrics["datasets"][dataset]["arms"][a],measure(arms[a]))
        for mechanism, values in metrics["datasets"][dataset]["mechanisms"].items():
            for a in ARMS:compare(values[a],measure([r for r in arms[a] if r["mechanism"]==mechanism]))
        compare(metrics["datasets"][dataset]["paired"]["B2-A2"],pair(arms["A2"],arms["B2"]))
        old=read_jsonl(ROOT/"outputs/runs"/config["historical_run_id"]/f"{dataset}.jsonl")
        old_arms={a:[r for r in old if r["arm"]==a] for a in ARMS}
        for a in ARMS:
            for row in old_arms[a]: row["audit_prediction"]=independently_parse(row,manifest["response_formats"][a]["json_schema"]["schema"])
        pairs={"A14-A2":pair(old_arms["A2"],arms["A2"]),"B14-B2":pair(old_arms["B2"],arms["B2"]),"B14-A14":pair(arms["A2"],arms["B2"]),"B2-A2":pair(old_arms["A2"],old_arms["B2"])}
        for name,value in pairs.items():compare(upgrade["comparisons"][dataset][name],value)
        for name, group in (("A2",old_arms["A2"]),("B2",old_arms["B2"]),("A14",arms["A2"]),("B14",arms["B2"])):
            compare(upgrade["performance"][dataset][name],cost(group))
        compare(upgrade["comparisons"][dataset]["descriptive_interaction_accuracy_delta"],pairs["B14-A14"]["accuracy_delta"]-pairs["B2-A2"]["accuracy_delta"])
        collected.extend(rows)
    require(len(collected)==294,"Expected 294 formal records")
    for group in upgrade["groups"]:
        compare(group,measure([r for r in collected if (r["dataset"],r["arm"],r["group"])==(group["dataset"],group["arm"],group["group"])]))
    csv_rows=list(csv.DictReader((report_dir/"predictions.csv").open(encoding="utf-8-sig",newline="")))
    require([(r["dataset"],r["arm"],r["id"]) for r in csv_rows]==[(r["dataset"],r["arm"],r["id"]) for r in collected],"Prediction CSV order/count differs")
    for exported, original in zip(csv_rows,collected):
        for key in ("gold_label","group","mechanism","predicted_label","parse_status","world_reason_true","world_reason_false","direct_reason"):
            require(exported[key]==str(original.get(key) or ""),"Prediction CSV content differs: "+key)
    completions=[r["response_json"]["id"] for r in collected if r["status"]=="completed"]
    require(len(completions)==len(set(completions)),"Repeated completion ID")
    observed=sorted(collected,key=lambda r:r["created_at"])
    require([(r["dataset"],r["arm"],r["id"]) for r in observed]==[(r["dataset"],r["arm"],r["id"]) for r in collected],"Formal execution order changed")
    gate=json.loads((run/"technical_gate.json").read_text(encoding="utf-8"))
    smoke=run.with_name(run.name+"_smoke")
    require(gate["passed"] and file_hash(smoke/"nonthinking_probe.json")==gate["nonthinking_probe_sha256"],"Nonthinking gate mismatch")
    probe=json.loads((smoke/"nonthinking_probe.json").read_text(encoding="utf-8"))
    require(probe["passed"] and probe["disabled_template"]["text"]!=probe["enabled_template"]["text"],"Ignored thinking switch")
    reasoning_clear(probe["response"]["response_json"])
    smoke_rows=read_jsonl(smoke/"synthetic.jsonl")
    require(len(smoke_rows)==6 and {(r["arm"],r["id"]) for r in smoke_rows}=={(a,i) for a in ARMS for i in ("smoke_support","smoke_refute","smoke_nei")},"Incomplete synthetic smoke")
    for row in smoke_rows:
        reasoning_clear(row["response_json"])
        independently_parse(row,manifest["response_formats"][row["arm"]]["json_schema"]["schema"])
        require(row["protocol_valid"],"Smoke protocol failure")
        require(row["response_json"]["id"] not in completions,"Smoke output reused as formal")
    constraint=json.loads((smoke/"constraint_probe.json").read_text(encoding="utf-8"))
    require(constraint["passed"] and len(constraint["records"])==5,"Constraint probe incomplete")
    for item in constraint["records"]:
        response=item["response"];reasoning_clear(response["response_json"])
        if item["condition"]=="unconstrained_control":require(response["raw_response"].strip()=="NOT_JSON","Unconstrained control failed")
        elif item["condition"]=="length_unconstrained":require(len(json_without_duplicates(response["raw_response"])["reason"])>16,"Length control failed")
        else:
            schema=response["request_payload"]["response_format"]["json_schema"]["schema"]
            value=json_without_duplicates(response["raw_response"])
            require(set(value)==set(schema["required"]),"Probe required fields not constrained")
            for key,spec in schema["properties"].items():
                require(isinstance(value[key],str) and ("enum" not in spec or value[key] in spec["enum"]) and len(value[key])<=spec.get("maxLength",float("inf")),"Probe field constraint failed")
    for name in ("disabled_template","enabled_template"):
        require(sha256(probe[name]["text"].encode())==probe[name]["sha256"],"Template digest mismatch")
    require(file_hash(run/"context_preflight.json")==gate["context_preflight_sha256"],"Context receipt changed")
    require(file_hash(run.with_name(run.name+"_performance")/"receipt.json")==gate["performance_receipt_sha256"],"Performance receipt changed")
    telemetry=Path(env["startup"]["log_directory"])/"resources.jsonl"
    require(file_hash(telemetry)==upgrade["hardware"]["telemetry_sha256"],"Telemetry changed after report; stop own server then regenerate report")
    samples=read_jsonl(telemetry)
    compare(upgrade["hardware"]["sampled_resources"],dict(samples=len(samples),gpu_peak_used_mib=max(s["gpus"][0]["used_mib"] for s in samples),
            gpu_min_free_mib=min(s["gpus"][0]["free_mib"] for s in samples),minimum_available_ram_gib=min(s["available_ram_bytes"] for s in samples)/1024**3))
    review=list(csv.DictReader((report_dir/"reason_consistency_review.csv").open(encoding="utf-8-sig",newline="")))
    expected_review=[(d,r["id"]) for d in ("challenge","basic") for label in LABELS for r in sorted((r for r in collected if r["dataset"]==d and r["arm"]=="B2" and r["gold_label"]==label),key=lambda r:r["id"])[:3]]
    require([(r["dataset"],r["id"]) for r in review]==expected_review,"Review selection changed")
    receipt.update(passed=True,experiment_completed=True,formal_records=len(collected),semantic_review_status=Counter(r["semantic_review_status"] for r in review),
                   fingerprint_sha256=metrics["fingerprint_sha256"],source_jsonl_sha256=metrics["source_jsonl_sha256"],audit_source_sha256=file_hash(Path(__file__)))
    atomic_json(report_dir/"execution_audit.json",receipt)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
