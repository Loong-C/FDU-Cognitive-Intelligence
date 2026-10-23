"""Re-run the unchanged v2 auditor in an isolated snapshot without rewriting history."""

import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    destination = (args.destination or ROOT/"outputs"/("legacy-v2-reaudit-"+str(time.time_ns()))).resolve()
    if not destination.is_relative_to((ROOT/"outputs").resolve()) or destination.exists():
        raise ValueError("Use a new isolated directory inside outputs")
    baseline=json.loads((ROOT/"experiments/003_model_scaling_14b/historical_baseline.json").read_text(encoding="utf-8"))
    archive=subprocess.check_output(["git","archive","--format=zip",baseline["base_commit"]],cwd=ROOT)
    destination.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        for name in source.namelist():
            if not (destination/name).resolve().is_relative_to(destination):
                raise ValueError("Unsafe archived path")
        source.extractall(destination)
    for name in baseline["sha256"]:
        source=ROOT/name; target=(destination/name).resolve()
        if not target.is_relative_to(destination):raise ValueError("Unsafe baseline path")
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():target.unlink()
        # Only large immutable model/runtime assets are linked; mutable reports,
        # logs and metadata are copied so the old auditor cannot alter originals.
        if source.stat().st_size>16*1024**2 and source.suffix.lower() in (".gguf",".dll",".zip"):
            os.link(source,target)
        else:
            shutil.copyfile(source,target)
    with (destination/"reaudit.log").open("w",encoding="utf-8") as log:
        result=subprocess.run([sys.executable,str(destination/"scripts/audit_structured_run.py"),"--config",str(destination/"configs/experiment_v2.json")],
                              cwd=destination,stdout=log,stderr=subprocess.STDOUT)
    print(f"Isolated legacy audit: {destination}; exit={result.returncode}")
    if result.returncode:
        print((destination/"reaudit.log").read_text(encoding="utf-8",errors="replace"))
        raise SystemExit(result.returncode)
    report=destination/"experiments/002_constrained_output/reports/pilot_qwen3_4b_q4_struct_v2_r2/execution_audit.json"
    final=ROOT/"experiments/003_model_scaling_14b/legacy_v2_reaudit.json"
    data=json.loads(report.read_text(encoding="utf-8"))
    data["isolated_snapshot_directory"]=str(destination)
    data["historical_repository_commit"]=baseline["base_commit"]
    final.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+"\n").encode("utf-8"))
    print(f"Legacy evidence copied to {final}")


if __name__=="__main__":main()
