"""Describe observed output lengths without changing frozen validation or labels."""
from collections import Counter, defaultdict
import json
from pathlib import Path

from ab_factcheck.common import atomic_json, file_hash, now
from ab_factcheck.worlds_v5.orchestrator import digest

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/005_layered_worlds"
RUN = ROOT / "outputs/runs/layered_worlds_qwen38_27b_v5_r2_free_fresh"
manifest = json.loads((EXP / "fresh_dev_v5.json").read_text(encoding="utf-8"))
records = []
for dataset, data in manifest["datasets"].items():
    for row in data["rows"]:
        directory = RUN / "records" / digest([dataset, row["id"]])
        for stage in ("generate_T", "generate_F"):
            path = directory / (stage + ".json")
            if not path.exists():
                continue
            rec = json.loads(path.read_text(encoding="utf-8"))
            value = rec["validation"]["parsed"]
            records.append({"dataset": dataset, "id": row["id"], "mechanism": row["mechanism"], "stage": stage,
                "candidate_world_chars": len(value["candidate_world"]), "target_condition_chars": len(value["target_condition"]),
                "request_world_max_length": rec["request_payload"]["response_format"]["json_schema"]["schema"]["properties"]["candidate_world"]["maxLength"],
                "request_max_completion_tokens": rec["request_payload"]["max_completion_tokens"],
                "actual_completion_tokens": rec["usage"]["completion_tokens"], "finish_reason": rec["finish_reason"],
                "raw_response_matches_saved_provider_content": rec["raw_response"] == rec["response_json"]["choices"][0]["message"]["content"],
                "raw_json_chars": len(rec["raw_response"]), "world_tail": value["candidate_world"][-45:],
                "original_quality_flags": rec["validation"]["quality_flags"], "raw_sha256": file_hash(path)})
grouped = defaultdict(list)
for rec in records:
    grouped[rec["stage"]].append(rec)
result = {"generated_at": now(), "method": "post-hoc descriptive observation only; no added API requests, validation changes, prompt tuning or label repair",
    "hypothesis_status": "Repeated 368-character endings are observed. The model/provider cause and relationship to the 384-token setting have NOT been established by a controlled experiment.",
    "schema_compliance_is_not_semantic_completeness": True,
    "by_stage": {stage: {"responses": len(rows), "maximum_world_chars": max(r["candidate_world_chars"] for r in rows),
        "world_length_histogram": dict(Counter(r["candidate_world_chars"] for r in rows)),
        "worlds_at_368_chars": sum(r["candidate_world_chars"] == 368 for r in rows),
        "worlds_at_requested_schema_limit": sum(r["candidate_world_chars"] == r["request_world_max_length"] for r in rows)} for stage,rows in grouped.items()},
    "all_saved_raw_content_matches": all(r["raw_response_matches_saved_provider_content"] for r in records),
    "records": records}
atomic_json(EXP / "resumption_20261026_length_diagnostics.json", result)
print(json.dumps({k:v for k,v in result.items() if k != "records"}, ensure_ascii=True))
