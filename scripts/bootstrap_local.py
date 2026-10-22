"""Download checksum-pinned public artifacts for the local experiment (no system install)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/runtime"
REVISION = "ae44f08e1392f39c0e474af10c3ff8355c8b6688"
MODEL_FILE = "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
ARTIFACTS = [
    {
        "name": "llama-b11669-bin-win-cuda-12.4-x64.zip",
        "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11669/llama-b11669-bin-win-cuda-12.4-x64.zip",
        "sha256": "c2da1f73ed176ae093ac5aceb978a7b167a16113f6d74c6789eeaee2135cb8dc",
    },
    {
        "name": "cudart-llama-bin-win-cuda-12.4-x64.zip",
        "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11669/cudart-llama-bin-win-cuda-12.4-x64.zip",
        "sha256": "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
    },
    {
        "name": MODEL_FILE,
        "url": f"https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/{REVISION}/{MODEL_FILE}",
        "sha256": "2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e",
    },
]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(item: dict) -> Path:
    target = OUT / item["name"]
    if target.exists():
        if digest(target) != item["sha256"]:
            raise RuntimeError(f"Existing file checksum mismatch: {target.name}")
        print(f"Verified existing {target.name}", flush=True)
        return target
    temporary = target.with_suffix(target.suffix + ".partial")
    for attempt in range(3):
        try:
            offset = temporary.stat().st_size if temporary.exists() else 0
            headers = {"User-Agent": "ab-factcheck/0.1"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(item["url"], headers=headers)
            with urllib.request.urlopen(request, timeout=90) as response:
                resume = offset > 0 and response.status == 206
                if not resume:
                    offset = 0
                total = offset + int(response.headers.get("Content-Length", 0))
                mode = "ab" if resume else "wb"
                last_print = 0.0
                with temporary.open(mode) as output:
                    while chunk := response.read(4 * 1024 * 1024):
                        output.write(chunk)
                        offset += len(chunk)
                        if time.monotonic() - last_print > 15:
                            print(f"{target.name}: {offset / 1e6:.0f}/{total / 1e6:.0f} MB", flush=True)
                            last_print = time.monotonic()
            if digest(temporary) != item["sha256"]:
                raise ValueError(f"Downloaded checksum mismatch: {target.name}")
            temporary.replace(target)
            print(f"Downloaded and verified {target.name}", flush=True)
            return target
        except (OSError, TimeoutError) as exc:
            if attempt == 2:
                raise
            print(f"Download retry: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(2 ** attempt)
    raise RuntimeError("Download did not complete")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for item in ARTIFACTS:
        path = download(item)
        if path.suffix == ".zip":
            destination = (OUT / "llama-b11669").resolve()
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if not (destination / name).resolve().is_relative_to(destination):
                        raise ValueError(f"Unsafe archive entry: {name}")
                archive.extractall(destination)
    manifest = {"model_revision": REVISION, "backend_release": "b11669", "artifacts": ARTIFACTS}
    (OUT / "artifacts.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("Local runtime assets are ready.", flush=True)


if __name__ == "__main__":
    main()
