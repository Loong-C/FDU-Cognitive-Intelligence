"""Versioned local pilot experiments; historical and constrained output protocols."""

import argparse
import copy
import json
from pathlib import Path
import sys

from .common import ARMS, STRUCTURED_ARMS, DATASETS, ROOT, experiment_arms, frozen_json, load_config
from .gates import constraint_probe, verify_smoke
from .diagnostics import doctor
from .model_client import LocalModelClient
from .pilot import load_pilot, prepare
from .prompts import PromptSet
from .reporting import report
from .runner import RunSession, make_fingerprint

SMOKE_ROWS = [
    {"id": "smoke_support", "group": "smoke_s", "mechanism": "synthetic", "label": "SUPPORTS",
     "evidence": "In a fictional room, the sealed box contains exactly three red cubes.",
     "claim": "The sealed box contains exactly three red cubes."},
    {"id": "smoke_refute", "group": "smoke_r", "mechanism": "synthetic", "label": "REFUTES",
     "evidence": "In a fictional room, the sealed box contains exactly three red cubes.",
     "claim": "The sealed box contains exactly four red cubes."},
    {"id": "smoke_nei", "group": "smoke_n", "mechanism": "synthetic", "label": "NOT ENOUGH INFO",
     "evidence": "In a fictional room, the sealed box contains exactly three red cubes.",
     "claim": "The sealed box also contains a blue cube."},
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "doctor", "smoke", "run", "report"))
    parser.add_argument("--config", type=Path, default=ROOT / "configs/experiment.json")
    parser.add_argument("--dataset", choices=(*DATASETS, "all"), default="all")
    parser.add_argument("--arm", choices=(*ARMS, *STRUCTURED_ARMS, "all"), default="all")
    parser.add_argument("--split", choices=("pilot",), default="pilot", help="This stage exposes only the development pilot")
    args = parser.parse_args(argv)
    client = None
    try:
        config = load_config(args.config)
        structured = config.get("output_protocol") == "json_schema_v2"
        configured_arms = experiment_arms(config)
        if args.arm != "all" and args.arm not in configured_arms:
            raise ValueError("Selected arm does not match the configured protocol")
        if args.command == "prepare":
            print(json.dumps(prepare(config), ensure_ascii=False, indent=2))
            return 0
        if args.command == "report":
            result = report(config)
            print(f"Report ready: {result['report_directory']} ({result['record_count']} records)")
            return 0
        if args.command == "smoke":
            config = copy.deepcopy(config)
            config["run_id"] += "_smoke"
        client = LocalModelClient(config["model"])
        environment = doctor(config, client)
        print(f"Local model ready: {client.model_id}", flush=True)
        if args.command == "doctor":
            print(json.dumps({key: environment[key] for key in ("gpu", "backend_version", "pilot")}, ensure_ascii=False, indent=2))
            return 0
        prompts = PromptSet(ROOT / config["prompts_dir"])
        fingerprint = make_fingerprint(config, prompts, environment["runtime"])
        session = RunSession(ROOT / config["output_root"] / config["run_id"], config, prompts, client, fingerprint)
        arms = configured_arms if args.arm == "all" else (args.arm,)
        if args.command == "smoke":
            if structured:
                session.initialize()
                constraint_probe(session)
            records = session.run("synthetic", sorted(SMOKE_ROWS, key=lambda row: row["id"]), arms, split="smoke")
            print(f"Smoke: {sum(r['parse_status']=='ok' for r in records)}/{len(records)} parseable; inspect actual responses in the run directory.")
            if structured and any(r["parse_status"] != "ok" for r in records):
                raise ValueError("Smoke incomplete or invalid; formal run blocked")
        else:
            datasets = DATASETS if args.dataset == "all" else (args.dataset,)
            if structured:
                gate = verify_smoke(config, fingerprint, SMOKE_ROWS)
                frozen_json(session.directory / "smoke_gate.json", gate)
                for arm in arms:
                    for dataset in datasets:
                        session.run(dataset, load_pilot(config, dataset), (arm,))
            else:
                for dataset in datasets:
                    session.run(dataset, load_pilot(config, dataset), arms)
        return 0
    except KeyboardInterrupt:
        print("Interrupted; committed per-item records are preserved. Rerun the same command to resume.", file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
