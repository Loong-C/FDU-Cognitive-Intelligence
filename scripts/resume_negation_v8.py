"""Continue the frozen V8 batch only after provider quota waits. No answer retries."""
import json
import time

from ab_factcheck.common import ROOT, atomic_json, now
from ab_factcheck.negation_v8.experiment import OUTPUT, run
from ab_factcheck.negation_v8.reporting import report


def main():
    ledger_path = ROOT / "outputs/groq/quota.json"
    state_path = ROOT / OUTPUT / "confirm/continuation.json"
    state = {"started": now(), "phase": "confirm", "invocations": 0,
             "policy": "Only resume definite provider 429 quota stops; never retry ambiguous transport or received answers."}
    while True:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        blocked = max(0, ledger.get("blocked_until", 0) - time.time())
        if blocked:
            state.update(status="waiting_for_provider_quota", wait_seconds=blocked, updated=now())
            atomic_json(state_path, state)
            print(json.dumps({"status": state["status"], "wait_seconds": round(blocked, 1), "at": now()}), flush=True)
            until = time.monotonic() + blocked + 1
            while time.monotonic() < until:
                time.sleep(max(0, min(30, until - time.monotonic())))
        receipt = run("confirm")
        state.update(invocations=state["invocations"] + 1, last_execution=receipt, updated=now())
        if receipt["status"] == "complete":
            result = report("confirm")
            state.update(status="complete", passed_development_rule=result["passes_development_rule"], ended=now())
            atomic_json(state_path, state)
            return
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        last = ledger["attempts"][-1] if ledger["attempts"] else {}
        safe_quota_stop = (last.get("status") == "http_error" and last.get("http_status") == 429
                           and receipt.get("error_type") == "Halt"
                           and ("Quota reset" in receipt.get("reason", "") or "HTTP 429" in receipt.get("reason", "")))
        if not safe_quota_stop:
            state.update(status="requires_inspection", ended=now())
            atomic_json(state_path, state)
            raise SystemExit("Stopped on a non-quota condition; no automatic resend")
        state.update(status="quota_stop", updated=now())
        atomic_json(state_path, state)
        # On short 429 exhaustion the ledger deadline may already have expired.
        # Pace conservatively; the next invocation still honors all shared limits.
        if ledger.get("blocked_until", 0) <= time.time():
            time.sleep(30)


if __name__ == "__main__":
    main()
