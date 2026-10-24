"""Append-only DAG records and conservative recovery of interrupted requests."""
import json

from ..common import atomic_json, file_hash, frozen_json, json_bytes, now, sha256
from ..groq_client import GroqStop
from .adjudicator import adjudicate
from .client import Halt
from .constructor import Constructor
from .models import Candidate, Problem, validate
from .verifier import Verifier


def digest(value):
    return sha256(json_bytes(value))


class Orchestrator:
    def __init__(self, directory, prompts, fingerprint, limits, client=None):
        self.directory, self.prompts, self.client = directory, prompts, client
        self.fingerprint, self.limits = fingerprint, limits
        self.fp_hash = digest(fingerprint)
        self.constructors = {b: Constructor(b, prompts) for b in ("T", "F")}
        self.verifiers = {b: Verifier(b, prompts) for b in ("T", "F")}

    def initialize(self):
        frozen_json(self.directory / "fingerprint.json", self.fingerprint)

    def receive(self, relative, messages, response_format, *, limit, dependencies=None, validate_output=True):
        path = self.directory / relative
        pending = path.with_suffix(".inflight")
        error_path = path.with_suffix(".errors.json")
        request = {"messages": messages, "response_format": response_format, "max_completion_tokens": limit}
        identity = {"run_fingerprint_sha256": self.fp_hash, "request_sha256": digest(request),
                    "upstream_sha256": dependencies or {}}
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if any(record.get(k) != v for k, v in identity.items()):
                raise GroqStop("Saved node differs from frozen request/dependencies")
            if record.get("record_sha256") != digest({k: v for k, v in record.items() if k != "record_sha256"}):
                raise GroqStop("Saved node integrity mismatch")
            pending.unlink(missing_ok=True)
        else:
            if pending.exists():
                raise GroqStop("Ambiguous interrupted request; inspect inflight and ledger before any resend")
            errors = json.loads(error_path.read_text(encoding="utf-8")) if error_path.exists() else []
            if errors and not errors[-1]["retryable"]:
                raise GroqStop("Node has a terminal or ambiguous failure; automatic resend forbidden")
            if self.client is None:
                raise GroqStop("Missing recorded completion")
            atomic_json(pending, {**identity, "started_at": now()})
            try:
                response = self.client.complete(messages, response_format=response_format, max_completion_tokens=limit)
            except Halt as exc:
                errors.append({**identity, "time": now(), "error": str(exc), "retryable": exc.retryable,
                               "ambiguous": exc.ambiguous, "attempts": self.client.last_attempts})
                atomic_json(error_path, errors)
                if not exc.ambiguous:
                    pending.unlink(missing_ok=True)
                raise
            except GroqStop as exc:
                # Unknown adapter failures must remain ambiguous rather than discard the marker.
                errors.append({**identity, "time": now(), "error": str(exc), "retryable": False,
                               "ambiguous": True, "attempts": getattr(self.client, "last_attempts", [])})
                atomic_json(error_path, errors)
                raise
            validation = (validate(response["raw_response"], response_format["json_schema"]["schema"], response["finish_reason"])
                          if validate_output and response_format else {"protocol_valid": response["finish_reason"] == "stop", "errors": [], "parsed": None})
            record = {**identity, **response, "validation": validation}
            record["record_sha256"] = digest(record)
            frozen_json(path, record)
            pending.unlink(missing_ok=True)
        if record.get("provider_validation_issues") or not record.get("nonthinking_validation", {}).get("passed") or not record["validation"]["protocol_valid"]:
            raise GroqStop("Received protocol/provider failure retained; no regeneration")
        return record

    def item(self, dataset, sample_id, problem: Problem):
        # Paths never use untrusted dataset IDs directly.
        base = f"records/{digest([dataset, sample_id])}"
        dependencies = {"problem": digest({"evidence": problem.evidence, "claim": problem.claim})}
        generated, verified = {}, {}
        # Always both constructors, then both verifiers. No predictions can gate a role.
        for branch in ("T", "F"):
            messages, fmt = self.constructors[branch].request(problem)
            generated[branch] = self.receive(f"{base}/generate_{branch}.json", messages, fmt,
                limit=self.limits["constructor"], dependencies=dependencies)
        for branch in ("T", "F"):
            candidate = Candidate(**generated[branch]["validation"]["parsed"])
            messages, fmt = self.verifiers[branch].request(problem, candidate)
            verified[branch] = self.receive(f"{base}/verify_{branch}.json", messages, fmt,
                limit=self.limits["verifier"], dependencies={**dependencies, "constructor": generated[branch]["record_sha256"]})
        verdict = {"dataset": dataset, "id": sample_id, "run_fingerprint_sha256": self.fp_hash,
                   "upstream_sha256": {b: verified[b]["record_sha256"] for b in ("T", "F")},
                   **adjudicate(*(verified[b]["validation"]["parsed"]["decision"] for b in ("T", "F")))}
        frozen_json(self.directory / base / "verdict.json", verdict)
        return verdict
