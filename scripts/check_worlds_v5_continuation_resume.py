"""Recheck saved DAG with no API client; run only after inference has stopped."""
from contextlib import redirect_stdout
import io
from pathlib import Path

from ab_factcheck.common import atomic_json, file_hash, now
from ab_factcheck.groq_client import GroqStop
from ab_factcheck.worlds_v5_continuation import ContinuationExperiment, load_policy

ROOT = Path(__file__).resolve().parents[1]
config = load_policy(ROOT / "configs/continuation_worlds_v5_free.json")
directories = [ROOT / "outputs/runs" / (config["run_id"] + "_" + p) for p in ("smoke", "fresh")]
if any((p / "run.lock").exists() for p in directories):
    raise SystemExit("Inference lock exists; wait until it stops")


def snapshot():
    return {str(p.relative_to(ROOT)): file_hash(p) for d in directories for p in d.rglob("*") if p.is_file()}


before = snapshot()
ledger = file_hash(ROOT / "outputs/groq/quota.json")
exp = ContinuationExperiment(config, phase="fresh", client=None)
exp.initialize()
reason = None
buffer = io.StringIO()
try:
    with redirect_stdout(buffer):
        exp.run()
except GroqStop as exc:
    reason = str(exc)
assert reason in (None, "Missing recorded completion", "Node has a terminal or ambiguous failure; automatic resend forbidden", "Ambiguous interrupted request; inspect inflight and ledger before any resend"), reason
assert before == snapshot(), "Recovery mutated saved evidence"
assert ledger == file_hash(ROOT / "outputs/groq/quota.json"), "Recovery changed quota ledger"
result = {"time": now(), "passed": True, "api_client": None, "new_http_requests": 0,
          "cached_fresh_pairs_rechecked": sum(line.startswith("paired saved ") for line in buffer.getvalue().splitlines()),
          "cached_smoke_gate_rechecked": True, "stop_at_first_missing_or_blocked_node": reason,
          "raw_files_unchanged": len(before), "quota_ledger_sha256_unchanged": ledger}
atomic_json(ROOT / "experiments/005_layered_worlds/continuation_cache_validation.json", result)
print(result)
