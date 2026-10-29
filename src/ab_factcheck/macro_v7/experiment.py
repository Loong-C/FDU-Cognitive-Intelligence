"""Frozen, resumable dev-only experiments. No test path is implemented here."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path

from ..common import ROOT, atomic_json, file_hash, frozen_json, now, read_jsonl
from ..groq_client import GroqStop, exclusive, load_local_key
from ..symbolic_z3.client import SymbolicClient
from ..worlds_v5.client import Halt
from .inference import ARMS, digest, messages, parse, schema

EXPERIMENT = "experiments/007_macro_inference"
OUTPUT = "outputs/macro_v7"
CONFIG = "configs/experiment_macro_v7.json"


def load_dev(dataset, root=ROOT):
    if dataset not in ("basic", "challenge"):
        raise ValueError("Only the frozen development datasets are accepted")
    return read_jsonl(root / f"data/splits/v1/{dataset}/dev.jsonl")


def source_hashes(root=ROOT):
    paths = [CONFIG, "src/ab_factcheck/macro_v7/inference.py", "src/ab_factcheck/macro_v7/experiment.py",
             "src/ab_factcheck/symbolic_z3/client.py", "src/ab_factcheck/groq_client.py",
             "src/ab_factcheck/worlds_v5/client.py", "src/ab_factcheck/worlds_v5_continuation.py",
             "src/ab_factcheck/model_client.py", "src/ab_factcheck/common.py", "src/ab_factcheck/structured.py",
             "prompts/v2/A2_system.txt", "prompts/v2/A2_user.txt"]
    paths += [p.relative_to(root).as_posix() for p in sorted((root / "prompts/v7").glob("*.txt"))]
    paths += [f"data/splits/v1/{d}/dev.jsonl" for d in ("basic", "challenge")]
    return {p: file_hash(root / p) for p in paths}


def choose_rows(phase, seed, groups_per_mechanism, root=ROOT):
    if phase == "scout":
        selection = json.loads((root / "experiments/006_symbolic_z3/selection.json").read_text(encoding="utf-8"))
        return [{k: r[k] for k in ("id", "dataset", "group", "mechanism", "claim", "evidence")} for r in selection["rows"]]
    old = json.loads((root / "experiments/005_layered_worlds/fresh_dev_v5.json").read_text(encoding="utf-8"))
    selected = []
    for dataset in ("basic", "challenge"):
        pilot = json.loads((root / f"experiments/001_two_world_pilot/pilot/{dataset}_manifest.json").read_text(encoding="utf-8"))
        excluded = {r["group"] for r in pilot["assignments"] if r["is_pilot"]}
        excluded |= {r["group"] for r in old["datasets"][dataset]["rows"]}
        # Each new confirmatory stage excludes every group used in preceding v7 stages.
        for p in sorted((root / EXPERIMENT).glob("*/manifest.json")):
            if p.parent.name != phase:
                excluded |= {r["group"] for r in json.loads(p.read_text(encoding="utf-8"))["rows"] if r["dataset"] == dataset}
        by_mechanism = defaultdict(lambda: defaultdict(list))
        for r in load_dev(dataset, root):
            if r["group"] not in excluded:
                by_mechanism[r["mechanism"]][r["group"]].append(r)
        if len(by_mechanism) != 7:
            raise ValueError("Insufficient fresh development mechanisms")
        for mechanism, groups in sorted(by_mechanism.items()):
            ranking = sorted(groups, key=lambda g: (digest([seed, dataset, mechanism, g]), g))
            if len(ranking) < groups_per_mechanism:
                raise ValueError("Insufficient fresh development groups")
            for group in ranking[:groups_per_mechanism]:
                selected += [{k: r[k] for k in ("id", "group", "mechanism", "claim", "evidence")} | {"dataset": dataset}
                             for r in sorted(groups[group], key=lambda r: r["id"])]
    return selected


def freeze(phase, arms, groups_per_mechanism=1, root=ROOT):
    if not phase or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in phase):
        raise ValueError("Invalid stage name")
    if not arms or any(a not in ARMS for a in arms) or len(set(arms)) != len(arms):
        raise ValueError("Invalid arms")
    config = json.loads((root / CONFIG).read_text(encoding="utf-8"))
    rows = choose_rows(phase, config["seed"], groups_per_mechanism, root)
    manifest = {"phase": phase, "arms": arms, "rows": rows, "seed": config["seed"],
                "groups_per_mechanism": groups_per_mechanism, "test_access": False,
                "purpose": "historical exploratory development" if phase == "scout" else "new group-separated development validation",
                "input_fields": ["claim", "evidence"]}
    directory = root / EXPERIMENT / phase
    frozen_json(directory / "manifest.json", manifest)
    frozen_json(directory / "freeze.json", {"manifest_sha256": file_hash(directory / "manifest.json"),
                                            "source_sha256": source_hashes(root), "config": config})
    print(json.dumps({"frozen": phase, "n": len(rows), "arms": arms, "groups": len({(r['dataset'],r['group']) for r in rows})}), flush=True)


def verify(phase, root=ROOT):
    directory = root / EXPERIMENT / phase
    f = json.loads((directory / "freeze.json").read_text(encoding="utf-8"))
    if file_hash(directory / "manifest.json") != f["manifest_sha256"]:
        raise GroqStop("Manifest integrity mismatch")
    for path, expected in f["source_sha256"].items():
        if file_hash(root / path) != expected:
            raise GroqStop("Frozen source changed: " + path)
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8")), f


def receive(client, destination, request, freeze_hash):
    request_hash = digest(request)
    if destination.exists():
        record = json.loads(destination.read_text(encoding="utf-8"))
        expected = digest({k: v for k, v in record.items() if k != "record_sha256"})
        if record["record_sha256"] != expected or record["request_sha256"] != request_hash or record["freeze_sha256"] != freeze_hash:
            raise GroqStop("Cached response integrity mismatch")
        return record
    inflight = destination.with_suffix(".inflight")
    if inflight.exists():
        raise GroqStop("Ambiguous unfinished request; refusing automatic regeneration")
    frozen_json(inflight, {"request_sha256": request_hash, "started": now()})
    try:
        record = client.complete(**request)
    except Halt as exc:
        atomic_json(destination.with_suffix(".error.json"), {"at": now(), "message": str(exc),
            "retryable": exc.retryable, "ambiguous": exc.ambiguous, "attempts": client.last_attempts})
        if not exc.ambiguous:
            inflight.unlink()
        raise
    record.update(request_sha256=request_hash, freeze_sha256=freeze_hash)
    record["record_sha256"] = digest(record)
    frozen_json(destination, record)
    inflight.unlink()
    return record


def run(phase, max_new=None, root=ROOT):
    manifest, f = verify(phase, root)
    config = f["config"]
    load_local_key(root)
    client = SymbolicClient(config["model"], root / "outputs/groq/quota.json", config["quota_policy"], free_plan_confirmed=True)
    directory = root / OUTPUT / phase
    count, reused = 0, 0
    receipt = {"started": now(), "phase": phase}
    try:
        with exclusive(directory / "run.lock"):
            # Sample-major execution keeps every partial prefix paired.
            for index, row in enumerate(manifest["rows"]):
                for arm in manifest["arms"]:
                    destination = directory / "records" / row["dataset"] / row["id"] / (arm + ".json")
                    cached = destination.exists()
                    if not cached and max_new is not None and count >= max_new:
                        receipt["status"] = "bounded_execution_stop"
                        return
                    request = {"messages": messages(arm, claim=row["claim"], evidence=row["evidence"], root=root),
                               "response_format": schema(arm),
                               "max_completion_tokens": 1024 if arm == "baseline" else config["candidate_completion_limit"]}
                    record = receive(client, destination, request, digest(f))
                    count += int(not cached)
                    reused += int(cached)
                    parsed = parse(arm, record)
                    if record["provider_validation_issues"]:
                        raise GroqStop("Provider protocol failure; response retained")
                    print(json.dumps({"item": index + 1, "total": len(manifest["rows"]), "arm": arm,
                                      "cached": cached, "label": parsed["label"], "tokens": record["usage"]["total_tokens"]}), flush=True)
            receipt["status"] = "complete"
    except (GroqStop, KeyboardInterrupt) as exc:
        receipt.update(status="stopped", reason=str(exc), error_type=type(exc).__name__)
        print(json.dumps(receipt), flush=True)
    finally:
        receipt.update(ended=now(), new_responses=count, reused_responses=reused, new_http_attempts=client.new_attempts)
        atomic_json(directory / "last_execution.json", receipt)
        client.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("freeze", "run"))
    p.add_argument("--phase", default="scout")
    p.add_argument("--arms", nargs="+", choices=ARMS, default=["nli", "certificate", "dual"])
    p.add_argument("--groups-per-mechanism", type=int, default=1)
    p.add_argument("--max-new", type=int)
    a = p.parse_args()
    if a.command == "freeze":
        freeze(a.phase, a.arms, a.groups_per_mechanism)
    else:
        run(a.phase, a.max_new)


if __name__ == "__main__":
    main()
