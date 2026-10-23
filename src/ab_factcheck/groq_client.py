"""Fixed-origin Groq adapter; secrets never enter records or exception messages."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import time

import httpx

from .common import atomic_json, now, sha256
from .model_client import nonthinking_check

ENDPOINT = "https://api.groq.com/openai/v1"
MODEL = "qwen/qwen3.8-27b"
RATE_HEADERS = ("retry-after", "x-ratelimit-limit-requests", "x-ratelimit-limit-tokens",
                "x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens",
                "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens")


class GroqStop(RuntimeError):
    """Stop/pause the experiment, never convert a protocol/credential error to an answer."""


def load_local_key(root: Path):
    """Opt-in local loader. No shell evaluation, logging or file contents in errors."""
    if os.environ.get("GROQ_API_KEY"):
        return
    import subprocess
    if subprocess.run(["git", "ls-files", "--error-unmatch", ".env.local"], cwd=root,
                      capture_output=True).returncode == 0:
        raise GroqStop("Refusing a tracked credential file")
    if subprocess.run(["git", "check-ignore", "-q", ".env.local"], cwd=root).returncode != 0:
        raise GroqStop("Credential file must be ignored before loading")
    try:
        values = [line.split("=", 1)[1].strip().strip("\"'")
                  for line in (root / ".env.local").read_text(encoding="utf-8-sig").splitlines()
                  if line.startswith("GROQ_API_KEY=")]
    except OSError:
        raise GroqStop("Local credential file unavailable") from None
    if len(values) != 1 or not values[0]:
        raise GroqStop("Local credential entry missing or ambiguous")
    os.environ["GROQ_API_KEY"] = values[0]


@contextmanager
def exclusive(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise GroqStop("Run/ledger locked; inspect the owning process before removing a stale lock") from None
    with os.fdopen(fd, "w") as out:
        out.write(str(os.getpid()))
    try:
        yield
    finally:
        path.unlink()


def duration(value, clock=time.time):
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", value)
    if parts and "".join(n + u for n, u in parts) == value:
        return sum(float(n) * {"ms": .001, "s": 1, "m": 60, "h": 3600, "d": 86400}[u] for n, u in parts)
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - clock())
    except (ValueError, TypeError, OverflowError):
        return 0.0


class GroqModelClient:
    def __init__(self, config, ledger_path, *, free_plan_confirmed=False, transport=None,
                 sleeper=time.sleep, clock=time.time):
        if not free_plan_confirmed:
            raise GroqStop("Free Plan must be confirmed before any network request; no paid requests authorized")
        if config.get("endpoint") != ENDPOINT or config.get("model_id") != MODEL:
            raise GroqStop("Only the fixed HTTPS Groq origin and requested model are allowed")
        if (config.get("reasoning_effort"), config.get("temperature"), config.get("seed"),
            config.get("stream"), config.get("max_tokens")) != ("none", 0, 42, False, 1024):
            raise GroqStop("Unexpected decoding parameters; this protocol is frozen")
        self._key = os.environ.get("GROQ_API_KEY", "")
        if not self._key:
            raise GroqStop("GROQ_API_KEY is absent from the execution environment")
        self.config, self.model_id = config, MODEL
        self.ledger_path = Path(ledger_path)
        self.clock, self.sleeper = clock, sleeper
        self.http = httpx.Client(base_url=ENDPOINT + "/", timeout=config["timeout_seconds"],
                                 trust_env=False, follow_redirects=False, transport=transport)

    def close(self):
        self.http.close()

    def clean(self, value):
        if isinstance(value, str):
            value = value.replace(self._key, "[REDACTED]")
            value = re.sub(r"\b(?:gsk_|sk-proj-)[A-Za-z0-9_-]+", "[REDACTED]", value)
            return re.sub(r"\borg_[A-Za-z0-9_-]+", "[ORG]", value)
        if isinstance(value, list):
            return [self.clean(x) for x in value]
        if isinstance(value, dict):
            return {k: self.clean(v) for k, v in value.items() if k.lower() not in ("authorization", "api_key")}
        return value

    def ledger(self):
        return json.loads(self.ledger_path.read_text(encoding="utf-8")) if self.ledger_path.exists() else {"attempts": [], "blocked_until": 0}

    def save(self, ledger):
        atomic_json(self.ledger_path, self.clean(ledger))

    def wait(self, seconds):
        # Long resets pause the run instead of silently sleeping for a day.
        if seconds > self.config["budget"]["max_wait_seconds"]:
            raise GroqStop("Quota reset exceeds bounded wait; resume this run later")
        if seconds > 0:
            self.sleeper(seconds)

    def _reserve(self, ledger, payload):
        budget = self.config["budget"]
        # UTF-8 bytes plus overhead is deliberately pessimistic, not a tokenizer claim.
        reserve = len(json.dumps(payload, ensure_ascii=False).encode()) + 512 + self.config["max_tokens"]
        recent = [a for a in ledger["attempts"] if a["timestamp"] > self.clock() - 86400]
        if len(recent) >= budget["requests_24h"] or sum(a["charged_tokens"] for a in recent) + reserve > budget["tokens_24h"]:
            raise GroqStop("Local rolling-24h free budget reached; records preserved; resume later")
        if reserve > budget["tokens_per_minute"]:
            raise GroqStop("Conservative request reservation exceeds per-minute budget")
        self.wait(max(0, ledger.get("blocked_until", 0) - self.clock()))
        while True:
            minute = [a for a in recent if a["timestamp"] > self.clock() - 60]
            wait = max(0, (recent[-1]["timestamp"] + budget["min_interval_seconds"] - self.clock())) if recent else 0
            if minute and (len(minute) >= budget["requests_per_minute"] or sum(a["charged_tokens"] for a in minute) + reserve > budget["tokens_per_minute"]):
                wait = max(wait, minute[0]["timestamp"] + 60.1 - self.clock())
            if wait <= 0:
                break
            self.wait(wait)
        previous = recent[-1] if recent else {}
        headers = previous.get("rate_limits", {})
        elapsed = self.clock() - previous.get("timestamp", 0)
        for unit, needed in (("requests", 1), ("tokens", reserve)):
            try:
                low = float(headers.get(f"x-ratelimit-remaining-{unit}", "inf")) < needed
            except ValueError:
                low = True
            if low:
                reset = duration(headers.get(f"x-ratelimit-reset-{unit}"), self.clock)
                if not reset:
                    raise GroqStop("Server quota depleted without a reset time")
                self.wait(max(0, reset - elapsed + .2))
        entry = {"timestamp": self.clock(), "requested_at": now(), "charged_tokens": reserve,
                 "reservation_tokens": reserve, "status": "reserved", "request_sha256": sha256(json.dumps(payload, sort_keys=True).encode())}
        ledger["attempts"].append(entry)
        self.save(ledger)  # Reserve before network; a crash never loses budget accounting.
        return entry

    def complete(self, messages, *, response_format=None):
        payload = {"model": MODEL, "messages": messages, "temperature": 0, "seed": 42,
                   "reasoning_effort": "none", "stream": False, "max_completion_tokens": 1024}
        if response_format is not None:
            payload["response_format"] = response_format
        attempts, started = [], self.clock()
        with exclusive(self.ledger_path.with_suffix(".lock")):
            ledger = self.ledger()
            for index in range(self.config["network_retries"] + 1):
                entry = self._reserve(ledger, payload)
                attempts.append(entry)
                try:
                    response = self.http.post("chat/completions", json=payload, headers={"Authorization": "Bearer " + self._key})
                except httpx.TransportError as exc:
                    entry.update(status="transport_error", client_error_type=type(exc).__name__, responded_at=now())
                    self.save(ledger)
                    if index == self.config["network_retries"]:
                        raise GroqStop("Bounded transport retries exhausted; inspect attempt ledger") from None
                    self.wait(2 ** (index + 1))
                    continue
                entry.update(http_status=response.status_code, responded_at=now(),
                             rate_limits={k: response.headers[k] for k in RATE_HEADERS if k in response.headers})
                request_id = response.headers.get("x-request-id")
                entry["request_id_sha256"] = sha256(request_id.encode()) if request_id else None
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if response.status_code != 200:
                    error = body.get("error", {}) if isinstance(body, dict) else {}
                    entry.update(status="http_error", server_error_type=self.clean(error.get("type")),
                                 diagnostic=self.clean(str(error.get("message", "No JSON error message")))[:1200])
                    delay = max(duration(response.headers.get("retry-after"), self.clock), 2 ** (index + 1))
                    if response.status_code == 429:
                        for unit in ("requests", "tokens"):
                            if response.headers.get(f"x-ratelimit-remaining-{unit}") == "0":
                                delay = max(delay, duration(response.headers.get(f"x-ratelimit-reset-{unit}"), self.clock))
                        ledger["blocked_until"] = self.clock() + delay
                    self.save(ledger)
                    if response.status_code not in (429, 500, 502, 503, 504) or index == self.config["network_retries"]:
                        raise GroqStop(f"HTTP {response.status_code}; sanitized diagnostic saved; run stopped")
                    self.wait(delay)
                    continue
                if not isinstance(body, dict):
                    body = {}
                usage = body.get("usage", {})
                valid_usage = all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
                if valid_usage:
                    valid_usage = usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
                entry.update(status="received", usage=usage,
                             charged_tokens=usage["total_tokens"] if valid_usage else entry["charged_tokens"])
                self.save(ledger)
                choices = body.get("choices", [])
                content = choices[0].get("message", {}).get("content") if len(choices) == 1 else None
                check = nonthinking_check(body)
                issues = []
                if body.get("model") != MODEL: issues.append("model_identity_mismatch")
                if not valid_usage: issues.append("missing_or_invalid_usage")
                if not isinstance(content, str): issues.append("invalid_content")
                if not check["passed"]: issues.append("reasoning_detected")
                # Save the completion even when verification fails; never regenerate a received answer.
                safe_body = {k: body.get(k) for k in ("choices", "usage", "model", "system_fingerprint", "created", "service_tier")}
                return self.clean({"raw_response": content, "response_json": safe_body,
                    "finish_reason": choices[0].get("finish_reason") if len(choices) == 1 else None,
                    "usage": usage, "latency_seconds": self.clock() - started,
                    "requested_at": attempts[0]["requested_at"], "responded_at": entry["responded_at"],
                    "completion_request_attempts": len(attempts), "http_request_attempts": len(attempts),
                    "attempts": attempts, "request_payload": payload,
                    "effective_request_parameters": {k: v for k, v in payload.items() if k != "messages"},
                    "nonthinking_validation": check, "provider_validation_issues": issues,
                    "system_fingerprint": body.get("system_fingerprint"), "preflight_prompt_tokens": None})
        raise GroqStop("No completion received")
