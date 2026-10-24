"""v5 transport, reusing v4 credentials, fixed origin, locks and shared quota ledger.

No v4 implementation is modified. Read/write transport failures are ambiguous and
are never retried. Only definite connect failures and retryable HTTP statuses may
be retried, at most twice; received completions are never regenerated.
"""
import copy

import httpx

from ..common import now, sha256
from ..groq_client import GroqModelClient, GroqStop, MODEL, RATE_HEADERS, duration, exclusive
from ..model_client import nonthinking_check


class Halt(GroqStop):
    def __init__(self, reason, *, retryable=False, ambiguous=False):
        super().__init__(reason)
        self.retryable, self.ambiguous = retryable, ambiguous


class WorldClient(GroqModelClient):
    def __init__(self, config, ledger_path, **kwargs):
        if config["network_retries"] not in range(3):
            raise GroqStop("v5 permits at most two transient retries")
        super().__init__(config, ledger_path, **kwargs)
        self.last_attempts = []

    def _reserve(self, ledger, payload):
        # Reuse v4's exact persistent accounting with this node's actual output
        # ceiling. A shallow adapter view avoids mutating the frozen config.
        view = copy.copy(self)
        view.config = {**self.config, "max_tokens": payload["max_completion_tokens"]}
        return GroqModelClient._reserve(view, ledger, payload)

    def complete(self, messages, *, response_format=None, max_completion_tokens=384):
        if type(max_completion_tokens) is not int or not 1 <= max_completion_tokens <= 1024:
            raise Halt("Unsupported completion limit")
        payload = {"model": MODEL, "messages": messages, "temperature": 0, "seed": 42,
                   "reasoning_effort": "none", "stream": False,
                   "max_completion_tokens": max_completion_tokens}
        if response_format is not None:
            payload["response_format"] = response_format
        self.last_attempts = []
        started = self.clock()
        with exclusive(self.ledger_path.with_suffix(".lock")):
            ledger = self.ledger()
            for index in range(self.config["network_retries"] + 1):
                try:
                    entry = self._reserve(ledger, payload)
                except GroqStop as exc:
                    raise Halt(str(exc), retryable=True) from None
                self.last_attempts.append(entry)
                try:
                    response = self.http.post("chat/completions", json=payload,
                                              headers={"Authorization": "Bearer " + self._key})
                except httpx.TransportError as exc:
                    definite = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
                    entry.update(status="connect_error" if definite else "transport_ambiguous",
                                 client_error_type=type(exc).__name__, responded_at=now())
                    self.save(ledger)
                    if not definite:
                        raise Halt("Ambiguous transport failure; automatic resend forbidden", ambiguous=True) from None
                    if index == self.config["network_retries"]:
                        raise Halt("Bounded connection retries exhausted") from None
                    self.wait(2 ** (index + 1))
                    continue
                entry.update(http_status=response.status_code, responded_at=now(),
                             rate_limits={k: response.headers[k] for k in RATE_HEADERS if k in response.headers})
                reqid = response.headers.get("x-request-id")
                entry["request_id_sha256"] = sha256(reqid.encode()) if reqid else None
                try:
                    body = response.json()
                except ValueError:
                    body = None
                if response.status_code != 200:
                    entry.update(status="http_error", error_body=self.clean(body if body is not None else response.text))
                    delay = max(duration(response.headers.get("retry-after"), self.clock), 2 ** (index + 1))
                    if response.status_code == 429:
                        for unit in ("requests", "tokens"):
                            if response.headers.get(f"x-ratelimit-remaining-{unit}") == "0":
                                delay = max(delay, duration(response.headers.get(f"x-ratelimit-reset-{unit}"), self.clock))
                        ledger["blocked_until"] = self.clock() + delay
                    self.save(ledger)
                    if response.status_code not in (429, 500, 502, 503, 504):
                        raise Halt(f"HTTP {response.status_code}; terminal response retained")
                    if index == self.config["network_retries"]:
                        raise Halt(f"HTTP {response.status_code}; bounded retries exhausted")
                    try:
                        self.wait(delay)
                    except GroqStop as exc:
                        raise Halt(str(exc), retryable=True) from None
                    continue
                raw_body = copy.deepcopy(body)
                if not isinstance(body, dict):
                    body = {}
                usage = body.get("usage") or {}
                valid_usage = isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
                if valid_usage:
                    valid_usage = usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
                entry.update(status="received", usage=usage,
                             charged_tokens=usage["total_tokens"] if valid_usage else entry["charged_tokens"])
                self.save(ledger)
                choices = body.get("choices", [])
                choice = choices[0] if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict) else {}
                message = choice.get("message") or {}
                content = message.get("content") if isinstance(message, dict) else None
                try:
                    check = nonthinking_check(body)
                except (TypeError, KeyError, AttributeError):
                    check = {"passed": False, "error": "MALFORMED_PROVIDER_BODY"}
                issues = []
                if body.get("model") != MODEL: issues.append("MODEL_IDENTITY_MISMATCH")
                if not valid_usage: issues.append("INVALID_USAGE")
                if not isinstance(content, str): issues.append("INVALID_CONTENT")
                if not check["passed"]: issues.append("NONTHINKING_CHECK_FAILED")
                if message.get("refusal") if isinstance(message, dict) else False:
                    issues.append("PROVIDER_REFUSAL")
                response_id = body.get("id")
                response_hash = sha256(str(response_id).encode()) if response_id is not None else None
                if isinstance(raw_body, dict):
                    raw_body.pop("id", None)
                    raw_body["response_id_sha256"] = response_hash
                return self.clean({"raw_response": content, "response_json": raw_body,
                    "raw_non_json_body": response.text if raw_body is None else None,
                    "response_id_sha256": response_hash, "actual_model_id": body.get("model"),
                    "system_fingerprint": body.get("system_fingerprint"),
                    "finish_reason": choice.get("finish_reason"), "usage": usage,
                    "latency_seconds": self.clock() - started, "requested_at": self.last_attempts[0]["requested_at"],
                    "responded_at": entry["responded_at"], "attempts": self.last_attempts,
                    "request_payload": payload, "nonthinking_validation": check,
                    "provider_validation_issues": issues})
        raise Halt("No completion received")
