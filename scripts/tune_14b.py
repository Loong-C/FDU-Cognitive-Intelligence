"""Measure safe partial-offload candidates using synthetic probes, never pilot accuracy."""

import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ab_factcheck.cli import SMOKE_ROWS
from ab_factcheck.common import ROOT, atomic_json, file_hash, load_config, now
from ab_factcheck.model_client import LocalModelClient
from ab_factcheck.prompts import PromptSet
from ab_factcheck.resources_v3 import snapshot, startup_issues, summarize
from ab_factcheck.structured import parse_structured, response_format_for


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/experiment_14b_v3.json")
    parser.add_argument("--apply-selection", action="store_true", help="Freeze measured choice into a config whose run has not started")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.apply_selection:
        for suffix in ("", "_smoke", "_performance"):
            if (ROOT/config["output_root"]/(config["run_id"]+suffix)/"fingerprint.json").exists():
                raise ValueError("Run already frozen; use a new run ID before changing offload selection")
    base = ROOT / "outputs/runtime/qwen3-14b" / ("tuning-" + str(time.time_ns()))
    base.mkdir(parents=True)
    results = []
    prompts = PromptSet(ROOT / config["prompts_dir"], ("A2", "B2"))
    for layers in config["deployment"]["candidate_gpu_layers"]:
        trial = copy.deepcopy(config)
        trial["deployment"]["gpu_layers"] = layers
        trial["run_id"] += f"_tune_l{layers}"
        config_path = base / f"layers_{layers}.json"
        atomic_json(config_path, trial)
        result = {"layers": layers, "started_at": now(), "records": [], "passed": False}
        resources = snapshot()
        result["screening"] = {"resources": resources, "issues": startup_issues(trial, resources, layers)}
        client = None
        owned_directory = None
        try:
            if result["screening"]["issues"]:
                raise RuntimeError("; ".join(result["screening"]["issues"]))
            launch = subprocess.run([sys.executable, str(ROOT / "scripts/server_14b.py"), "start", "--config", str(config_path)],
                                    capture_output=True, text=True, timeout=180)
            result["launcher"] = {"returncode": launch.returncode, "stdout": launch.stdout, "stderr": launch.stderr}
            if launch.returncode:
                raise RuntimeError("Candidate startup rejected; see launcher evidence")
            startup = json.loads((ROOT / trial["deployment"]["startup_file"]).read_text(encoding="utf-8"))
            owned_directory = Path(startup["log_directory"])
            result["startup"] = startup
            client = LocalModelClient(trial["model"])
            for _ in range(150):
                if (owned_directory / "failure.json").exists():
                    raise RuntimeError((owned_directory / "failure.json").read_text(encoding="utf-8"))
                try:
                    if client.http.get("/health", timeout=2).status_code == 200:
                        break
                except Exception:
                    pass
                time.sleep(2)
            client.discover()
            for arm in ("A2", "B2"):
                for row in SMOKE_ROWS:
                    response = client.complete(prompts.render(arm, claim=row["claim"], evidence=row["evidence"]), response_format=response_format_for(arm))
                    parsed = parse_structured(response["raw_response"], arm, response["finish_reason"])
                    record = {"id": row["id"], "arm": arm, "gold_label_for_reporting_only": row["label"], "response": response, "parsed": parsed}
                    result["records"].append(record)
                    atomic_json(base / f"result_l{layers}.json", result)
                    if not parsed["protocol_valid"] or not response["nonthinking_validation"]["passed"] or not response["prompt_count_matches"]:
                        raise RuntimeError("Technical probe failure; logical mistakes are retained but do not block")
            result["passed"] = not (owned_directory / "failure.json").exists()
            result["resources_after"] = snapshot()
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if client:
                client.close()
            if owned_directory:
                (owned_directory / "stop.request").write_text(now())
                for _ in range(30):
                    if (owned_directory / "stopped.json").exists() or (owned_directory / "failure.json").exists():
                        break
                    time.sleep(1)
                # Allow the owning watchdog to finish releasing its child handle.
                time.sleep(2)
            atomic_json(base / f"result_l{layers}.json", result)
            results.append(result)
            print(json.dumps({"layers": layers, "passed": result["passed"], "error": result.get("error")}), flush=True)
    successful = [r for r in results if r["passed"]]
    selected = max((r["layers"] for r in successful), default=None)
    receipt = {"captured_at": now(), "selection_rule": "largest predeclared candidate passing technical checks and resource reserve; no accuracy selection",
               "selected_gpu_layers": selected, "results": results, "configuration_updated": False}
    atomic_json(base / "selection.json", receipt)
    print(f"Selection evidence: {base / 'selection.json'}; selected layers: {selected}")
    if selected is None:
        raise SystemExit(1)
    if args.apply_selection:
        config["deployment"].update(gpu_layers=selected, tuning_receipt=(base/"selection.json").relative_to(ROOT).as_posix(),
                                    tuning_receipt_sha256=file_hash(base/"selection.json"))
        atomic_json(args.config, config)
        print("Measured selection and evidence hash saved to configuration.")
    if config["deployment"]["gpu_layers"] != selected:
        print("Set deployment.gpu_layers before freezing smoke/formal fingerprints. Never modify an existing run.")


if __name__ == "__main__":
    main()
