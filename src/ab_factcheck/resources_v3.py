"""Windows resource measurements. GPU values are dedicated nvidia-smi memory."""

import ctypes
import json
import os
import shutil
import subprocess
import time

from .common import ROOT, now


def command(args, timeout=20):
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def powershell_json(code):
    return json.loads(command(["powershell.exe", "-NoProfile", "-Command", code + " | ConvertTo-Json -Depth 5 -Compress"]))


def snapshot(*, detailed=False):
    if os.name != "nt":
        raise RuntimeError("The v3 resource guard requires the target Windows host")
    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (key, ctypes.c_ulonglong) for key in ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]
    status = Memory(); status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    gpu_text = command(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,driver_version", "--format=csv,noheader,nounits"])
    gpu_rows = []
    for line in gpu_text.splitlines():
        index, name, total, used, free, utilization, driver = [x.strip() for x in line.split(",")]
        gpu_rows.append(dict(index=int(index), name=name, total_mib=float(total), used_mib=float(used), free_mib=float(free), utilization_percent=float(utilization), driver=driver))
    result = dict(captured_at=now(), monotonic=time.monotonic(), available_ram_bytes=status.available,
                  total_ram_bytes=status.total, commit_limit_bytes=status.page_total, commit_available_bytes=status.page_available,
                  disk_free_bytes=shutil.disk_usage(ROOT).free, gpus=gpu_rows)
    if detailed:
        result["processes"] = powershell_json("@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'llama|python' } | Select-Object Name,ProcessId,ParentProcessId,CommandLine)")
        result["listeners"] = powershell_json("@(Get-NetTCPConnection -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess)")
    return result


def page_reads():
    data = powershell_json("Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory | Select-Object PageReadsPersec,PagesInputPersec,PagesOutputPersec")
    return {k: int(v) for k, v in data.items()}


def startup_issues(config, resources, gpu_layers):
    policy = config["deployment"]
    issues = []
    if not isinstance(gpu_layers, int) or not 0 < gpu_layers < 40:
        issues.append("Require partial offload: 1..39 of 40 transformer layers")
    if resources["available_ram_bytes"] < policy["min_available_ram_gib"] * 1024**3:
        issues.append(f"Available physical RAM below conservative cold-start threshold {policy['min_available_ram_gib']} GiB")
    # Conservative screening only; actual buffers and headroom must be measured.
    estimated = gpu_layers * (config["model"]["size_bytes"] / 40 / 1024**2 + 40) + 512
    if len(resources["gpus"]) != 1:
        issues.append("This configuration expects exactly one GPU")
    elif resources["gpus"][0]["free_mib"] < estimated + policy["min_free_vram_mib"]:
        issues.append(f"Estimated GPU allocation {estimated:.0f} MiB leaves insufficient dedicated VRAM reserve")
    if resources["disk_free_bytes"] < 2 * 1024**3:
        issues.append("Disk reserve below 2 GiB")
    return issues


def summarize(samples):
    if not samples:
        return {"samples": 0}
    return {"samples": len(samples), "gpu_peak_used_mib": max(s["gpus"][0]["used_mib"] for s in samples),
            "gpu_min_free_mib": min(s["gpus"][0]["free_mib"] for s in samples),
            "minimum_available_ram_gib": min(s["available_ram_bytes"] for s in samples) / 1024**3,
            "note": "Whole-device sampled peak, includes other applications; not a continuous or process-exclusive peak."}
