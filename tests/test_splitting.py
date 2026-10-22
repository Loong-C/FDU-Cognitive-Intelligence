"""Regression checks for leakage, reproducibility and frozen-data integrity."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ab_factcheck.splitting import (  # noqa: E402
    LABELS, build_artifacts, read_records, split_records, validate_partition, write_artifacts,
)


def sample_rows() -> list[dict]:
    return [
        {
            "id": f"{mechanism}-{group}-{label_index}",
            "group": f"{mechanism}-{group}",
            "mechanism": mechanism,
            "label": label,
            "claim": f"claim {mechanism}-{group}-{label_index}",
            "evidence": f"evidence {mechanism}-{group}-{label_index}",
            "source_title": f"source {mechanism}-{group}",
        }
        for mechanism in ("A", "B") for group in range(10)
        for label_index, label in enumerate(LABELS)
    ]


def split(rows: list[dict], **overrides) -> tuple[list[dict], list[dict]]:
    options = {"dataset": "fixture", "seed": 42, "test_fraction": 0.2, "candidates": 32}
    options.update(overrides)
    return split_records(rows, **options)


class SplitTests(unittest.TestCase):
    def test_group_holdout_is_complete_and_preserves_records(self):
        rows = sample_rows()
        dev, test = split(rows)
        audit = validate_partition(rows, dev, test)
        self.assertTrue(all(audit["checks"].values()))
        self.assertEqual(len(test), 12)
        self.assertEqual({row["mechanism"] for row in test}, {"A", "B"})

    def test_same_seed_is_independent_of_input_order(self):
        self.assertEqual(split(sample_rows()), split(list(reversed(sample_rows()))))

    def test_rejects_row_wise_split_that_leaks_groups(self):
        rows = sample_rows()
        with self.assertRaisesRegex(ValueError, "no_group_overlap"):
            validate_partition(rows, rows[::2], rows[1::2])

    def test_rejects_lost_or_changed_records(self):
        rows = sample_rows()
        dev, test = split(rows)
        with self.assertRaisesRegex(ValueError, "complete_coverage"):
            validate_partition(rows, dev[:-1], test)
        changed = [{**dev[0], "claim": "changed"}, *dev[1:]]
        with self.assertRaisesRegex(ValueError, "unchanged_records"):
            validate_partition(rows, changed, test)

    def test_rejects_bad_ratio_and_unsplittable_stratum(self):
        for fraction in (0, 1, -0.1, 1.1):
            with self.assertRaises(ValueError):
                split(sample_rows(), test_fraction=fraction)
        with self.assertRaisesRegex(ValueError, "at least two groups"):
            split(sample_rows()[:3])
        rows = sample_rows()
        rows[0]["mechanism"] = "different"
        with self.assertRaisesRegex(ValueError, "multiple mechanisms"):
            split(rows)

    def test_reader_rejects_duplicate_ids_inputs_and_bad_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.jsonl"
            first, second = sample_rows()[:2]
            for bad_row, message in (
                ({**second, "id": first["id"]}, "duplicate id"),
                ({**second, "claim": first["claim"], "evidence": first["evidence"]}, "duplicate claim/evidence"),
                ({**second, "label": "INVALID"}, "invalid label"),
            ):
                path.write_text("\n".join(json.dumps(row) for row in (first, bad_row)), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    read_records(path)

    def test_existing_artifact_requires_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            write_artifacts(output, {"dev.jsonl": b"original\n"})
            with self.assertRaisesRegex(ValueError, "Existing split artifacts differ"):
                write_artifacts(output, {"dev.jsonl": b"changed\n"})
            self.assertEqual((output / "dev.jsonl").read_bytes(), b"original\n")
            with self.assertRaisesRegex(ValueError, "Missing or modified"):
                write_artifacts(output, {"dev.jsonl": b"changed\n"}, check=True)

    def test_real_benchmark_matches_frozen_artifacts(self):
        config = json.loads((ROOT / "configs/data_split.json").read_text(encoding="utf-8"))
        artifacts, report = build_artifacts(ROOT, config)
        write_artifacts(ROOT / config["output_dir"], artifacts, check=True)
        self.assertEqual(sum(item["source"]["rows"] for item in report["datasets"].values()), 1785)
        self.assertTrue(all(report["global_validation"]["checks"].values()))


if __name__ == "__main__":
    unittest.main()
