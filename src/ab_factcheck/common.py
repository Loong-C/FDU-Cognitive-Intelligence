"""Small shared utilities for inspectable, atomic experiment artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .splitting import LABELS, inside, json_bytes, sha256

ROOT = Path(__file__).resolve().parents[2]
ARMS = ("A0", "B1", "C1")
STRUCTURED_ARMS = ("A2", "B2", "C2")
DATASETS = ("challenge", "basic")


def experiment_arms(config: dict) -> tuple[str, ...]:
    default = STRUCTURED_ARMS if config.get("output_protocol") == "json_schema_v2" else ARMS
    arms = config.get("arms", default)
    if not isinstance(arms, (list, tuple)) or tuple(arms) not in (default, ("A2", "B2")) or any(a not in default for a in arms):
        raise ValueError("Arms must preserve the protocol order; supported subset is A2/B2")
    return tuple(arms)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path: Path | None = None) -> dict:
    config = json.loads((path or ROOT / "configs/experiment.json").read_text(encoding="utf-8"))
    model = config["model"]
    if model["temperature"] != 0 or model["stream"] is not False:
        raise ValueError("This experiment requires temperature=0 and stream=false")
    if not 0 < model["max_tokens"] < model["context_tokens"]:
        raise ValueError("Invalid token budgets")
    for key in ("experiment_id", "run_id", "split_version"):
        value = config[key]
        if not value or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in value):
            raise ValueError(f"Unsafe identifier: {key}")
    for key in ("pilot_dir", "prompts_dir", "output_root", "report_root"):
        inside(ROOT, config[key])
    if config.get("output_protocol") not in (None, "json_schema_v2"):
        raise ValueError("Unknown output protocol")
    if config.get("output_protocol") == "json_schema_v2":
        contexts = (8192, 4096) if config.get("model_upgrade_v3") else (8192,)
        if (model["max_tokens"], model["seed"]) != (1024, 42) or model["context_tokens"] not in contexts:
            raise ValueError("v2 requires max_tokens=1024, context=8192, seed=42")
    experiment_arms(config)
    if config.get("model_upgrade_v3"):
        if experiment_arms(config) != ("A2", "B2") or config["prompts_dir"] != "prompts/v2":
            raise ValueError("v3 requires unchanged v2 A2/B2 prompts")
        if model.get("chat_template_kwargs") != {"enable_thinking": False} or model.get("reasoning_format") != "deepseek" or model.get("require_nonthinking") is not True:
            raise ValueError("v3 requires explicit nonthinking with reasoning_content visibility")
        if config.get("execution_order") != "dataset_then_arm":
            raise ValueError("v3 requires challenge A/B then basic A/B")
        for key in ("startup_file", "backend_executable"):
            inside(ROOT, config["deployment"][key])
        inside(ROOT, model["file"])
    return config


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path: Path, value: object) -> None:
    atomic_bytes(path, json_bytes(value))


def frozen_json(path: Path, value: object) -> None:
    content = json_bytes(value)
    if path.exists() and path.read_bytes() != content:
        raise ValueError(f"Frozen artifact differs; use a new version/run: {path}")
    if not path.exists():
        atomic_bytes(path, content)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    atomic_bytes(path, b"".join(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n" for row in rows))
