"""Serial, atomic, resumable execution with an immutable run fingerprint."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

from .common import ARMS, ROOT, atomic_json, file_hash, frozen_json, json_bytes, now, sha256, write_jsonl
from .model_client import RequestFailure
from .parsing import parse_response


def source_hashes() -> dict:
    return {name: file_hash(Path(__file__).parent / name) for name in (
        "common.py", "pilot.py", "prompts.py", "parsing.py", "model_client.py", "runner.py",
    )}


def make_fingerprint(config: dict, prompts, runtime: dict) -> dict:
    return {
        "configuration": config,
        "prompts": prompts.hashes,
        "inference_source_sha256": source_hashes(),
        "model_id": runtime["model_id"],
        "model_sha256": config["model"]["sha256"],
        "backend_identity": runtime.get("backend_identity"),
        "chat_template_sha256": sha256(runtime["props"]["chat_template"].encode()),
        "context_tokens": runtime["props"]["default_generation_settings"]["n_ctx"],
        "pilot_sha256": {
            dataset: file_hash(ROOT / config["pilot_dir"] / f"{dataset}_manifest.json")
            for dataset in ("challenge", "basic")
        },
    }


class RunSession:
    def __init__(self, directory: Path, config: dict, prompts, client, fingerprint: dict):
        self.directory = directory
        self.config = config
        self.prompts = prompts
        self.client = client
        self.fingerprint = fingerprint
        self.fingerprint_hash = sha256(json_bytes(fingerprint))

    def initialize(self):
        frozen_json(self.directory / "fingerprint.json", self.fingerprint)
        if not (self.directory / "started.json").exists():
            atomic_json(self.directory / "started.json", {"created_at": now(), "fingerprint_sha256": self.fingerprint_hash})

    def _record_path(self, dataset: str, arm: str, sample_id: str) -> Path:
        safe_id = sha256(sample_id.encode())
        return self.directory / "records" / dataset / arm / f"{safe_id}.json"

    def run(self, dataset: str, rows: list[dict], arms=ARMS, *, split="pilot") -> list[dict]:
        self.initialize()
        expected = {"dataset": dataset, "split": split, "ids": [row["id"] for row in rows], "arms": list(ARMS)}
        frozen_json(self.directory / f"expected_{dataset}.json", expected)
        lock_path = self.directory / "run.lock"
        try:
            lock = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ValueError("Run is locked. If its process has ended, inspect and remove run.lock before resuming.") from exc
        with os.fdopen(lock, "w", encoding="utf-8") as output:
            output.write(json.dumps({"pid": os.getpid(), "created_at": now()}))
        try:
            for arm in arms:
                for index, row in enumerate(rows, 1):
                    record_path = self._record_path(dataset, arm, row["id"])
                    previous = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else None
                    if previous and not previous.get("retryable", False):
                        continue
                    print(f"{dataset}/{arm} {index}/{len(rows)} {row['id']}", flush=True)
                    messages = self.prompts.render(arm, claim=row["claim"], evidence=row["evidence"])
                    record = {
                        "run_id": self.config["run_id"], "dataset": dataset, "split": split,
                        "arm": arm, "id": row["id"], "group": row["group"],
                        "mechanism": row["mechanism"], "gold_label": row["label"],
                        "prompt_sha256": self.prompts.hashes[arm],
                        "messages_sha256": sha256(json_bytes(messages)),
                        "run_fingerprint_sha256": self.fingerprint_hash,
                        "model_id": self.client.model_id, "backend_version": self.config["model"]["backend_release"],
                        "model_sha256": self.config["model"]["sha256"],
                        "created_at": now(), "retryable": False,
                    }
                    if previous:
                        record["previous_failures"] = previous.get("previous_failures", []) + [
                            {key: previous.get(key) for key in ("created_at", "error", "latency_seconds", "request_attempts")}
                        ]
                    start = time.perf_counter()
                    try:
                        response = self.client.complete(messages)
                        record.update(response)
                        record.update(parse_response(response["raw_response"], arm, response["finish_reason"]))
                        record["status"] = "completed"
                    except RequestFailure as exc:
                        record.update(
                            status="request_failed", raw_response=None, predicted_label=None,
                            parse_status="invalid", parse_error="request_failed", consistency_status="unavailable",
                            error=str(exc), retryable=exc.transient, request_attempts=exc.attempts,
                            latency_seconds=time.perf_counter() - start, usage={}, finish_reason=None,
                        )
                    atomic_json(record_path, record)
        finally:
            lock_path.unlink(missing_ok=True)
            records = self.export(dataset, rows, split)
        return records

    def export(self, dataset: str, rows: list[dict], split="pilot") -> list[dict]:
        records = []
        for arm in ARMS:
            for row in rows:
                path = self._record_path(dataset, arm, row["id"])
                if path.exists():
                    record = json.loads(path.read_text(encoding="utf-8"))
                    if record["run_fingerprint_sha256"] != self.fingerprint_hash:
                        raise ValueError("Result fingerprint does not match this run")
                else:
                    record = {
                        "run_id": self.config["run_id"], "dataset": dataset, "split": split,
                        "arm": arm, "id": row["id"], "group": row["group"], "mechanism": row["mechanism"],
                        "gold_label": row["label"], "predicted_label": None,
                        "status": "not_run", "parse_status": "invalid", "parse_error": "not_run",
                        "consistency_status": "unavailable", "retryable": True,
                    }
                records.append(record)
        write_jsonl(self.directory / f"{dataset}.jsonl", records)
        return records
