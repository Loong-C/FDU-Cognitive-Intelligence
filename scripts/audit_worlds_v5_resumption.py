"""Audit the 2026-10-26 resume against the immutable 2026-10-24 checkpoint."""
import json
from pathlib import Path
import runpy

from ab_factcheck.common import atomic_json, file_hash, now

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/005_layered_worlds"
RUN = "layered_worlds_qwen38_27b_v5_r2_free"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit():
    result = runpy.run_path(str(ROOT / "scripts/audit_worlds_v5_continuation.py"))["audit"]()
    errors = result["errors"]
    snapshot = read(ROOT / "outputs/worlds_v5_history/before_resume_20261026.json")
    public, private = ROOT / snapshot["public_archive"], ROOT / snapshot["private_archive"]
    for name, expected in snapshot["report_files_sha256"].items():
        if file_hash(public / name) != expected:
            errors.append("historical_report_archive_changed:" + name)
    for name, expected in snapshot["raw_files_sha256"].items():
        original = ROOT / name
        archived = private / Path(name).relative_to("outputs/runs")
        if file_hash(archived) != expected:
            errors.append("historical_raw_archive_changed:" + name)
        if original.name == "last_stop.json":
            continue  # historical stop remains in the exact-byte archive
        if original.name.endswith(".errors.json"):
            old, new = read(archived), read(original)
            if new[:len(old)] != old:
                errors.append("historical_error_prefix_changed:" + name)
        elif file_hash(original) != expected:
            errors.append("prior_response_or_fingerprint_changed:" + name)
    ledger = read(ROOT / "outputs/groq/quota.json")
    prefix = snapshot["ledger_prefix_attempts"]
    if ledger["attempts"][:prefix] != snapshot["ledger_prefix"]:
        errors.append("pre_resume_ledger_prefix_changed")
    if read(private / "quota.json")["attempts"] != snapshot["ledger_prefix"]:
        errors.append("archived_ledger_changed")
    attempts = ledger["attempts"][prefix:]
    received = [a for a in attempts if a["status"] == "received"]
    old_requests = {a["request_sha256"] for a in snapshot["ledger_prefix"] if a["status"] == "received"}
    if any(a["request_sha256"] in old_requests for a in received):
        errors.append("previously_successful_request_regenerated")
    result.update(time=now(), passed=not errors, resume_date="2026-10-26",
        archived_report_files=len(snapshot["report_files_sha256"]),
        preserved_prior_run_files=len(snapshot["raw_files_sha256"]),
        preserved_pre_resume_ledger_entries=prefix,
        resume_http_attempts=len(attempts), resume_successful_responses=len(received),
        resume_successful_tokens=sum(a["usage"]["total_tokens"] for a in received),
        resume_conservative_charged_tokens=sum(a["charged_tokens"] for a in attempts),
        old_successful_requests_regenerated=sum(a["request_sha256"] in old_requests for a in received),
        first_resume_request_at=attempts[0]["requested_at"] if attempts else None,
        last_resume_request_at=attempts[-1]["requested_at"] if attempts else None)
    return result


if __name__ == "__main__":
    result = audit()
    atomic_json(EXP / "resumption_20261026_audit.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "checked_records"}, ensure_ascii=True, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
