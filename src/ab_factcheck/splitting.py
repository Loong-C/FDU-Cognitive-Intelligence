"""Deterministic, mechanism-stratified group holdout using only the standard library."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path


LABELS = ("SUPPORTS", "REFUTES", "NOT ENOUGH INFO")
REQUIRED_FIELDS = (
    "id", "group", "claim", "evidence", "label", "mechanism", "source_title",
)
ALGORITHM = "mechanism_group_hash_candidates_v1"


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def input_key(row: dict) -> tuple[str, str]:
    return row["claim"].strip(), row["evidence"].strip()


def read_records(path: Path) -> list[dict]:
    rows = []
    ids = set()
    inputs = set()
    with path.open(encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            for key in REQUIRED_FIELDS:
                if not isinstance(row.get(key), str) or not row[key].strip():
                    raise ValueError(f"{path}:{line_number}: missing/empty string field {key}")
            if row["label"] not in LABELS:
                raise ValueError(f"{path}:{line_number}: invalid label {row['label']!r}")
            if row["id"] in ids:
                raise ValueError(f"{path}:{line_number}: duplicate id {row['id']}")
            if input_key(row) in inputs:
                raise ValueError(f"{path}:{line_number}: duplicate claim/evidence pair")
            ids.add(row["id"])
            inputs.add(input_key(row))
            rows.append(row)
    if not rows:
        raise ValueError(f"{path}: empty dataset")
    return rows


def split_records(
    rows: list[dict], *, dataset: str, seed: int, test_fraction: float, candidates: int,
) -> tuple[list[dict], list[dict]]:
    """Keep groups intact; choose balanced test groups independently per mechanism.

    For each mechanism, round its group count * test_fraction half up, bounded
    to keep at least one group on each side. Rank groups using seeded SHA-256
    candidates, then select the candidate closest to the requested row and
    per-label fractions. No model outputs or evaluation scores are consulted.
    """
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be strictly between 0 and 1")
    if not isinstance(candidates, int) or candidates < 1:
        raise ValueError("candidates must be a positive integer")
    if not rows:
        raise ValueError("Cannot split an empty dataset")
    groups = defaultdict(list)
    for row in rows:
        groups[row["group"]].append(row)
    strata = defaultdict(list)
    for group, members in sorted(groups.items()):
        mechanisms = {row["mechanism"] for row in members}
        if len(mechanisms) != 1:
            raise ValueError(f"Group {group} contains multiple mechanisms")
        strata[next(iter(mechanisms))].append(group)

    test_groups = set()
    for mechanism, group_ids in sorted(strata.items()):
        if len(group_ids) < 2:
            raise ValueError(f"Mechanism {mechanism} needs at least two groups")
        test_count = min(len(group_ids) - 1, max(1, math.floor(len(group_ids) * test_fraction + 0.5)))
        counts = {group: Counter(row["label"] for row in groups[group]) for group in group_ids}
        totals = sum(counts.values(), Counter())
        total_rows = sum(totals.values())
        best = None
        for attempt in range(candidates):
            def rank(group: str) -> str:
                key = json.dumps([seed, dataset, mechanism, attempt, group], ensure_ascii=False)
                return sha256(key.encode("utf-8"))

            chosen = tuple(sorted(sorted(group_ids, key=rank)[:test_count]))
            selected = sum((counts[group] for group in chosen), Counter())
            score = (sum(selected.values()) / total_rows - test_fraction) ** 2
            score += sum(
                (selected[label] / totals[label] - test_fraction) ** 2
                for label in LABELS if totals[label]
            )
            candidate = (score, chosen)
            if best is None or candidate < best:
                best = candidate
        test_groups.update(best[1])

    dev = sorted((row for row in rows if row["group"] not in test_groups), key=lambda row: row["id"])
    test = sorted((row for row in rows if row["group"] in test_groups), key=lambda row: row["id"])
    return dev, test


def statistics(rows: list[dict]) -> dict:
    return {
        "rows": len(rows),
        "groups": len({row["group"] for row in rows}),
        "labels": {label: sum(row["label"] == label for row in rows) for label in LABELS},
        "mechanisms": dict(sorted(Counter(row["mechanism"] for row in rows).items())),
        "human_review_status": dict(sorted(Counter(row.get("human_review_status", "missing") for row in rows).items())),
        "evidence_condition": dict(sorted(Counter(row.get("evidence_condition", "unspecified") for row in rows).items())),
    }


def validate_partition(rows: list[dict], dev: list[dict], test: list[dict]) -> dict:
    original = {row["id"]: row for row in rows}
    combined = dev + test
    checks = {
        "nonempty_splits": bool(dev and test),
        "unique_ids": len({row["id"] for row in combined}) == len(combined),
        "complete_coverage": len(combined) == len(rows) and {row["id"] for row in combined} == set(original),
        "unchanged_records": all(original.get(row["id"]) == row for row in combined),
        "no_group_overlap": not ({row["group"] for row in dev} & {row["group"] for row in test}),
        "no_input_pair_overlap": not ({input_key(row) for row in dev} & {input_key(row) for row in test}),
        "all_labels_in_both": all({row["label"] for row in subset} == set(LABELS) for subset in (dev, test)),
        "all_mechanisms_in_both": all(
            {row["mechanism"] for row in subset} == {row["mechanism"] for row in rows}
            for subset in (dev, test)
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"Split validation failed: {[key for key, passed in checks.items() if not passed]}")
    overlaps = {
        field: len({row[field].strip() for row in dev} & {row[field].strip() for row in test})
        for field in ("claim", "evidence", "source_title")
    }
    return {"checks": checks, "shared_values_between_dev_and_test": overlaps}


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if path == root.resolve() or not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path must stay inside the repository: {relative}")
    return path


def build_artifacts(root: Path, config: dict) -> tuple[dict[str, bytes], dict]:
    if config.get("version") != 1:
        raise ValueError("Unsupported split configuration version")
    artifacts = {}
    report = {
        "algorithm": ALGORITHM,
        "configuration": config,
        "model_input_fields": ["claim", "evidence"],
        "datasets": {},
    }
    all_dev, all_test = [], []
    for dataset, source in sorted(config["datasets"].items()):
        if not dataset.isascii() or not dataset.replace("_", "").isalnum():
            raise ValueError(f"Invalid dataset name: {dataset}")
        path = inside(root, source["path"])
        if sha256(path.read_bytes()) != source["sha256"]:
            raise ValueError(f"Raw source checksum changed: {source['path']}")
        rows = read_records(path)
        if len(rows) != source["rows"] or len({row["group"] for row in rows}) != source["groups"]:
            raise ValueError(f"Unexpected row/group count: {source['path']}")
        dev, test = split_records(
            rows, dataset=dataset, seed=config["seed"],
            test_fraction=config["test_fraction"], candidates=config["candidates"],
        )
        audit = validate_partition(rows, dev, test)
        all_dev.extend(dev)
        all_test.extend(test)
        files = {}
        for split, subset in (("dev", dev), ("test", test)):
            relative = f"{dataset}/{split}.jsonl"
            content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in subset).encode("utf-8")
            artifacts[relative] = content
            files[relative] = sha256(content)
        assignments = [
            {"id": row["id"], "group": row["group"], "mechanism": row["mechanism"], "split": split}
            for split, subset in (("dev", dev), ("test", test)) for row in subset
        ]
        artifacts[f"{dataset}/manifest.json"] = json_bytes({
            "dataset": dataset,
            "source": source,
            "assignments": sorted(assignments, key=lambda row: row["id"]),
            "output_sha256": files,
        })
        report["datasets"][dataset] = {
            "source": statistics(rows), "dev": statistics(dev), "test": statistics(test),
            "actual_test_fraction": len(test) / len(rows),
            "by_mechanism": {
                mechanism: {
                    name: statistics([row for row in subset if row["mechanism"] == mechanism])
                    for name, subset in (("source", rows), ("dev", dev), ("test", test))
                }
                for mechanism in sorted({row["mechanism"] for row in rows})
            },
            **audit,
        }
    report["global_validation"] = validate_partition(all_dev + all_test, all_dev, all_test)
    report["notes"] = [
        "Basic and challenge must be evaluated separately; do not combine them into one score.",
        "Dev is for development and tuning. Freeze test until final evaluation.",
        "Only claim and evidence are model inputs; labels and management fields are not inputs.",
        "Basic review status is pending in the original data; it has not been changed or independently adjudicated.",
        "Checks cover exact/trimmed matches and supplied groups, not semantic similarity or pretraining contamination.",
    ]
    artifacts["report.json"] = json_bytes(report)
    return artifacts, report


def write_artifacts(output: Path, artifacts: dict[str, bytes], *, check: bool = False, overwrite: bool = False) -> None:
    mismatches = [
        name for name, content in artifacts.items()
        if not (output / name).is_file() or (output / name).read_bytes() != content
    ]
    if check:
        if mismatches:
            raise ValueError(f"Missing or modified split artifacts: {', '.join(mismatches)}")
        return
    conflicts = [name for name in mismatches if (output / name).exists()]
    if conflicts and not overwrite:
        raise ValueError(
            "Existing split artifacts differ. Use a new output_dir for a new split version, "
            "or explicitly pass --overwrite. Conflicts: " + ", ".join(conflicts)
        )
    for name in mismatches:
        target = inside(output, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifacts[name])
