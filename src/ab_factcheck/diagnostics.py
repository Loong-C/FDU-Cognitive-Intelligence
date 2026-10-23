"""Collect actual local environment and backend evidence before inference."""

import json
from pathlib import Path
import platform
import subprocess
import sys

from .common import ROOT, atomic_json, experiment_arms, file_hash, now, read_jsonl
from .pilot import prepare
from .prompts import PromptSet


def command_output(arguments: list[str]) -> dict:
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        return {"returncode": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}


def doctor(config: dict, client) -> dict:
    pilot_summary = prepare(config)
    prompts = PromptSet(ROOT / config["prompts_dir"], experiment_arms(config))
    raw_rows = []
    for path in ([] if config.get("model_upgrade_v3") else (ROOT / "data/raw/benchmark_1011").glob("*.jsonl")):
        raw_rows.extend(read_jsonl(path))
    prompts.validate_example(raw_rows)
    model_path = (ROOT / config["model"]["file"]).resolve()
    actual_hash = file_hash(model_path)
    if actual_hash != config["model"]["sha256"]:
        raise ValueError("Local model SHA-256 does not match configuration")
    runtime = client.discover()
    actual_model = runtime["props"].get("model_path")
    if not actual_model or model_path != Path(actual_model).resolve():
        raise ValueError(f"The server loaded a different model: {actual_model}")
    startup_file = ROOT / config.get("deployment", {}).get("startup_file", "outputs/runtime/server.json")
    startup = json.loads(startup_file.read_text(encoding="utf-8-sig")) if startup_file.exists() else {}
    backend_version = command_output([startup["executable"], "--version"]) if startup.get("executable") else {"error": "No local startup record"}
    log_text = ""
    if startup.get("log_directory"):
        log_file = Path(startup["log_directory"]) / "stderr.log"
        if log_file.exists():
            log_text = log_file.read_text(encoding="utf-8", errors="replace")
    version_text = backend_version.get("stdout", "") + backend_version.get("stderr", "")
    expected_build = config["model"]["backend_release"].removeprefix("b")
    if f"build {expected_build}" not in version_text:
        raise ValueError("The actual backend build differs from the configuration")
    if not any("offloaded" in line.lower() for line in log_text.splitlines()):
        raise ValueError("Backend startup log does not establish GPU offload")
    runtime["backend_identity"] = {
        "version": version_text.strip(),
        "executable_sha256": file_hash(Path(startup["executable"])),
        "arguments": [str(value).replace(str(ROOT), "<repo>") for value in startup["arguments"]],
        "offload_evidence": [line[line.lower().index("offloaded"):].strip() for line in log_text.splitlines() if "offloaded" in line.lower()],
    }
    if config.get("model_upgrade_v3"):
        import re
        from .preflight_v3 import context_preflight
        from .resources_v3 import snapshot
        if runtime["model_id"] != config["model"]["alias"]:
            raise ValueError("Loaded alias differs")
        offloads = re.findall(r"offloaded (\d+)/(\d+) layers", log_text)
        if not offloads or not 0 < int(offloads[-1][0]) < int(offloads[-1][1]):
            raise ValueError("Startup log must establish actual CPU/GPU partial offload")
        if int(offloads[-1][0]) != config["deployment"]["gpu_layers"]:
            raise ValueError("Actual GPU layers differ from frozen configuration")
        backend_directory = Path(startup["executable"]).parent
        runtime["backend_identity"]["library_sha256"] = {p.name: file_hash(p) for p in backend_directory.glob("*.dll")}
        context_preflight(config, prompts, client)
    result = {
        "captured_at": now(), "python": sys.version, "platform": platform.platform(),
        "gpu": command_output(["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader"]),
        "dependencies": command_output([sys.executable, "-m", "pip", "freeze", "--exclude-editable"]),
        "backend_version": backend_version,
        "backend_log_evidence": [line for line in log_text.splitlines() if any(term in line.lower() for term in ("offload", "cuda", "n_ctx", "kv buffer"))],
        "startup": startup, "runtime": runtime, "model_sha256": actual_hash,
        "pilot": pilot_summary, "prompt_sha256": prompts.hashes,
        "seed_note": "Seed=42 is requested. CUDA/backend execution is not claimed to be bitwise deterministic.",
    }
    if config.get("model_upgrade_v3"):
        result["resources"] = snapshot()
    run_directory = ROOT / config["output_root"] / config["run_id"]
    if not (run_directory / "environment.json").exists():
        atomic_json(run_directory / "environment.json", result)
    atomic_json(run_directory / "environment_latest_check.json", result)
    return result
