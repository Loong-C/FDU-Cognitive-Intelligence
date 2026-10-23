"""Loopback-only llama.cpp client with bounded retries and context preflight."""

from __future__ import annotations

import ipaddress
import hashlib
import re
import socket
import time
from urllib.parse import urlsplit

import httpx


def nonthinking_check(response: dict) -> dict:
    """Inspect raw generation; never strip/repair reasoning or the answer."""
    issues = []
    for choice in response.get("choices", []):
        message = choice.get("message", {})
        for key in ("reasoning_content", "reasoning"):
            if message.get(key) not in (None, "", []):
                issues.append(key)
        content = message.get("content") or ""
        cleaned = re.sub(r"<think>\s*</think>", "", content, flags=re.I)
        if re.search(r"</?think\b", cleaned, flags=re.I):
            issues.append("nonempty_or_unclosed_think")
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("reasoning_tokens", "thinking_tokens") and item not in (None, 0):
                    issues.append(key)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(response.get("usage", {}))
    return {"passed": not issues, "issues": issues, "policy": "inspect_raw_no_stripping_v1"}


class RequestFailure(RuntimeError):
    def __init__(self, message: str, *, attempts: int = 1, transient: bool = False):
        super().__init__(message)
        self.attempts = attempts
        self.transient = transient


def validate_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Endpoint must be a plain loopback HTTP(S) URL")
    if parsed.path.rstrip("/") != "/v1" or not parsed.hostname:
        raise ValueError("Endpoint path must be /v1")
    host = parsed.hostname
    if host == "localhost":
        addresses = [entry[4][0] for entry in socket.getaddrinfo(host, parsed.port or 80, type=socket.SOCK_STREAM)]
        if not addresses or not all(ipaddress.ip_address(address).is_loopback for address in addresses):
            raise ValueError("localhost must resolve only to loopback addresses")
        host = "127.0.0.1" if "127.0.0.1" in addresses else "::1"
    try:
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError("Remote model endpoints are forbidden")
    except ValueError as exc:
        raise ValueError("Only literal loopback addresses or localhost are allowed") from exc
    authority = f"[{host}]" if ":" in host else host
    if parsed.port:
        authority += f":{parsed.port}"
    return f"{parsed.scheme}://{authority}"


class LocalModelClient:
    def __init__(self, config: dict, *, transport=None, sleeper=time.sleep):
        self.config = config
        self.base = validate_endpoint(config["endpoint"])
        self.http = httpx.Client(
            base_url=self.base, timeout=config["timeout_seconds"],
            trust_env=False, follow_redirects=False, transport=transport,
        )
        self.sleeper = sleeper
        self.model_id = None
        self.props = None
        self.request_attempts = 0

    def close(self):
        self.http.close()

    def _request(self, method: str, path: str, payload=None) -> dict:
        for attempt in range(self.config["network_retries"] + 1):
            self.request_attempts += 1
            try:
                response = self.http.request(method, path, json=payload) if payload is not None else self.http.request(method, path)
                response.raise_for_status()
                value = response.json()
                if not isinstance(value, dict):
                    raise RequestFailure("Model endpoint returned a non-object JSON response")
                return value
            except httpx.HTTPStatusError as exc:
                transient = exc.response.status_code in (408, 429, 500, 502, 503, 504)
                if not transient or attempt == self.config["network_retries"]:
                    raise RequestFailure(f"HTTP {exc.response.status_code}: {exc.response.text[:500]}", attempts=attempt + 1, transient=transient) from exc
            except httpx.TransportError as exc:
                if attempt == self.config["network_retries"]:
                    raise RequestFailure(f"{type(exc).__name__}: {exc}", attempts=attempt + 1, transient=True) from exc
            except ValueError as exc:
                raise RequestFailure("Model endpoint returned invalid JSON") from exc
            self.sleeper(2 ** attempt)
        raise RequestFailure("Request failed")

    def discover(self) -> dict:
        self._request("GET", "/health")
        data = self._request("GET", "/v1/models").get("data", [])
        if len(data) != 1 or not isinstance(data[0].get("id"), str):
            raise ValueError("Expected exactly one loaded model")
        self.model_id = data[0]["id"]
        self.props = self._request("GET", "/props")
        settings = self.props.get("default_generation_settings", {})
        actual_context = settings.get("n_ctx")
        if actual_context != self.config["context_tokens"]:
            raise ValueError(f"Context differs: expected {self.config['context_tokens']}, server {actual_context}")
        template = self.props.get("chat_template")
        if not isinstance(template, str) or not template:
            raise ValueError("Server did not expose the chat template")
        return {"model_id": self.model_id, "model_metadata": data[0], "props": self.props}

    def template_options(self):
        return {key: self.config[key] for key in ("chat_template_kwargs", "reasoning_format") if key in self.config}

    def apply_template(self, messages: list[dict]) -> str:
        formatted = self._request("POST", "/apply-template", {"messages": messages, "add_generation_prompt": True, **self.template_options()})
        prompt = formatted.get("prompt")
        if not isinstance(prompt, str):
            raise RequestFailure("Server /apply-template did not return prompt text")
        self.last_template_summary = {"sha256": hashlib.sha256(prompt.encode()).hexdigest(), "characters": len(prompt),
                                      "suffix": prompt[-160:], "options": self.template_options()}
        return prompt

    def count_prompt(self, messages: list[dict]) -> int:
        prompt = self.apply_template(messages)
        tokens = self._request("POST", "/tokenize", {"content": prompt, "add_special": True, "parse_special": True}).get("tokens")
        if not isinstance(tokens, list):
            raise RequestFailure("Server /tokenize did not return a token list")
        return len(tokens)

    def complete(self, messages: list[dict], *, response_format: dict | None = None) -> dict:
        all_before = self.request_attempts
        if self.model_id is None:
            self.discover()
        prompt_tokens = self.count_prompt(messages)
        if prompt_tokens + self.config["max_tokens"] > self.config["context_tokens"]:
            raise RequestFailure(f"context_overflow: {prompt_tokens} prompt + {self.config['max_tokens']} output exceeds {self.config['context_tokens']}")
        payload = {
            "model": self.model_id, "messages": messages,
            "temperature": self.config["temperature"], "seed": self.config["seed"],
            "max_tokens": self.config["max_tokens"], "stream": False, "cache_prompt": False,
            **self.template_options(),
        }
        if response_format is not None:
            payload["response_format"] = response_format
        before = self.request_attempts
        start = time.perf_counter()
        response = self._request("POST", "/v1/chat/completions", payload)
        latency = time.perf_counter() - start
        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise RequestFailure("Expected one completion choice")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str):
            raise RequestFailure("Completion content is not a string")
        actual_tokens = response.get("usage", {}).get("prompt_tokens")
        if isinstance(actual_tokens, int) and actual_tokens + self.config["max_tokens"] > self.config["context_tokens"]:
            raise RequestFailure("Actual prompt tokens exceeded preflight context budget")
        return {
            "raw_response": content, "response_json": response,
            "finish_reason": choices[0].get("finish_reason"),
            "latency_seconds": latency, "usage": response.get("usage", {}),
            "preflight_prompt_tokens": prompt_tokens,
            "completion_request_attempts": self.request_attempts - before,
            "http_request_attempts": self.request_attempts - all_before,
            "effective_request_parameters": {k: v for k, v in payload.items() if k != "messages"},
            **({"request_payload": payload} if response_format is not None else {}),
            **({"nonthinking_validation": nonthinking_check(response), "applied_template": self.last_template_summary,
                "prompt_count_matches": actual_tokens == prompt_tokens}
               if self.config.get("require_nonthinking") else {}),
        }
