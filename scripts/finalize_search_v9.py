"""Observe the existing V9 worker and audit/report it on completion; no API calls."""
import argparse
from collections import Counter
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import time

from ab_factcheck.common import ROOT, atomic_bytes, atomic_json, now
from audit_search_v9 import main as audit


def alive(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == 259
    finally:
        kernel.CloseHandle(handle)


def observe(pid):
    output = ROOT / "outputs/search_v9"
    directory = ROOT / "experiments/009_small_search"
    while True:
        state = json.loads((output / "pipeline.json").read_text(encoding="utf-8"))
        live = alive(pid)
        calls, tokens = Counter(), 0
        for path in (output / "records").glob("*/*/*.json"):
            if path.stem not in ("repeat_nli", "claim_first_nli", "reason_first_nli", "repeat_baseline", "baseline", "nli", "negative"):
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            calls[path.stem] += 1
            tokens += record["usage"]["total_tokens"]
        info = {"updated": now(), "worker_pid": pid, "worker_alive": live,
                "pipeline_status": state["status"], "unique_responses": sum(calls.values()),
                "actual_tokens": tokens, "calls_by_arm": dict(calls)}
        if state["status"] == "complete":
            try:
                audit()
            except Exception as exc:
                info.update(status="audit_failed", error_type=type(exc).__name__)
                atomic_json(output / "completion.json", info)
                raise
            info["status"] = "complete_and_audited"
            atomic_json(output / "completion.json", info)
            atomic_bytes(directory / "STATUS.md", ("# V9 状态\n\n实验与审计均已完成。参见 [结果报告](RESULTS.md) 和 [审计记录](audit.json)。\n").encode("utf-8"))
            return
        if state["status"] == "requires_inspection" or not live:
            info["status"] = "requires_inspection"
            atomic_json(output / "completion.json", info)
            atomic_bytes(directory / "STATUS.md", ("# V9 状态\n\n执行器已停止，需要检查后继续。现有响应保留，不自动重发不确定请求。\n").encode("utf-8"))
            return
        info["status"] = "observing"
        atomic_json(output / "completion.json", info)
        text = ("# V9 状态\n\n"
            f"更新：{info['updated']}。执行器状态：`{state['status']}`，进程仍运行。\n\n"
            f"已收到 {sum(calls.values())} 个唯一新响应，已用 {tokens:,} tokens。\n\n"
            "14 题初筛已完成：A27 为 basic 7/7、challenge 6/7；重复 NLI 和调整 NLI schema 字段顺序均为 7/7、7/7，两者晋级。初筛不足以证明泛化提升。\n\n"
            "仍按冻结流程进行 42 题扩展筛选及 28 道新开发题确认。Groq TPD 额度耗尽时按服务端等待时间恢复，只复用已收到的响应，不重复生成、不更换模型、不升级套餐。\n\n"
            "执行结束后自动核验原始响应、决策、指标、分组隔离及费用，生成 RESULTS.md 和 audit.json。若发生不确定传输失败则停止并保留现场。\n")
        atomic_bytes(directory / "STATUS.md", text.encode("utf-8"))
        time.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-pid", type=int, required=True)
    observe(parser.parse_args().worker_pid)
