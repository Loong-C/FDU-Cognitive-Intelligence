"""Download the official pinned 14B artifact without changing the 4B runtime."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ab_factcheck.common import ROOT, atomic_json, file_hash, load_config, now


def download_verified(model, target):
    if target.exists():
        if target.stat().st_size != model["size_bytes"] or file_hash(target) != model["sha256"]:
            raise ValueError("Existing model differs; never overwrite it silently")
        return
    # Small independently range-checked chunks tolerate interrupted CDN streams.
    # No model inference concurrency is involved; only four download connections.
    chunks = target.parent / "download_chunks"
    chunks.mkdir(exist_ok=True)
    size = model["size_bytes"]
    chunk_size = 16 * 1024**2
    count = (size + chunk_size - 1) // chunk_size
    def fetch(index):
        begin = index * chunk_size
        end = min(size, begin + chunk_size) - 1
        path = chunks / f"{index:05d}.bin"
        if path.exists() and path.stat().st_size == end - begin + 1:
            return path
        partial = path.with_suffix(".partial")
        for attempt in range(5):
            try:
                offset = partial.stat().st_size if partial.exists() else 0
                start = begin + offset
                if start > end:
                    break
                req = urllib.request.Request(model["download_url"] + f"?download=true&range={start}-{end}",
                                             headers={"Range": f"bytes={start}-{end}", "User-Agent": "ab-factcheck-v3"})
                with urllib.request.urlopen(req, timeout=60) as response:
                    if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{size}":
                        raise ValueError("Server did not honor the exact requested byte range")
                    with partial.open("ab") as output:
                        while block := response.read(1024**2):
                            output.write(block)
                if partial.stat().st_size == end - begin + 1:
                    break
                raise OSError("Premature EOF; saved partial range for resume")
            except (OSError, TimeoutError) as exc:
                print(f"Range {index+1}/{count} retry {attempt+1}: {type(exc).__name__}", flush=True)
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        if partial.stat().st_size != end - begin + 1:
            raise ValueError("Chunk length mismatch")
        partial.replace(path)
        print(f"Verified byte range {index+1}/{count}", flush=True)
        return path
    with ThreadPoolExecutor(max_workers=4) as executor:
        paths = list(executor.map(fetch, range(count)))
    assembled = target.with_suffix(".assembled")
    h = hashlib.sha256()
    with assembled.open("wb") as output:
        for path in paths:
            with path.open("rb") as source:
                for block in iter(lambda: source.read(4 * 1024**2), b""):
                    h.update(block); output.write(block)
        output.flush(); os.fsync(output.fileno())
    if assembled.stat().st_size != size or h.hexdigest() != model["sha256"]:
        raise ValueError("Assembled model SHA-256/length mismatch; chunks retained")
    assembled.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/experiment_14b_v3.json")
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    model = config["model"]
    target = ROOT / model["file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    receipt = {"captured_at": now(), "status": "started"}
    try:
        url = f"https://huggingface.co/api/models/{model['repository']}/revision/{model['revision']}?blobs=true"
        with urllib.request.urlopen(url, timeout=45) as response:
            metadata = json.load(response)
        artifact = next(x for x in metadata["siblings"] if x["rfilename"] == target.name)
        if (metadata["sha"], artifact["size"], artifact["lfs"]["sha256"]) != (model["revision"], model["size_bytes"], model["sha256"]):
            raise ValueError("Official source differs from the pinned artifact")
        receipt.update(source_url=url, repository=model["repository"], revision=metadata["sha"],
                       artifact=artifact, license=metadata.get("cardData", {}).get("license"),
                       download_url=model["download_url"], disk_free_bytes=shutil.disk_usage(target.parent).free)
        atomic_json(target.parent / "source_metadata.json", receipt)
        if args.metadata_only:
            receipt["status"] = "metadata_verified_only"
        else:
            partial = target.with_suffix(target.suffix + ".partial")
            remaining = model["size_bytes"] - (partial.stat().st_size if partial.exists() else 0)
            if not target.exists() and shutil.disk_usage(target.parent).free < 2 * remaining + 2 * 1024**3:
                raise RuntimeError("Insufficient disk space for download plus 2 GiB reserve")
            download_verified(model, target)
            if target.stat().st_size != model["size_bytes"]:
                raise ValueError("Downloaded artifact length differs")
            receipt.update(status="downloaded_and_verified", local_sha256=file_hash(target), local_size_bytes=target.stat().st_size)
    except Exception as exc:
        receipt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        atomic_json(target.parent / ("deployment-" + str(time.time_ns()) + ".json"), receipt)
        atomic_json(target.parent / "deployment.json", receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
