"""Generate or verify the frozen benchmark split from any working directory."""

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ab_factcheck.splitting import build_artifacts, inside, write_artifacts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/data_split.json")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Verify source hashes and all frozen artifacts without writing")
    mode.add_argument("--overwrite", action="store_true", help="Explicitly replace conflicting generated artifacts")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        output = inside(ROOT, config["output_dir"])
        raw_root = (ROOT / "data/raw").resolve()
        if output.is_relative_to(raw_root) or raw_root.is_relative_to(output):
            raise ValueError("output_dir must be separate from data/raw")
        artifacts, report = build_artifacts(ROOT, config)
        write_artifacts(output, artifacts, check=args.check, overwrite=args.overwrite)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("Verified frozen split." if args.check else "Split artifacts are ready.")
    for dataset, details in report["datasets"].items():
        dev, test = details["dev"], details["test"]
        print(f"{dataset}: dev={dev['rows']} rows/{dev['groups']} groups; "
              f"test={test['rows']} rows/{test['groups']} groups "
              f"({details['actual_test_fraction']:.2%} of rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
