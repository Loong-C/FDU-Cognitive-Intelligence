"""Offline audit and compact report for the frozen V9 staged comparison."""
from collections import Counter
import csv
from datetime import datetime
import json
from pathlib import Path
import re

from ab_factcheck.common import ROOT, LABELS, atomic_bytes, atomic_json, file_hash, now
from ab_factcheck.search_v9 import ARMS, EXP, OUT, checked, parsed, verify, rank


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def first_field(record):
    try:
        value = json.loads(record["raw_response"])
        return next(iter(value)) if isinstance(value, dict) and value else "INVALID_JSON_OBJECT"
    except (ValueError, TypeError):
        return "INVALID_JSON_OBJECT"


def independent_policy(method, predictions):
    if method.startswith("agree__"):
        alternative = predictions[method.removeprefix("agree__")]
        return alternative if alternative in LABELS and alternative == predictions["nli"] else predictions["baseline"]
    if method == "signed_v8":
        inverse = {"SUPPORTS": "REFUTES", "REFUTES": "SUPPORTS", "NOT ENOUGH INFO": "NOT ENOUGH INFO"}
        positive = predictions["nli"]
        return positive if positive in LABELS and positive == inverse.get(predictions.get("negative")) else predictions["baseline"]
    return predictions[method]


def main():
    plan, freeze = verify()
    directory = ROOT / EXP
    reports = {s: read(directory / s / "metrics.json") for s in ("pilot", "scout", "confirm")}
    assert all(r["complete"] for r in reports.values())
    shortlist = read(directory / "shortlist.json")
    selected = read(directory / "winner.json")
    winner = selected["method"]
    assert shortlist["pilot_metrics_sha256"] == file_hash(directory / "pilot/metrics.json")
    assert selected["scout_metrics_sha256"] == file_hash(directory / "scout/metrics.json")
    ranked = sorted(ARMS, key=lambda a: min(rank(reports["pilot"]["methods"][m]) for m in (a, "agree__" + a)))
    assert shortlist["arms"] == ranked[:2]
    eligible = ["nli", "signed_v8", *shortlist["arms"], *("agree__" + a for a in shortlist["arms"])]
    assert winner == min(eligible, key=lambda m: rank(reports["scout"]["methods"][m]))
    source = {}
    for dataset in ("basic", "challenge"):
        path = ROOT / f"data/splits/v1/{dataset}/dev.jsonl"
        assert file_hash(path) == freeze["source_sha256"][path.relative_to(ROOT).as_posix()]
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            source[dataset, row["id"]] = row
    lookup = {}
    for stage in ("pilot", "scout", "confirm"):
        assert len({(r["dataset"], r["id"]) for r in plan[stage]}) == len(plan[stage])
        for row in plan[stage]:
            key = row["dataset"], row["id"]
            assert set(row) == {"dataset", "id", "group", "mechanism", "claim", "evidence"}
            assert all(row[k] == source[key][k] for k in row if k != "dataset")
            lookup[key] = row
    groups = {(r["dataset"], r["group"]) for r in plan["confirm"]}
    assert len(groups) == 14 and not groups & {tuple(k) for k in plan["excluded_groups"]}
    assert set(Counter((r["dataset"], r["group"]) for r in plan["confirm"]).values()) == {2}
    for dataset, group in groups:
        assert plan["confirm_group_sizes"][f"{dataset}/{group}"]["available"] == sum(d == dataset and r["group"] == group for (d, _), r in source.items())
    raw, raw_hashes, calls, tokens = {}, {}, Counter(), Counter()
    confirm_keys = {(r["dataset"], r["id"]) for r in plan["confirm"]}
    pilot_keys = {(r["dataset"], r["id"]) for r in plan["pilot"]}
    for path in (ROOT / OUT / "records").glob("*/*/*.json"):
        if path.stem not in (*ARMS, "baseline", "nli", "negative"):
            continue
        key = path.parent.parent.name, path.parent.name
        arm = path.stem
        record = checked(path, arm, lookup[key], freeze)
        assert record["response_json"]["choices"][0]["message"]["content"] == record["raw_response"]
        if key in confirm_keys:
            before = directory / "winner.json"
        elif key not in pilot_keys:
            before = directory / "shortlist.json"
            assert arm in shortlist["arms"]
        else:
            before = directory / "freeze.json"
            assert arm in ARMS
        assert datetime.fromisoformat(record["requested_at"]).timestamp() >= before.stat().st_mtime
        raw[key, arm] = record
        raw_hashes[path.relative_to(ROOT).as_posix()] = file_hash(path)
        calls[arm] += 1
        tokens[arm] += record["usage"]["total_tokens"]
    stage_rows = {}
    for stage, metrics in reports.items():
        with (directory / stage / "predictions.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        stage_rows[stage] = rows
        assert len(rows) == len(plan[stage]) == metrics["n"]
        assert {(r["dataset"], r["id"]) for r in rows} == {(r["dataset"], r["id"]) for r in plan[stage]}
        stage_keys = {(r["dataset"], r["id"]) for r in rows}
        for arm, count in metrics["calls"].items():
            records = [r for (k, a), r in raw.items() if k in stage_keys and a == arm]
            assert len(records) == count
            assert sum(r["usage"]["total_tokens"] for r in records) == metrics["tokens"][arm]
        for row in rows:
            key = row["dataset"], row["id"]
            assert row["gold"] == source[key]["label"]
            assert row["group"] == source[key]["group"]
            predictions = {a: parsed(a, r) for (k, a), r in raw.items() if k == key}
            if stage != "confirm":
                predictions["baseline"], predictions["nli"] = row["baseline"], row["nli"]
            for method in metrics["methods"]:
                if stage == "confirm" or method in ARMS or method.startswith("agree__"):
                    assert row[method] == independent_policy(method, predictions)
        for method, entry in metrics["methods"].items():
            for dataset in ("basic", "challenge"):
                subset = [r for r in rows if r["dataset"] == dataset]
                m = entry["metrics"][dataset]
                correct = sum(r[method] == r["gold"] for r in subset)
                assert m["n"] == len(subset) and m["correct"] == correct
                assert m["accuracy"] == correct / len(subset)
                f1s = []
                for label in LABELS:
                    ng = sum(r["gold"] == label for r in subset)
                    np = sum(r[method] == label for r in subset)
                    tp = sum(r["gold"] == label and r[method] == label for r in subset)
                    assert m["classes"][label]["support"] == ng
                    assert m["classes"][label]["recall"] == (tp / ng if ng else None)
                    if ng:
                        f1s.append(2 * tp / (ng + np))
                assert abs(m["macro_f1"] - sum(f1s) / len(f1s)) < 1e-12
                assert entry["paired"][dataset]["improved"] == sum(r[method] == r["gold"] and r["baseline"] != r["gold"] for r in subset)
                assert entry["paired"][dataset]["harmed"] == sum(r[method] != r["gold"] and r["baseline"] == r["gold"] for r in subset)
    assert not list((ROOT / OUT / "records").glob("*/*/*.inflight"))
    secret = [s.split("=", 1)[1].strip().strip("\"'") for s in (ROOT / ".env.local").read_text(encoding="utf-8-sig").splitlines() if s.startswith("GROQ_API_KEY=")]
    files = [Path(__file__), ROOT / "src/ab_factcheck/search_v9.py", ROOT / "tests/test_search_v9.py"]
    files += [p for folder in (ROOT / EXP, ROOT / OUT) for p in folder.rglob("*") if p.is_file()]
    for path in files:
        content = path.read_bytes()
        assert not any(s and s.encode() in content for s in secret)
        assert not re.search(rb"\bgsk_[A-Za-z0-9_-]{20,}", content)
    audit = {"passed": True, "audited_at": now(), "winner": winner, "fresh_n": 28, "fresh_groups": 14,
        "full_groups_evaluated": False, "historical_group_overlap": 0, "exact_payloads_verified": True,
        "nonthinking_observable_checks_passed": True, "stage_freezes_precede_requests": True,
        "decision_and_metrics_independently_recomputed": True, "test_files_read": False,
        "unique_new_responses": len(raw), "actual_tokens": sum(tokens.values()),
        "calls_by_arm": dict(calls), "tokens_by_arm": dict(tokens),
        "observed_first_output_fields": {a: dict(Counter(first_field(r) for (k, arm), r in raw.items() if arm == a)) for a in calls},
        "invalid_responses_by_arm": {a: sum(parsed(arm, r) not in LABELS for (k, arm), r in raw.items() if arm == a) for a in calls},
        "research_cost_note": "Each new response counted once; pilot is a subset of scout, so stage costs must not be summed.",
        "audit_script_sha256": file_hash(Path(__file__)), "raw_file_sha256": raw_hashes}
    atomic_json(directory / "audit.json", audit)
    lines = ["# V9 少量样本方案筛选结果", "", f"最终候选：`{winner}`。所有阶段已完成，原始响应及计分审计通过。", "",
        "Qwen-27B 非思考；仅开发集输入；未训练；测试集封存。初筛和扩展使用历史开发题，只能用于选方向。确认集为 14 个此前未使用的组、每组两题，共 28 题，并非完整组评测。", ""]
    for stage, title in (("pilot", "14 题初筛"), ("scout", "42 题扩展筛选"), ("confirm", "28 题新开发组确认")):
        lines += ["## " + title, "", "| 方法 | Basic 正确数 | Challenge 正确数 |", "|---|---:|---:|"]
        for method, entry in reports[stage]["methods"].items():
            a, b = (entry["metrics"][d] for d in ("basic", "challenge"))
            lines += [f"| {method} | {a['correct']}/{a['n']} | {b['correct']}/{b['n']} |"]
        lines.append("")
    result = reports["confirm"]["methods"][winner]
    lines += ["## 确认集配对比较", "", "| 数据集 | Accuracy 差值 | 修正 / 损害 | 组 bootstrap 95% 区间 | 组置换 p |", "|---|---:|---:|---:|---:|"]
    for d in ("basic", "challenge"):
        stats = result["statistics"][d]["metrics"]["accuracy"]
        paired = result["paired"][d]
        lo, hi = stats["group_bootstrap_95"]
        lines += [f"| {d} | {100*stats['delta']:+.2f} pp | {paired['improved']} / {paired['harmed']} | [{100*lo:+.2f}, {100*hi:+.2f}] pp | {stats['group_paired_two_sided_p']:.4f} |"]
    confirm = reports["confirm"]
    baseline_tokens = confirm["tokens"]["baseline"]
    method_tokens = sum(confirm["tokens"].values()) - (0 if winner.startswith("agree__") or winner == "signed_v8" else baseline_tokens)
    lines += ["", "小样本不能证明总体非劣或测试集提升。候选和规则在确认请求之前冻结；确认结果不会用于重新选择本轮赢家。", "", "## 成本", "",
        f"本轮新增 {len(raw)} 个唯一响应，共 {sum(tokens.values()):,} tokens；历史缓存成本不计入本轮新增开销。",
        f"确认阶段基线使用 {baseline_tokens:,} tokens，候选部署所需响应使用 {method_tokens:,} tokens（{method_tokens/baseline_tokens:.2f} 倍）。融合方案计入基线；单模型方案不计入用于比较的基线。",
        "", "## 干预与解释限制", "",
        "`reason_first_nli` 改变的是请求 schema 的字段顺序；还需区分请求顺序和实际生成顺序。各方案实际响应的首字段计数见 audit.json 的 observed_first_output_fields。若对照原本也先输出 justification，不能把差异解释为先推理后分类的因果效果。",
        "14 题初筛的 challenge 恰好没有 REFUTES 样本，故该切片无法估计此类召回率；没有为了补齐标签而事后换题。42 题扩展和 28 题确认分别保留各自真实类别分母。",
        "", "输入完整性、精确请求、模型返回 ID、非思考可观测检查、分组隔离、冻结时间、逐题决策及准确率/F1/类别召回率均已核对。未读取测试文件。", ""]
    atomic_bytes(directory / "RESULTS.md", "\n".join(lines).encode("utf-8"))
    print(json.dumps({k: v for k, v in audit.items() if k != "raw_file_sha256"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
