"""Explicitly authorized free-quota continuation without altering frozen r1 code.

The provider's Free Plan enforces its quota. The historical ledger remains an
append-only audit trail, not a substitute for the provider's unknown daily window.
This module cannot change the account plan, billing, endpoint or model.
"""
import argparse
import copy
import json
from pathlib import Path

from .common import ROOT, atomic_json, file_hash, frozen_json, json_bytes, now, sha256
from .groq_client import GroqStop, duration, exclusive, load_local_key
from .structured import response_format_for
from .worlds_v5.client import Halt, WorldClient
from .worlds_v5.evaluation import report
from .worlds_v5.experiment import EXPERIMENT, Experiment, load_config
from .worlds_v5.models import Problem
from .worlds_v5.orchestrator import Orchestrator, digest


def load_policy(path, root=ROOT):
    policy = json.loads(path.read_text(encoding="utf-8"))
    if (policy["quota_policy"], policy["local_rolling_daily_stop"], policy["never_upgrade_plan_or_change_endpoint"],
        policy["reuse_received_parent_responses"]) != ("provider_enforced_free", False, True, True):
        raise GroqStop("Unexpected continuation policy")
    if policy["parent_config"] != "configs/experiment_worlds_v5.json":
        raise GroqStop("Only the frozen v5 parent is supported")
    parent = load_config(root / policy["parent_config"])
    if parent["run_id"] != policy["parent_run_id"] or parent["run_id"] == policy["run_id"]:
        raise GroqStop("Continuation requires its own run identity")
    if not policy["run_id"] or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in policy["run_id"]):
        raise GroqStop("Unsafe continuation run ID")
    if policy["free_reference_limits"] != {"requests_per_day": 1000, "tokens_per_day": 200000, "requests_per_minute": 30, "tokens_per_minute": 8000}:
        raise GroqStop("Unexpected Free Plan reference")
    expected = {k: parent["model"]["budget"][k] for k in ("requests_per_minute", "tokens_per_minute", "min_interval_seconds", "max_wait_seconds")}
    if policy["throttle"] != expected:
        raise GroqStop("Minute throttle must stay unchanged")
    if type(policy["max_new_attempts_per_execution"]) is not int or not 1 <= policy["max_new_attempts_per_execution"] <= 1000:
        raise GroqStop("Execution attempt cap required")
    config = copy.deepcopy(parent)
    config["run_id"] = policy["run_id"]
    config["continuation_policy"] = policy
    # Daily numbers are reference metadata; ProviderFreeClient does not pretend
    # its rolling window is the provider's undisclosed daily quota window.
    config["model"]["budget"].update(requests_24h=1000, tokens_24h=200000)
    return config


class ProviderFreeClient(WorldClient):
    def __init__(self, config, ledger_path, policy, **kwargs):
        if policy["quota_policy"] != "provider_enforced_free" or policy["local_rolling_daily_stop"] is not False:
            raise GroqStop("Explicit provider-enforced policy required")
        super().__init__(config, ledger_path, **kwargs)
        self.policy = policy
        self.new_attempts = 0

    def _reserve(self, ledger, payload):
        if self.new_attempts >= self.policy["max_new_attempts_per_execution"]:
            raise GroqStop("Execution attempt cap reached; inspect before another invocation")
        budget = self.policy["throttle"]
        reserve = len(json.dumps(payload, ensure_ascii=False).encode()) + 512 + payload["max_completion_tokens"]
        self.wait(max(0, ledger.get("blocked_until", 0) - self.clock()))
        # Preserve conservative accounting and minute pacing, but never reject a
        # request merely because serialized bytes exceed a TOKEN quota. The
        # provider performs the actual token count and enforces its hard limit.
        scheduled = min(reserve, budget["tokens_per_minute"])
        while True:
            minute = [a for a in ledger["attempts"] if a["timestamp"] > self.clock() - 60]
            last = ledger["attempts"][-1] if ledger["attempts"] else None
            delay = max(0, last["timestamp"] + budget["min_interval_seconds"] - self.clock()) if last else 0
            if minute and (len(minute) >= budget["requests_per_minute"] or sum(a["charged_tokens"] for a in minute) + scheduled > budget["tokens_per_minute"]):
                delay = max(delay, minute[0]["timestamp"] + 60.1 - self.clock())
            if delay <= 0: break
            self.wait(delay)
        previous = ledger["attempts"][-1] if ledger["attempts"] else {}
        headers = previous.get("rate_limits", {})
        elapsed = self.clock() - previous.get("timestamp", 0)
        for unit, needed in (("requests", 1), ("tokens", scheduled)):
            try:
                low = float(headers.get(f"x-ratelimit-remaining-{unit}", "inf")) < needed
            except ValueError:
                raise GroqStop("Invalid provider quota header") from None
            if low:
                reset = duration(headers.get(f"x-ratelimit-reset-{unit}"), self.clock)
                if not reset: raise GroqStop("Provider quota exhausted without reset time")
                self.wait(max(0, reset - elapsed + .2))
        entry = {"timestamp": self.clock(), "requested_at": now(), "charged_tokens": reserve,
                 "reservation_tokens": reserve, "status": "reserved",
                 "request_sha256": sha256(json.dumps(payload, sort_keys=True).encode()),
                 "quota_policy": "provider_enforced_free", "continuation_policy_sha256": digest(self.policy)}
        ledger["attempts"].append(entry)
        self.save(ledger)
        self.new_attempts += 1
        return entry


class LineageOrchestrator(Orchestrator):
    def __init__(self, *args, parent_directory, root=ROOT, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_directory, self.root = parent_directory, root
        self.parent_fp = json.loads((parent_directory / "fingerprint.json").read_text(encoding="utf-8"))
        for name, expected in self.parent_fp["source_sha256"].items():
            if file_hash(root / name) != expected:
                raise GroqStop("Frozen parent inference source changed")

    def receive(self, relative, messages, response_format, *, limit, dependencies=None, validate_output=True):
        destination = self.directory / relative
        source = self.parent_directory / relative
        if not destination.exists():
            if source.with_suffix(".inflight").exists():
                raise GroqStop("Parent has an ambiguous inflight request; do not resend")
            if source.exists():
                r = json.loads(source.read_text(encoding="utf-8"))
                if r["run_fingerprint_sha256"] != digest(self.parent_fp) or r["record_sha256"] != digest({k: v for k, v in r.items() if k != "record_sha256"}):
                    raise GroqStop("Parent completion integrity failed")
                request = {"messages": messages, "response_format": response_format, "max_completion_tokens": limit}
                if r["request_sha256"] != digest(request):
                    raise GroqStop("Parent request differs; refusing selective regeneration")
                p = r["request_payload"]
                if p["messages"] != messages or p.get("response_format") != response_format or p["max_completion_tokens"] != limit:
                    raise GroqStop("Parent payload differs")
                if any(p.get(k) != v for k, v in {"model": self.fingerprint["config"]["model"]["model_id"], "temperature": 0, "seed": 42, "reasoning_effort": "none", "stream": False}.items()):
                    raise GroqStop("Parent inference parameters differ")
                for key, value in (dependencies or {}).items():
                    if key != "constructor" and r["upstream_sha256"].get(key) != value:
                        raise GroqStop("Parent original-input dependency differs")
                if "constructor" in (dependencies or {}):
                    gp = source.with_name("generate_" + source.stem[-1] + ".json")
                    if not gp.exists() or json.loads(gp.read_text(encoding="utf-8"))["record_sha256"] != r["upstream_sha256"]["constructor"]:
                        raise GroqStop("Parent branch dependency differs")
                r.update(run_fingerprint_sha256=self.fp_hash, upstream_sha256=dependencies or {},
                         reused_from={"path": source.relative_to(self.root).as_posix(), "file_sha256": file_hash(source),
                                      "parent_record_sha256": r["record_sha256"], "new_http_requests": 0})
                r.pop("record_sha256")
                r["record_sha256"] = digest(r)
                frozen_json(destination, r)
            else:
                ep = source.with_suffix(".errors.json")
                if ep.exists():
                    errors = json.loads(ep.read_text(encoding="utf-8"))
                    if errors and (errors[-1].get("ambiguous") or not errors[-1].get("retryable")):
                        raise GroqStop("Parent terminal failure cannot be retried under a new run ID")
        return super().receive(relative, messages, response_format, limit=limit,
                               dependencies=dependencies, validate_output=validate_output)


class ContinuationExperiment(Experiment):
    def __init__(self, config, *, phase="smoke", client=None, root=ROOT):
        super().__init__(config, phase=phase, root=root)
        parent_dir = root / "outputs/runs" / (config["continuation_policy"]["parent_run_id"] + "_" + phase)
        fp = self.dag.fingerprint
        fp["continuation_source_sha256"] = {"src/ab_factcheck/worlds_v5_continuation.py": file_hash(root / "src/ab_factcheck/worlds_v5_continuation.py")}
        fp["parent_fingerprint_sha256"] = file_hash(parent_dir / "fingerprint.json")
        self.dag = LineageOrchestrator(self.directory, self.prompts, fp, config["limits"], client,
                                       parent_directory=parent_dir, root=root)

    def run(self):
        if self.phase != "fresh": raise GroqStop("Fresh phase required")
        smoke = ContinuationExperiment(self.config, phase="smoke", root=self.root)
        smoke.initialize(); smoke.smoke()
        frozen_json(self.directory / "smoke_gate_reference.json", {"path": smoke.directory.relative_to(self.root).as_posix(),
                    "sha256": file_hash(smoke.directory / "smoke_gate.json")})
        for group in self.manifest["execution_order"]:
            dataset = group["dataset"]
            rows = {r["id"]: r for r in self.manifest["datasets"][dataset]["rows"]}
            for sample_id in group["ids"]:
                row = rows[sample_id]
                problem = Problem(row["evidence"], row["claim"])
                messages = self.direct.render("A2", evidence=problem.evidence, claim=problem.claim)
                self.dag.receive("records/" + digest([dataset, sample_id]) + "/baseline_A27.json", messages,
                    response_format_for("A2"), limit=self.config["limits"]["baseline"], dependencies={"problem": digest(problem.__dict__)})
                self.dag.item(dataset, sample_id, problem)
                print("paired saved " + dataset + "/" + sample_id, flush=True)


def continuation_report(exp):
    summary = report(exp)
    reused, new = [], []
    for path in exp.directory.rglob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and "request_payload" in value:
            (reused if value.get("reused_from") else new).append(value)
    summary["continuation_accounting"] = {
        "reused_responses": len(reused), "new_responses": len(new),
        "reused_tokens_not_charged_again": sum(r["usage"].get("total_tokens", 0) for r in reused),
        "new_successful_tokens": sum(r["usage"].get("total_tokens", 0) for r in new),
        "combined_lineage_cost_fields_include_parent_usage": True}
    atomic_json(exp.root / EXPERIMENT / "reports" / (exp.config["run_id"] + "_" + exp.phase) / "metrics.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("smoke", "run", "continue", "report"))
    parser.add_argument("--policy", type=Path, default=ROOT / "configs/continuation_worlds_v5_free.json")
    parser.add_argument("--phase", choices=("smoke", "fresh"), default="smoke")
    parser.add_argument("--env-local", action="store_true")
    parser.add_argument("--free-plan-confirmed", action="store_true")
    args = parser.parse_args(argv)
    client, exp = None, None
    try:
        config = load_policy(args.policy)
        if args.command == "report":
            exp = ContinuationExperiment(config, phase=args.phase)
            print(json.dumps(continuation_report(exp)["continuation_accounting"]))
            return 0
        if args.env_local: load_local_key(ROOT)
        client = ProviderFreeClient(config["model"], ROOT / "outputs/groq/quota.json", config["continuation_policy"], free_plan_confirmed=args.free_plan_confirmed)
        phases = ("smoke", "fresh") if args.command == "continue" else (("smoke",) if args.command == "smoke" else ("fresh",))
        for phase in phases:
            exp = ContinuationExperiment(config, phase=phase, client=client)
            with exclusive(exp.directory / "run.lock"):
                exp.initialize()
                try:
                    (exp.smoke if phase == "smoke" else exp.run)()
                finally:
                    summary = continuation_report(exp)
                    print(json.dumps({"phase": phase, "v5_completed": summary["v5_completed"], "baseline_completed": summary["baseline_completed"], **summary["continuation_accounting"]}), flush=True)
        return 0
    except (GroqStop, ValueError, OSError, KeyError) as exc:
        safe = client.clean(str(exc)) if client else str(exc)
        if exp: atomic_json(exp.directory / "last_stop.json", {"time": now(), "type": type(exc).__name__, "reason": safe})
        print("STOP: " + safe, flush=True)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; preserve inflight markers and inspect before resume.")
        return 130
    finally:
        if client: client.close()


if __name__ == "__main__":
    raise SystemExit(main())
