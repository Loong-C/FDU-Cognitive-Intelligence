"""Separate costs and cohorts for the authorized 2026-10-26 resumption."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import runpy

from ab_factcheck.common import atomic_json, now
from ab_factcheck.worlds_v5.evaluation import metrics, paired
from ab_factcheck.worlds_v5.orchestrator import digest

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/005_layered_worlds"
RUN = "layered_worlds_qwen38_27b_v5_r2_free"
STAGES = ("baseline_A27", "generate_T", "generate_F", "verify_T", "verify_F")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def summarize():
    helpers = runpy.run_path(str(ROOT / "scripts/summarize_worlds_v5_continuation.py"))
    cumulative = helpers["summary"]()
    snapshot = read(ROOT / "outputs/worlds_v5_history/before_resume_20261026.json")
    ledger = read(ROOT / "outputs/groq/quota.json")
    attempts = ledger["attempts"][snapshot["ledger_prefix_attempts"]:]
    received = [a for a in attempts if a["status"] == "received"]
    old_dirs = {Path(p).parent.name for p in snapshot["raw_files_sha256"] if p.endswith("/verdict.json") and "_fresh/" in p}
    complete = [r for r in cumulative["rows"] if r["A27"] is not None and r["V5"] is not None]
    old = [r for r in complete if digest([r["dataset"], r["id"]]) in old_dirs]
    added = [r for r in complete if digest([r["dataset"], r["id"]]) not in old_dirs]
    cross_date = []
    node_dates = {}
    for row in complete:
        directory = ROOT / "outputs/runs" / (RUN + "_fresh") / "records" / digest([row["dataset"], row["id"]])
        dates = {stage: datetime.fromisoformat(read(directory / (stage + ".json"))["requested_at"]).astimezone(timezone(timedelta(hours=8))).date().isoformat() for stage in STAGES}
        node_dates[row["id"]] = dates
        if len(set(dates.values())) > 1:
            cross_date.append({**row, "request_dates_Asia_Shanghai": dates})
    crossed_ids = {r["id"] for r in cross_date}
    groups = {"completed_before_resume": old, "completed_during_resume": added,
              "all_complete_pairs": complete, "all_complete_excluding_cross_date_item": [r for r in complete if r["id"] not in crossed_ids]}
    cohorts = {name: {"A27": metrics(rows, "A27"), "V5": metrics(rows, "V5"), "paired": paired(rows)} for name, rows in groups.items()}
    for name, rows in groups.items():
        cohorts[name]["frozen_planned_items"] = len(cumulative["rows"])
        cohorts[name]["paired"]["complete_pair_subset_is_not_full_evaluation"] = len(rows) != len(cumulative["rows"])
    first = attempts[0]["requested_at"] if attempts else None
    last_stop = cumulative["stops"].get("fresh")
    current_stop = last_stop if first and last_stop and last_stop["time"] >= first else None
    new_costs = {}
    success_requests = {a["request_sha256"] for a in received}
    for stage in STAGES:
        records = []
        for p in (ROOT / "outputs/runs" / (RUN + "_fresh")).rglob(stage + ".json"):
            rec = read(p)
            if any(a["status"] == "received" and a["request_sha256"] in success_requests for a in rec["attempts"]):
                records.append(rec)
        new_costs[stage] = {"responses": len(records), "prompt_tokens": sum(v["usage"]["prompt_tokens"] for v in records),
            "completion_tokens": sum(v["usage"]["completion_tokens"] for v in records),
            "total_tokens": sum(v["usage"]["total_tokens"] for v in records),
            "server_seconds": sum(v["usage"].get("total_time", 0) for v in records),
            "client_seconds_including_throttle": sum(v["latency_seconds"] for v in records),
            "schema_valid": sum(v["validation"].get("schema_valid", False) for v in records),
            "protocol_valid": sum(v["validation"].get("protocol_valid", False) for v in records),
            "system_fingerprints": dict(Counter(v["system_fingerprint"] for v in records))}
    result = {"generated_at": now(), "resume_date": "2026-10-26", "run_id": RUN,
        "state": "complete" if len(complete) == len(cumulative["rows"]) else "partial",
        "planned_items": len(cumulative["rows"]), "complete_pairs": len(complete),
        "previous_complete_pairs": len(old), "newly_completed_pairs": len(added),
        "remaining_successful_formal_responses": 520 - sum(cumulative["fresh_received_nodes"].values()),
        "resume_http_attempts": len(attempts), "resume_successful_responses": len(received),
        "resume_successful_tokens": sum(a["usage"]["total_tokens"] for a in received),
        "resume_conservative_charged_tokens": sum(a["charged_tokens"] for a in attempts),
        "resume_http_statuses": dict(Counter(str(a.get("http_status")) for a in attempts)),
        "first_request_at": first, "last_response_at": attempts[-1].get("responded_at") if attempts else None,
        "current_stop": current_stop, "retained_historical_stop": last_stop if last_stop != current_stop else None,
        "new_stage_costs": new_costs, "cohorts": cohorts, "cross_date_items": cross_date,
        "request_dates_Asia_Shanghai": node_dates,
        "failed_attempts": [a for a in attempts if a["status"] not in ("received", "reserved")],
        "latest_rate_limit_headers": attempts[-1].get("rate_limits") if attempts else None,
        "historical_checkpoint": snapshot["public_archive"]}
    cumulative["resumption_status"] = {
        "state": result["state"], "complete_pairs": len(complete),
        "current_stop": current_stop,
        "retained_historical_stop": result["retained_historical_stop"],
        "details": "resumption_20261026_summary.json",
    }
    atomic_json(EXP / "continuation_summary.json", cumulative)
    table_text = helpers["tables"](cumulative)
    if result["state"] == "complete" and current_stop is None:
        notice = (
            "> 2026-10-26 续跑已完成全部104题。下文 `stops` 是保留的10月24日历史停点，"
            "不代表本次仍被限流；分日成本与当前状态见 [续跑摘要](resumption_20261026_summary.json)。\n\n"
        )
        first_line, rest = table_text.split("\n", 1)
        table_text = first_line + "\n\n" + notice + rest.lstrip("\n")
    (EXP / "continuation_tables.md").write_text(table_text, encoding="utf-8")
    atomic_json(EXP / "resumption_20261026_summary.json", result)
    return result


if __name__ == "__main__":
    result = summarize()
    print(json.dumps({k: result[k] for k in ("state", "complete_pairs", "newly_completed_pairs", "remaining_successful_formal_responses", "resume_http_attempts", "resume_successful_tokens", "current_stop")}, ensure_ascii=True))
