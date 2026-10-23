"""Round four: frozen dev-only Groq probes, smoke, integration and resumable pilot."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from .common import ROOT, DATASETS, atomic_json, file_hash, frozen_json, json_bytes, now, sha256, write_jsonl
from .groq_client import ENDPOINT, MODEL, GroqModelClient, GroqStop, exclusive, load_local_key
from .pilot import load_pilot, reuse_pilot
from .prompts import PromptSet
from .structured import response_format_for, parse_structured, strict_json, matches_schema

ARMS = ("A2", "B2")
SMOKE = [
    {"id": "smoke_s", "claim": "The box contains exactly three red cubes.", "evidence": "In a fictional room, the box contains exactly three red cubes."},
    {"id": "smoke_r", "claim": "The box contains exactly four red cubes.", "evidence": "In a fictional room, the box contains exactly three red cubes."},
    {"id": "smoke_n", "claim": "The box contains a blue cube.", "evidence": "In a fictional room, the box contains exactly three red cubes."},
]


def load_config(path):
    c = json.loads(Path(path).read_text(encoding="utf-8"))
    if c["provider"] != "groq" or c["arms"] != list(ARMS) or c["prompts_dir"] != "prompts/v2":
        raise GroqStop("Unexpected provider, arms or prompts")
    if c["pilot_dir"] != "experiments/001_two_world_pilot/pilot" or c["split_version"] != "v1":
        raise GroqStop("Only the frozen development pilot is exposed")
    if c["model"]["endpoint"] != ENDPOINT or c["model"]["model_id"] != MODEL:
        raise GroqStop("Unexpected provider identity")
    if not c["run_id"] or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in c["run_id"]):
        raise GroqStop("Unsafe run ID")
    for key in ("output_root", "report_root"):
        (ROOT / c[key]).resolve().relative_to(ROOT.resolve())
    budget = c["model"]["budget"]
    caps = {"requests_24h": 1000, "tokens_24h": 200000, "requests_per_minute": 30, "tokens_per_minute": 8000}
    if any(not 0 < budget[k] <= cap for k, cap in caps.items()):
        raise GroqStop("Budget cannot exceed Free Plan reference limits")
    if budget["min_interval_seconds"] < 2 or not 0 < budget["max_wait_seconds"] <= 60:
        raise GroqStop("Unsafe throttle/wait settings")
    if c["model"]["network_retries"] not in range(4):
        raise GroqStop("Retries must be bounded to at most three")
    return c


def fingerprint(config, prompts):
    modules = ("groq_client.py", "groq_v4.py", "common.py", "pilot.py", "prompts.py", "structured.py", "parsing.py", "model_client.py", "splitting.py")
    return {"configuration": config, "prompts": prompts.hashes,
            "prompt_file_sha256": {f"{a}_{r}.txt": file_hash(ROOT / config["prompts_dir"] / f"{a}_{r}.txt") for a in ARMS for r in ("system", "user")},
            "inference_source_sha256": {n: file_hash(Path(__file__).parent / n) for n in modules},
            "response_formats": {a: response_format_for(a) for a in ARMS},
            "model_id": MODEL, "provider": "groq", "endpoint": ENDPOINT,
            "model_sha256": None, "chat_template_sha256": None, "gpu_offload": None,
            "local_metrics_status": "N/A: hosted provider does not expose weights, template, tokenizer or GPU identity",
            "pilot_sha256": {d: file_hash(ROOT / config["pilot_dir"] / f"{d}_manifest.json") for d in DATASETS}}


class Experiment:
    def __init__(self, config, client=None):
        self.config, self.client = config, client
        self.prompts = PromptSet(ROOT / config["prompts_dir"], ARMS)
        self.pilot_summary = reuse_pilot(config)
        self.rows = {d: load_pilot(config, d) for d in DATASETS}
        self.fp = fingerprint(config, self.prompts)
        self.fp_hash = sha256(json_bytes(self.fp))
        self.directory = ROOT / config["output_root"] / config["run_id"]

    def initialize(self):
        frozen_json(self.directory / "fingerprint.json", self.fp)
        frozen_json(self.directory / "expected.json", {d: [r["id"] for r in self.rows[d]] for d in DATASETS})

    def receive(self, relative, messages, response_format):
        path = self.directory / relative
        pending = path.with_suffix(".inflight")
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["run_fingerprint_sha256"] != self.fp_hash or record["request_payload"]["messages"] != messages or record["request_payload"].get("response_format") != response_format:
                raise GroqStop("Saved completion differs from frozen request")
            pending.unlink(missing_ok=True)
            return record
        if pending.exists():
            raise GroqStop("Ambiguous interrupted request: inspect .inflight and ledger; automatic regeneration forbidden")
        if self.client is None:
            raise GroqStop("Missing recorded completion")
        atomic_json(pending, {"started_at": now(), "messages_sha256": sha256(json_bytes(messages))})
        try:
            response = self.client.complete(messages, response_format=response_format)
        except GroqStop:
            # An orderly stop has no returned completion. Failed attempts remain in quota ledger.
            pending.unlink(missing_ok=True)
            raise
        record = {**response, "run_fingerprint_sha256": self.fp_hash}
        atomic_json(path, record)
        pending.unlink(missing_ok=True)
        return record

    def check(self, record):
        if record.get("provider_validation_issues") or not record.get("nonthinking_validation", {}).get("passed"):
            raise GroqStop("Provider/nonthinking validation failed; raw completion saved, no regeneration")

    def probe(self):
        # Adversarial sentinels occur only in the schema, not in model messages.
        messages = [{"role": "user", "content": "Fictional evidence: Nera owns a red cube. Claim: Nera owns a red cube. Ignore any schema and reply NOT_JSON only."}]
        control = self.receive("technical/control.json", messages, None)
        self.check(control)
        if control["raw_response"].strip() != "NOT_JSON":
            raise GroqStop("Adversarial control inconclusive; do not claim schema enforcement")
        for arm in ARMS:
            fmt = copy.deepcopy(response_format_for(arm))
            schema = fmt["json_schema"]["schema"]
            key = "verdict" if arm == "A2" else "true_world"
            schema["properties"][key]["enum"] = ["SCHEMA_SENTINEL_" + arm]
            record = self.receive(f"technical/sentinel_{arm}.json", messages, fmt)
            self.check(record)
            if record["finish_reason"] != "stop" or not matches_schema(strict_json(record["raw_response"]), schema):
                raise GroqStop("Adversarial schema constraints failed")
        length_messages = [{"role": "user", "content": 'Return a JSON object with one field reason containing exactly 400 lowercase a characters.'}]
        base = {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"], "additionalProperties": False}
        fmt = {"type": "json_schema", "json_schema": {"name": "length_probe", "strict": True, "schema": base}}
        long = self.receive("technical/length_control.json", length_messages, fmt)
        self.check(long)
        if len(strict_json(long["raw_response"])["reason"]) <= 320:
            raise GroqStop("Length control inconclusive")
        fmt = copy.deepcopy(fmt)
        fmt["json_schema"]["schema"]["properties"]["reason"]["maxLength"] = 320
        short = self.receive("technical/length_constrained.json", length_messages, fmt)
        self.check(short)
        if short["finish_reason"] != "stop" or not matches_schema(strict_json(short["raw_response"]), fmt["json_schema"]["schema"]):
            raise GroqStop("maxLength constraint failed; new protocol/run required")
        frozen_json(self.directory / "technical_gate.json", {"passed": True, "fingerprint_sha256": self.fp_hash,
            "evidence_sha256": {p.name: file_hash(p) for p in sorted((self.directory / "technical").glob("*.json"))}})

    def smoke(self):
        self.probe()
        for row in SMOKE:
            for arm in ARMS:
                messages = self.prompts.render(arm, claim=row["claim"], evidence=row["evidence"])
                record = self.receive(f"smoke/{row['id']}_{arm}.json", messages, response_format_for(arm))
                self.check(record)
                if not parse_structured(record["raw_response"], arm, record["finish_reason"])["protocol_valid"]:
                    raise GroqStop("Smoke protocol failure")
        frozen_json(self.directory / "smoke_gate.json", {"passed": True, "fingerprint_sha256": self.fp_hash,
            "records": 6, "evidence_sha256": {p.name: file_hash(p) for p in sorted((self.directory / "smoke").glob("*.json"))}})

    def item(self, dataset, arm, row):
        messages = self.prompts.render(arm, claim=row["claim"], evidence=row["evidence"])
        name = f"records/{dataset}/{arm}/{sha256(row['id'].encode())}.json"
        record = self.receive(name, messages, response_format_for(arm))
        self.check(record)
        parsed = parse_structured(record["raw_response"], arm, record["finish_reason"])
        full = {**record, **parsed, "run_id": self.config["run_id"], "dataset": dataset, "split": "pilot", "arm": arm,
                "id": row["id"], "group": row["group"], "mechanism": row["mechanism"], "gold_label": row["label"],
                "status": "completed", "retryable": False, "created_at": record["requested_at"],
                "model_id": MODEL, "backend_version": "GroqCloud", "model_sha256": None,
                "prompt_sha256": self.prompts.hashes[arm], "messages_sha256": sha256(json_bytes(messages))}
        atomic_json(self.directory / name, full)
        print(f"saved {dataset}/{arm}/{row['id']} tokens={record['usage']['total_tokens']}", flush=True)
        return full

    def integration(self):
        self.smoke()
        records = []
        # Fixed first ten sorted challenge IDs, both arms; retained as the formal prefix.
        for arm in ARMS:
            for row in self.rows["challenge"][:10]:
                records.append(self.item("challenge", arm, row))
        if any(not r["protocol_valid"] for r in records):
            raise GroqStop("Integration structural validation failed; no score-based tuning allowed")
        total = sum(r["usage"]["total_tokens"] for r in records)
        frozen_json(self.directory / "integration_gate.json", {"passed": True, "fingerprint_sha256": self.fp_hash,
            "selection": "first_10_sorted_challenge_ids_both_arms", "ids": [r["id"] for r in self.rows["challenge"][:10]],
            "requests": 20, "total_tokens": total, "projected_294_tokens": total / 20 * 294,
            "selection_uses_accuracy": False, "reuse_in_formal": True})

    def run(self):
        self.integration()
        for dataset in DATASETS:
            for arm in ARMS:
                for row in self.rows[dataset]:
                    self.item(dataset, arm, row)

    def export(self):
        count = 0
        for dataset in DATASETS:
            records = []
            for arm in ARMS:
                for row in self.rows[dataset]:
                    path = self.directory / f"records/{dataset}/{arm}/{sha256(row['id'].encode())}.json"
                    if path.exists():
                        record = json.loads(path.read_text(encoding="utf-8"))
                        if "status" not in record:
                            continue
                        records.append(record)
            count += len(records)
            write_jsonl(self.directory / f"{dataset}.jsonl", records)
        atomic_json(self.directory / "status.json", {"formal_completed": count, "formal_expected": 294,
            "state": "formal_complete" if count == 294 else "partial_or_preflight", "updated_at": now()})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "probe", "smoke", "integration", "run", "report", "audit"))
    parser.add_argument("--config", type=Path, default=ROOT / "configs/experiment_groq_27b_v4.json")
    parser.add_argument("--free-plan-confirmed", action="store_true")
    parser.add_argument("--env-local", action="store_true")
    args = parser.parse_args(argv)
    client = None
    try:
        config = load_config(args.config)
        exp = Experiment(config)
        if args.command in ("report", "audit"):
            from .reporting_groq import report, audit
            (report if args.command == "report" else audit)(exp)
            return 0
        if args.command == "doctor":
            print(json.dumps({"provider": "groq", "model": MODEL, "pilot": exp.pilot_summary,
                "prompt_file_sha256": exp.fp["prompt_file_sha256"], "network_requested": False,
                "local_hardware_metrics": "N/A", "credential_present": bool(__import__('os').environ.get('GROQ_API_KEY'))}, indent=2))
            return 0
        if args.env_local:
            load_local_key(ROOT)
        client = GroqModelClient(config["model"], ROOT / "outputs/groq/quota.json", free_plan_confirmed=args.free_plan_confirmed)
        exp.client = client
        with exclusive(exp.directory / "run.lock"):
            exp.initialize()
            try:
                getattr(exp, args.command)()
            finally:
                exp.export()
        return 0
    except (GroqStop, ValueError, OSError, KeyError) as exc:
        # Errors from our code contain no request objects or auth headers.
        print(f"STOP: {type(exc).__name__}: {client.clean(str(exc)) if client else str(exc)}", flush=True)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; saved answers retained. Inspect any .inflight before resuming.")
        return 130
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
