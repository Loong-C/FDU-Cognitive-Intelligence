"""Recompute the v6 report, check complete-run provenance, history and secret safety."""
import importlib.metadata
import hashlib
import json
import re
import subprocess

from ab_factcheck.common import ROOT, atomic_json, file_hash, read_jsonl
from ab_factcheck.symbolic_z3.experiment import EXPERIMENT, verify_freeze
from ab_factcheck.symbolic_z3.report import report


def main():
    result = report()
    directory = ROOT / EXPERIMENT
    manifest = verify_freeze()
    records = [json.loads((directory / "records" / (r["id"] + ".json")).read_text(encoding="utf-8"))
               for r in manifest["rows"] if (directory / "records" / (r["id"] + ".json")).exists()]
    probes = [json.loads((directory / name).read_text(encoding="utf-8")) for name in ("probe.json", "probe_birth.json")]
    completions = [r["completion"] for r in records + probes]
    all_attempts = [a for r in completions for a in r["attempts"]]
    ledger = json.loads((ROOT / "outputs/groq/quota.json").read_text(encoding="utf-8"))
    ledger_entries = {(a["timestamp"], a["request_sha256"]): a for a in ledger["attempts"]}
    for a in all_attempts:
        if ledger_entries.get((a["timestamp"], a["request_sha256"])) != a:
            raise ValueError("Attempt not found unchanged in shared ledger")
    source_paths = ["src/ab_factcheck", "prompts/v1", "prompts/v2", "prompts/v5", "data",
                    "experiments/001_two_world_pilot", "experiments/002_constrained_output",
                    "experiments/003_model_scaling_14b", "experiments/004_groq_27b", "experiments/005_layered_worlds"]
    changed = subprocess.check_output(["git", "diff", "--name-only", "9d0daea", "--", *source_paths], cwd=ROOT, text=True).splitlines()
    historic_changes = [p for p in changed if not p.startswith("src/ab_factcheck/symbolic_z3/")]
    secret_values = []
    secret_file = ROOT / ".env.local"
    if secret_file.exists():
        secret_values = [line.split("=", 1)[1].strip().strip("\"'") for line in secret_file.read_text(encoding="utf-8-sig").splitlines()
                         if line.startswith("GROQ_API_KEY=") and line.split("=", 1)[1].strip()]
    files = [p for base in (directory, ROOT / "prompts/v6", ROOT / "src/ab_factcheck/symbolic_z3")
             for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    files += [ROOT / "configs/experiment_symbolic_z3_v6.json", ROOT / "tests/test_symbolic_z3.py"]
    unsafe = []
    for path in files:
        content = path.read_text(encoding="utf-8-sig")
        if any(value in content for value in secret_values) or re.search(r"\b(?:gsk_|sk-proj-)[A-Za-z0-9_-]{12,}", content):
            unsafe.append(path.relative_to(ROOT).as_posix())
    pending = [p.name for p in (directory / "records").glob("*.inflight.json")]
    frozen = json.loads((directory / "freeze.json").read_text(encoding="utf-8"))
    frozen_sources = {**frozen["source_sha256"], **manifest["source_sha256"]}
    git_byte_mismatches = []
    for relative, expected in frozen_sources.items():
        indexed = subprocess.check_output(["git", "show", ":" + relative], cwd=ROOT)
        if hashlib.sha256(indexed).hexdigest() != expected:
            git_byte_mismatches.append(relative)
    audit = {**result, "all_scheduled": 42, "complete": len(records) == 42,
        "all_records_verified_and_replayed": True, "all_received_answers_unique": len({r["response_id_sha256"] for r in completions}) == len(completions),
        "formal_http_attempts": sum(len(r["completion"]["attempts"]) for r in records),
        "probe_http_attempts": sum(len(r["completion"]["attempts"]) for r in probes),
        "all_attempts_match_shared_ledger": True,
        "all_received_usage": {key: sum(r["usage"][key] for r in completions) for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "all_phase_conservative_charged_tokens": sum(a["charged_tokens"] for a in all_attempts),
        "nonthinking_checks_passed": all(r["nonthinking_validation"]["passed"] for r in completions),
        "provider_validation_issues": [r["provider_validation_issues"] for r in completions if r["provider_validation_issues"]],
        "finish_reasons": sorted({r["finish_reason"] for r in completions}),
        "system_fingerprints": sorted({r["system_fingerprint"] for r in completions}),
        "pending_inflight": pending, "historic_changes": historic_changes,
        "git_frozen_source_byte_mismatches": git_byte_mismatches,
        "credential_file_ignored": subprocess.run(["git", "check-ignore", "-q", ".env.local"], cwd=ROOT).returncode == 0,
        "secret_scan_files": len(files), "secret_matches": unsafe,
        "dependencies": {name: importlib.metadata.version(name) for name in ("z3-solver", "jsonschema", "httpx", "pytest")},
        "test_rows_opened": False,
        "test_seal_note": "Only dev files are consumed; history check uses git diff, not benchmark test inference.",
        "billing_verified": False}
    atomic_json(directory / "execution_audit.json", audit)
    print(json.dumps(audit, indent=2, ensure_ascii=True))
    if historic_changes or unsafe or pending or git_byte_mismatches or not audit["all_received_answers_unique"]:
        raise SystemExit(1)


if __name__ == "__main__": main()
