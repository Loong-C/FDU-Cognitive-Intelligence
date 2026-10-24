"""Independent v5 read-only audit; does not call Groq or reuse its adjudicator."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    # Same artifact serialization, independently specified.
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit(run_id):
    errors, checked, coverage = [], [], {}
    prompt_dir = ROOT / "prompts/v5"
    pm = read(prompt_dir / "manifest.json")
    for name, expected in pm["templates"].items():
        if file_hash(prompt_dir / name) != expected: errors.append("template_hash:" + name)
    if file_hash(prompt_dir / "schemas.json") != pm["schemas_sha256"]: errors.append("schema_hash")
    schemas = read(prompt_dir / "schemas.json")
    mapping = {("WITNESS_VALID", "TARGET_CONTRADICTS_EVIDENCE"): "SUPPORTS",
               ("TARGET_CONTRADICTS_EVIDENCE", "WITNESS_VALID"): "REFUTES",
               ("WITNESS_VALID", "WITNESS_VALID"): "NOT ENOUGH INFO",
               ("TARGET_CONTRADICTS_EVIDENCE", "TARGET_CONTRADICTS_EVIDENCE"): "UNRESOLVED_CONTRADICTION"}
    role_names = {"generate_T": "generator_true", "generate_F": "generator_false", "verify_T": "verifier_true", "verify_F": "verifier_false"}
    for phase in ("smoke", "fresh"):
        directory = ROOT / "outputs/runs" / (run_id + "_" + phase)
        if not (directory / "fingerprint.json").exists():
            coverage[phase] = {"initialized": False}
            continue
        fp = read(directory / "fingerprint.json")
        for name, expected in fp["source_sha256"].items():
            if file_hash(ROOT / name) != expected: errors.append("source_changed:" + name)
        for path in directory.rglob("*.json"):
            r = read(path)
            if not isinstance(r, dict) or "request_payload" not in r: continue
            checked.append(path.relative_to(ROOT).as_posix())
            if digest({k: v for k, v in r.items() if k != "record_sha256"}) != r.get("record_sha256"):
                errors.append("record_integrity:" + str(path))
            if r["run_fingerprint_sha256"] != digest(fp): errors.append("fingerprint:" + str(path))
            p = r["request_payload"]
            for key, value in {"model": "qwen/qwen3.8-27b", "reasoning_effort": "none", "temperature": 0, "seed": 42, "stream": False}.items():
                if p.get(key) != value: errors.append("request_parameters:" + str(path))
            if "tools" in p or "documents" in p: errors.append("external_input:" + str(path))
            if p.get("response_format", {}).get("json_schema", {}).get("strict") is not True and path.name != "control.json":
                errors.append("not_strict:" + str(path))
        if phase == "fresh":
            manifest = read(ROOT / fp["config"]["manifest"])
            if file_hash(ROOT / fp["config"]["manifest"]) != fp["dataset_sha256"]: errors.append("manifest_hash")
            sources = [(d, r) for d, v in manifest["datasets"].items() for r in v["rows"]]
            excluded = set(manifest["excluded_pilot_groups"])
            if any(r["group"] in excluded for _, r in sources): errors.append("pilot_group_leakage")
        else:
            sources = [("synthetic", json.loads(line)) for line in (ROOT / "experiments/005_layered_worlds/synthetic_smoke_cases.jsonl").read_text(encoding="utf-8").splitlines()]
        completed = 0
        for dataset, row in sources:
            base = directory / "records" / digest([dataset, row["id"]])
            nodes = {}
            for stage, role in role_names.items():
                path = base / (stage + ".json")
                if not path.exists(): continue
                r = read(path); nodes[stage] = r
                p = r["request_payload"]
                values = {"evidence": row["evidence"], "claim": row["claim"]}
                deps = {"problem": digest(values)}
                if stage.startswith("verify"):
                    gen_path = base / ("generate_" + stage[-1] + ".json")
                    if not gen_path.exists():
                        errors.append("missing_generator:" + str(path)); continue
                    gen = read(gen_path)
                    values.update(gen["validation"]["parsed"])
                    deps["constructor"] = gen["record_sha256"]
                expected = [{"role": "system", "content": (prompt_dir / (role + "_system.txt")).read_bytes().decode()},
                            {"role": "user", "content": re.sub(r"\{([a-z_]+)\}", lambda m: values[m[1]], (prompt_dir / (role + "_user.txt")).read_bytes().decode())}]
                if p["messages"] != expected: errors.append("message_isolation:" + str(path))
                if r["upstream_sha256"] != deps: errors.append("dependency:" + str(path))
                schema = schemas[pm["schema_choice"][role]]
                if p["response_format"]["json_schema"]["schema"] != schema: errors.append("role_schema:" + str(path))
                if r["validation"]["protocol_valid"]:
                    value = json.loads(r["raw_response"])
                    if set(value) != set(schema["required"]): errors.append("fields:" + str(path))
                    for k, spec in schema["properties"].items():
                        if not isinstance(value.get(k), str) or not value[k].strip(): errors.append("nonempty:" + str(path))
                        elif ("enum" in spec and value[k] not in spec["enum"]) or len(value[k]) > spec.get("maxLength", 10**9): errors.append("schema_value:" + str(path))
            vp = base / "verdict.json"
            if vp.exists():
                completed += 1
                if len(nodes) != 4:
                    errors.append("incomplete_four_calls:" + str(vp)); continue
                decisions = tuple(json.loads(nodes["verify_" + b]["raw_response"])["decision"] for b in ("T", "F"))
                v = read(vp)
                if v["label"] != mapping.get(decisions, "UNRESOLVED_BRANCH"): errors.append("mapping:" + str(vp))
                if v["upstream_sha256"] != {b: nodes["verify_" + b]["record_sha256"] for b in ("T", "F")}:
                    errors.append("verdict_dependency:" + str(vp))
            bp = base / "baseline_A27.json"
            if bp.exists():
                b = read(bp)
                values = {"claim": row["claim"], "evidence": row["evidence"]}
                expected = [{"role": "system", "content": (ROOT / "prompts/v2/A2_system.txt").read_text(encoding="utf-8")},
                            {"role": "user", "content": re.sub(r"\{(claim|evidence)\}", lambda m: values[m[1]], (ROOT / "prompts/v2/A2_user.txt").read_text(encoding="utf-8"))}]
                if b["request_payload"]["messages"] != expected: errors.append("baseline_input:" + str(bp))
        coverage[phase] = {"initialized": True, "planned": len(sources), "four_call_completed": completed}
    snapshot = ROOT / "outputs/worlds_v5_history/baseline.json"
    preserved = 0
    if snapshot.exists():
        for name, expected in read(snapshot)["files"].items():
            if not (ROOT / name).is_file() or file_hash(ROOT / name) != expected: errors.append("historical_file_changed:" + name)
            preserved += 1
    before = read(ROOT / "outputs/worlds_v5_history/quota_before.json")
    after = read(ROOT / "outputs/groq/quota.json")
    if after["attempts"][:len(before["attempts"])] != before["attempts"]: errors.append("historical_ledger_entries_changed")
    return {"passed": not errors, "errors": errors, "checked_response_records": len(checked),
            "checked_records": checked, "coverage": coverage, "historical_files_preserved": preserved,
            "historical_ledger_entries_preserved": len(before["attempts"]),
            "audit_type": "independent code path, same assistant; not external human semantic verification"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="layered_worlds_qwen38_27b_v5_r1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.run_id)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical(result))
    print(json.dumps({k: v for k, v in result.items() if k != "checked_records"}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
