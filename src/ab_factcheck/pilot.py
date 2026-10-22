"""Choose a frozen pilot inside the existing development split only."""

from collections import Counter, defaultdict
from itertools import combinations
import json

from .common import DATASETS, LABELS, ROOT, file_hash, frozen_json, json_bytes, read_jsonl, sha256
from .splitting import build_artifacts, statistics, write_artifacts


def choose_pilot(rows: list[dict], dataset: str, seed: int) -> list[dict]:
    quota = {"challenge": 2, "basic": 1}[dataset]
    strata = defaultdict(lambda: defaultdict(list))
    for row in rows:
        strata[row["mechanism"]][row["group"]].append(row)
    chosen = []
    for mechanism, groups in sorted(strata.items()):
        if len(groups) < quota:
            raise ValueError(f"Not enough groups for {dataset}/{mechanism}")
        full = [row for members in groups.values() for row in members]
        totals = Counter(row["label"] for row in full)
        ranked = []
        for group_ids in combinations(sorted(groups), quota):
            candidate = [row for group in group_ids for row in groups[group]]
            counts = Counter(row["label"] for row in candidate)
            missing = sum(totals[label] > 0 and counts[label] == 0 for label in LABELS)
            discrepancy = sum((counts[label] / len(candidate) - totals[label] / len(full)) ** 2 for label in LABELS)
            tie = sha256(json.dumps([seed, dataset, mechanism, group_ids]).encode())
            ranked.append(((missing, discrepancy, tie), candidate))
        chosen.extend(min(ranked, key=lambda item: item[0])[1])
    if {row["label"] for row in chosen} != set(LABELS):
        raise ValueError("Pilot lacks a label; use a new documented selection version")
    return sorted(chosen, key=lambda row: row["id"])


def prepare(config: dict) -> dict:
    if config.get("output_protocol") == "json_schema_v2":
        return reuse_pilot(config)
    split_config = json.loads((ROOT / "configs/data_split.json").read_text(encoding="utf-8"))
    artifacts, _ = build_artifacts(ROOT, split_config)
    write_artifacts(ROOT / split_config["output_dir"], artifacts, check=True)
    summary = {}
    for dataset in DATASETS:
        base = ROOT / "data/splits" / config["split_version"] / dataset
        dev = read_jsonl(base / "dev.jsonl")
        test = read_jsonl(base / "test.jsonl")
        rows = choose_pilot(dev, dataset, config["pilot_seed"])
        selected = {row["id"] for row in rows}
        groups = {row["group"] for row in rows}
        if groups & {row["group"] for row in test}:
            raise ValueError("Pilot overlaps test groups")
        if {row["id"] for row in dev if row["group"] in groups} != selected:
            raise ValueError("Pilot contains a partial group")
        manifest = {
            "version": 1,
            "algorithm": "mechanism_label_coverage_distribution_hash_v1",
            "dataset": dataset, "seed": config["pilot_seed"], "parent_split": "dev",
            "dev_sha256": file_hash(base / "dev.jsonl"),
            "test_sha256": file_hash(base / "test.jsonl"),
            "raw_sha256": split_config["datasets"][dataset]["sha256"],
            "statistics": statistics(rows),
            "development_rest_statistics": statistics([r for r in dev if r["id"] not in selected]),
            "assignments": [
                {"id": r["id"], "group": r["group"], "mechanism": r["mechanism"],
                 "label": r["label"], "parent_split": "dev", "is_pilot": r["id"] in selected}
                for r in sorted(dev, key=lambda r: r["id"])
            ],
        }
        frozen_json(ROOT / config["pilot_dir"] / f"{dataset}_manifest.json", manifest)
        summary[dataset] = manifest["statistics"]
    return summary


def reuse_pilot(config: dict) -> dict:
    """Validate the existing frozen selection, without running the sampler again."""
    summary = {}
    for dataset in DATASETS:
        path = ROOT / config["pilot_dir"] / f"{dataset}_manifest.json"
        reference = config["pilot_reference"][dataset]
        if file_hash(path) != reference["manifest_sha256"]:
            raise ValueError("Historical pilot manifest changed")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        rows = load_pilot(config, dataset)
        if len(rows) != reference["n"] or sha256(json_bytes([r["id"] for r in rows])) != reference["ordered_ids_sha256"]:
            raise ValueError("Historical pilot IDs/order changed")
        base = ROOT / "data/splits" / config["split_version"] / dataset
        if file_hash(base / "test.jsonl") != manifest["test_sha256"]:
            raise ValueError("Sealed holdout file changed")
        dev = read_jsonl(base / "dev.jsonl")
        groups = {r["group"] for r in rows}
        if {r["id"] for r in dev if r["group"] in groups} != {r["id"] for r in rows}:
            raise ValueError("Partial pilot group")
        summary[dataset] = statistics(rows)
    return summary


def load_pilot(config: dict, dataset: str) -> list[dict]:
    manifest = json.loads((ROOT / config["pilot_dir"] / f"{dataset}_manifest.json").read_text(encoding="utf-8"))
    path = ROOT / "data/splits" / config["split_version"] / dataset / "dev.jsonl"
    if file_hash(path) != manifest["dev_sha256"]:
        raise ValueError("Development split changed")
    ids = {r["id"] for r in manifest["assignments"] if r["is_pilot"]}
    rows = [row for row in read_jsonl(path) if row["id"] in ids]
    if len(rows) != len(ids):
        raise ValueError("Missing pilot IDs")
    return sorted(rows, key=lambda row: row["id"])
