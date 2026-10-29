"""Independent inspection of stored payloads; no network or test access."""
import argparse
import json
from collections import Counter

from ..common import ROOT, atomic_json, file_hash
from .experiment import EXPERIMENT, OUTPUT, load_dev, verify
from .inference import digest, messages, parse, schema


def audit(phase, root=ROOT):
    manifest, f = verify(phase, root)
    dev = {(d,r["id"]): r for d in ("basic", "challenge") for r in load_dev(d, root)}
    expected, observed = set(), set()
    problems, counts, models, tokens = [], Counter(), Counter(), 0
    hashes = {}
    for item in manifest["rows"]:
        row = dev[item["dataset"], item["id"]]
        assert all(row[k] == item[k] for k in ("claim", "evidence", "group", "mechanism"))
        for arm in manifest["arms"]:
            p = root / OUTPUT / phase / "records" / item["dataset"] / item["id"] / (arm + ".json")
            expected.add(p)
            if not p.exists():
                continue
            observed.add(p)
            r = json.loads(p.read_text(encoding="utf-8"))
            ident = f"{item['dataset']}/{item['id']}/{arm}"
            if r["record_sha256"] != digest({k:v for k,v in r.items() if k != "record_sha256"}):
                problems.append([ident, "record_hash"])
            payload = r["request_payload"]
            expected_payload = {"model": "qwen/qwen3.8-27b", "temperature": 0, "seed": 42,
                "reasoning_effort": "none", "stream": False,
                "max_completion_tokens": 1024 if arm == "baseline" else f["config"]["candidate_completion_limit"],
                "messages": messages(arm, claim=row["claim"], evidence=row["evidence"], root=root),
                "response_format": schema(arm)}
            if payload != expected_payload:
                problems.append([ident, "exact_input_or_settings"])
            if r["actual_model_id"] != expected_payload["model"] or not r["nonthinking_validation"]["passed"] or r["provider_validation_issues"]:
                problems.append([ident, "model_or_nonthinking"])
            models[r["actual_model_id"]] += 1
            counts["received"] += 1
            counts["invalid"] += parse(arm, r)["label"] == "INVALID"
            counts["truncated"] += r["finish_reason"] == "length"
            tokens += r["usage"]["total_tokens"]
            hashes[p.relative_to(root).as_posix()] = file_hash(p)
    extras = {p for p in (root / OUTPUT / phase / "records").glob("*/*/*.json") if not p.name.endswith(".error.json")} - expected
    problems += [[p.relative_to(root).as_posix(), "unexpected_record"] for p in sorted(extras)]
    result = {"phase": phase, "expected": len(expected), "received": len(observed), "complete": expected == observed,
              "protocol_passed": not problems, "problems": problems, "counts": dict(counts),
              "actual_models": dict(models), "total_tokens": tokens,
              "test_read_by_audit": False, "exact_payload_reconstructed_from_dev_claim_evidence_only": True,
              "raw_file_sha256": hashes}
    atomic_json(root / EXPERIMENT / phase / "audit.json", result)
    print(json.dumps({k:v for k,v in result.items() if k != "raw_file_sha256"}))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", default="scout")
    audit(p.parse_args().phase)
