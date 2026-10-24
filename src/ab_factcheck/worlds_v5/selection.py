"""Deterministic complete-group development selection; never open test rows."""
from collections import Counter, defaultdict
import json

from ..common import DATASETS, file_hash, frozen_json, read_jsonl
from .orchestrator import digest

SEED = 20261024


def select(root):
    # Exclude the union of pilot groups across both datasets, not just selected IDs.
    old = {d: json.loads((root / f"experiments/001_two_world_pilot/pilot/{d}_manifest.json").read_text(encoding="utf-8")) for d in DATASETS}
    excluded = {r["group"] for m in old.values() for r in m["assignments"] if r["is_pilot"]}
    result = {"seed": SEED, "algorithm": "one_complete_group_per_mechanism_ranked_by_sha256_seed_dataset_mechanism_group",
              "excluded_pilot_groups": sorted(excluded), "selection_uses_predictions": False,
              "source_sha256": {}, "datasets": {}, "execution_order": []}
    for dataset in DATASETS:
        relative = f"data/splits/v1/{dataset}/dev.jsonl"
        rows = read_jsonl(root / relative)
        result["source_sha256"][relative] = file_hash(root / relative)
        pilot = f"experiments/001_two_world_pilot/pilot/{dataset}_manifest.json"
        result["source_sha256"][pilot] = file_hash(root / pilot)
        groups = defaultdict(list)
        for row in rows:
            if row["group"] not in excluded:
                groups[row["group"]].append(row)
        if any(len({r["mechanism"] for r in rs}) != 1 for rs in groups.values()):
            raise ValueError("A group spans mechanisms; selection protocol needs a new version")
        mechanisms = sorted({r["mechanism"] for r in rows})
        selected, ranking = [], {}
        for mechanism in mechanisms:
            candidates = [g for g, rs in groups.items() if rs[0]["mechanism"] == mechanism]
            candidates.sort(key=lambda g: digest([SEED, dataset, mechanism, g]))
            if not candidates:
                raise ValueError("No unused development group for mechanism " + mechanism)
            ranking[mechanism] = candidates
            # No label-based or model-result-based optimization of the winning group.
            selected.extend(sorted(groups[candidates[0]], key=lambda r: r["id"]))
            result["execution_order"].append({"dataset": dataset, "group": candidates[0],
                                              "mechanism": mechanism,
                                              "ids": [r["id"] for r in sorted(groups[candidates[0]], key=lambda r: r["id"])]})
        result["datasets"][dataset] = {"rows": selected, "candidate_group_ranking": ranking,
            "group_count": len({r["group"] for r in selected}), "n": len(selected),
            "label_counts": dict(Counter(r["label"] for r in selected)),
            "mechanism_counts": dict(Counter(r["mechanism"] for r in selected)),
            "ordered_ids_sha256": digest([r["id"] for r in selected])}
    # Interleave datasets by mechanism index, keeping each group intact. All arms
    # use this same predeclared prefix if the quota stops the experiment early.
    result["execution_order"].sort(key=lambda g: (sorted(result["datasets"][g["dataset"]]["candidate_group_ranking"]).index(g["mechanism"]), g["dataset"]))
    return result


def freeze(root, path):
    manifest = select(root)
    frozen_json(path, manifest)
    return manifest
