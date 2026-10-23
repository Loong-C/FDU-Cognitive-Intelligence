"""Config-driven 14B launcher with an owning resource watchdog (no system changes)."""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ab_factcheck.common import ROOT, atomic_json, file_hash, load_config, now
from ab_factcheck.resources_v3 import command, page_reads, snapshot, startup_issues


def arguments(config, layers):
    m = config["model"]
    return [str(ROOT / config["deployment"]["backend_executable"]), "-m", str(ROOT / m["file"]),
            "--alias", m["alias"], "-ngl", str(layers), "-c", str(m["context_tokens"]), "-np", "1",
            "-b", "512", "-ub", "128", "-fa", "on", "--seed", "42", "--temp", "0", "-n", "1024",
            "--no-context-shift", "--no-cache-prompt", "--host", "127.0.0.1", "--port", str(urlsplit(m["endpoint"]).port),
            "--jinja", "--chat-template-kwargs", json.dumps(m["chat_template_kwargs"], separators=(",", ":")),
            "--reasoning", "off", "--reasoning-format", m["reasoning_format"], "--no-webui", "--log-timestamps", "-lv", "4"]


def worker(config, directory, layers):
    startup_path = ROOT / config["deployment"]["startup_file"]
    argv = arguments(config, layers)
    server = None
    policy = config["deployment"]
    pressure = 0
    begin = time.monotonic()
    try:
        # Recheck immediately before allocation, after any model hashing.
        resources = snapshot()
        issues = startup_issues(config, resources, layers)
        atomic_json(directory / "allocation_precheck.json", {"resources": resources, "issues": issues})
        if issues:
            raise RuntimeError("; ".join(issues))
        with (directory / "stdout.log").open("w", encoding="utf-8") as out, (directory / "stderr.log").open("w", encoding="utf-8") as err:
            server = subprocess.Popen(argv, cwd=Path(argv[0]).parent, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
            startup = dict(pid=server.pid, watchdog_pid=os.getpid(), created_at=now(), backend_release=config["model"]["backend_release"],
                           gpu_layers_requested=layers, port=urlsplit(config["model"]["endpoint"]).port, log_directory=str(directory),
                           executable=argv[0], arguments=argv[1:], configuration_sha256=file_hash(directory / "configuration.json"))
            atomic_json(directory / "startup.json", startup)
            atomic_json(startup_path, startup)
            while server.poll() is None:
                if (directory / "stop.request").exists():
                    break
                sample = snapshot()
                sample["paging"] = page_reads()
                with (directory / "resources.jsonl").open("a", encoding="utf-8") as output:
                    output.write(json.dumps(sample) + "\n"); output.flush()
                low_memory = sample["available_ram_bytes"] < policy["runtime_min_available_ram_gib"] * 1024**3
                low_vram = sample["gpus"][0]["free_mib"] < policy["min_free_vram_mib"]
                paging = (time.monotonic() - begin > 60 and sample["paging"]["PageReadsPersec"] > policy["max_page_reads_per_second"]
                          and sample["available_ram_bytes"] < 4 * 1024**3)
                pressure = pressure + 1 if paging else 0
                if low_memory or low_vram or pressure >= policy["page_pressure_consecutive_samples"]:
                    raise RuntimeError(f"Resource guard: low_ram={low_memory}, low_vram={low_vram}, sustained_page_pressure={pressure}")
                time.sleep(policy["resource_sample_seconds"])
            atomic_json(directory / "stopped.json", {"at": now(), "returncode": server.poll(), "requested": (directory / "stop.request").exists()})
    except Exception as exc:
        atomic_json(directory / "failure.json", {"at": now(), "error": f"{type(exc).__name__}: {exc}"})
    finally:
        # Popen retains the handle to this child. Never terminate an arbitrary PID.
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.kill(); server.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("precheck", "start", "stop", "worker"))
    parser.add_argument("--config", type=Path, default=ROOT / "configs/experiment_14b_v3.json")
    parser.add_argument("--gpu-layers", type=int, default=-1)
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    layers = config["deployment"]["gpu_layers"] if args.gpu_layers == -1 else args.gpu_layers
    startup_path = ROOT / config["deployment"]["startup_file"]
    if args.action == "worker":
        worker(config, args.directory, layers); return
    if args.action == "stop":
        startup = json.loads(startup_path.read_text(encoding="utf-8"))
        directory = Path(startup["log_directory"]).resolve()
        if not directory.is_relative_to((ROOT / "outputs/runtime/qwen3-14b").resolve()):
            raise ValueError("Unexpected server directory")
        (directory / "stop.request").write_text(now())
        print(f"Stop requested through owning watchdog: {directory}")
        return
    directory = ROOT / "outputs/runtime/qwen3-14b" / ("server-" + str(time.time_ns()))
    directory.mkdir(parents=True)
    resources = snapshot(detailed=True)
    issues = startup_issues(config, resources, layers)
    endpoint = urlsplit(config["model"]["endpoint"])
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", endpoint.port)) == 0:
            issues.append(f"Port {endpoint.port} already occupied; no process terminated")
    atomic_json(directory / "precheck.json", {"resources": resources, "issues": issues, "requested_gpu_layers": layers, "policy": config["deployment"]})
    print(f"Diagnostic directory: {directory}", flush=True)
    if issues:
        raise RuntimeError("; ".join(issues))
    if args.action == "precheck":
        print("Resource screening passed; model load and measured headroom still required."); return
    model_path = ROOT / config["model"]["file"]
    if model_path.stat().st_size != config["model"]["size_bytes"] or file_hash(model_path) != config["model"]["sha256"]:
        raise ValueError("14B model size/hash mismatch")
    argv = arguments(config, layers)
    version = command([argv[0], "--version"])
    # Some builds print their version to stderr; doctor validates combined output too.
    help_text = command([argv[0], "--help"])
    if "--chat-template-kwargs" not in help_text or "--reasoning-format" not in help_text:
        raise RuntimeError("Pinned backend lacks the required template/reasoning flags")
    atomic_json(directory / "configuration.json", config)
    atomic_json(directory / "backend.json", {"version": version, "sha256": file_hash(Path(argv[0])),
                "library_sha256": {p.name: file_hash(p) for p in Path(argv[0]).parent.glob("*.dll")}})
    log = (directory / "watchdog.log").open("w", encoding="utf-8")
    with log:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "worker", "--config", str(directory / "configuration.json"),
                          "--directory", str(directory), "--gpu-layers", str(layers)], cwd=ROOT, stdout=log, stderr=log,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    # Return promptly; doctor/health verifies readiness separately.
    for _ in range(20):
        if (directory / "failure.json").exists():
            raise RuntimeError((directory / "failure.json").read_text(encoding="utf-8"))
        if (directory / "startup.json").exists():
            print((directory / "startup.json").read_text(encoding="utf-8")); return
        time.sleep(0.5)
    raise RuntimeError("Watchdog startup did not acknowledge within 10 seconds; inspect logs before retrying")


if __name__ == "__main__":
    main()
