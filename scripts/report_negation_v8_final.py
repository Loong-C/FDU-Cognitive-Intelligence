"""Summarize the complete frozen experiment after its independent audit."""
import csv
import json
from collections import Counter

from ab_factcheck.common import ROOT, LABELS, atomic_bytes, atomic_json, file_hash, now
from ab_factcheck.negation_v8.experiment import EXPERIMENT, OUTPUT, verify


def main():
    manifest, freeze = verify("confirm")
    folder = ROOT / EXPERIMENT
    metrics = json.loads((folder / "confirm/metrics.json").read_text(encoding="utf-8"))
    audit = json.loads((folder / "confirm/audit.json").read_text(encoding="utf-8"))
    if not metrics["complete"] or not audit["passed"]:
        raise ValueError("Complete confirmation and successful independent audit required")
    assert audit["metrics_sha256"] == file_hash(folder / "confirm/metrics.json")
    assert audit["predictions_sha256"] == file_hash(folder / "confirm/predictions.csv")
    with (folder / "confirm/predictions.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(manifest["rows"])
    costs, ablations = {}, {}
    for node in ("baseline", "positive", "negative"):
        records = [json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / OUTPUT / "confirm/records").glob(f"*/*/{node}.json")]
        costs[node] = {"calls": len(records), **{k: sum(r["usage"][k] for r in records) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}}
    for dataset in ("basic", "challenge"):
        counts = Counter()
        for row in (r for r in rows if r["dataset"] == dataset):
            b, p, s = [row[k] == row["gold"] for k in ("baseline", "positive", "prediction")]
            if not b and p:
                counts["nli_fixes_kept" if s else "nli_fixes_blocked"] += 1
            if b and not p:
                counts["nli_harms_blocked" if s else "nli_harms_kept"] += 1
            counts["overrides"] += int(row["prediction"] != row["baseline"])
        ablations[dataset] = dict(counts)
    relaxed = (metrics["strict_accuracy_gain_somewhere"] and not metrics["detected_significant_regression"])
    result = {"created_at": now(), "complete": True, "strict_frozen_rule_passed": metrics["passes_development_rule"],
        "user_relaxed_screen_passed": relaxed, "noninferiority_established": False, "test_generalization_established": False,
        "relaxed_rule_provenance": "User relaxed requirements before V8; same no-significant-loss plus accuracy-gain screen as V7. Original stricter V8 gate is preserved separately, not amended.",
        "costs": costs, "ablation": ablations, "metrics_sha256": file_hash(folder / "confirm/metrics.json"),
        "audit_sha256": file_hash(folder / "confirm/audit.json")}
    atomic_json(folder / "final_assessment.json", result)
    lines = ["# V8：正反命题 NLI 一致性完整结果", "", f"生成时间（UTC）：{result['created_at']}。101 道预选新开发题全部完成，14 个完整组。测试集继续封存。", "",
        f"冻结的严格门槛：**{'通过' if metrics['passes_development_rule'] else '未通过'}**；按用户原有的“不显著退步且至少一套准确率提高”开发筛选口径：**{'通过' if relaxed else '未通过'}**。", "",
        "这些是开发候选筛选结果；未检出下降不等于证明非劣效，没有据此声称测试泛化或总体稳定优于基线。严格门槛要求两套准确率和 macro-F1 点估计均不下降，保留其失败标记。", "",
        "| 数据 | 方案 | 正确/总数 | 准确率 | Macro-F1 | S 召回 | R 召回 | NEI 召回 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    names = {"baseline": "A27", "nli": "单次 NLI", "signed_consensus": "正反一致性"}
    for dataset, arms in metrics["datasets"].items():
        for arm in names:
            m = arms[arm]["metrics"]
            lines.append(f"| {dataset} | {names[arm]} | {m['correct']}/{m['n']} | {m['accuracy']:.2%} | {m['macro_f1']:.4f} | " + " | ".join(f"{m['classes'][k]['recall']:.2%}" for k in LABELS) + " |")
    lines += ["", "## 成对效果与不确定性", "", "按完整组做 5,000 次 bootstrap 和 128 种精确配对置换，每套仅 7 组；以下 p 值为未校正的双侧检验。少数组的区间和 p 值可能不稳定，不将变体当成独立样本。", "", "| 数据 | 指标 | 差值（百分点） | 组 bootstrap 95% 区间 | 配对组 p |", "|---|---|---:|---|---:|"]
    paired_notes = []
    for dataset, arms in metrics["datasets"].items():
        entry = arms["signed_consensus"]
        for key, value in entry["statistics"]["metrics"].items():
            interval = value["group_bootstrap_95"]
            lines.append(f"| {dataset} | {key} | {100*value['delta']:+.2f} | [{100*interval[0]:+.2f}, {100*interval[1]:+.2f}] | {value['group_paired_two_sided_p']:.4f} |")
        pair = entry["paired"]
        paired_notes.append(f"{dataset}：相对 A27 改对 {pair['improved']} 题、误伤 {pair['harmed']} 题。")
    lines += ["", *paired_notes, ""]
    lines += ["## 一致性过滤的作用", "", "| 数据 | 保留 NLI 正确修正 | 拦截 NLI 正确修正 | 拦住 NLI 误伤 | 放过 NLI 误伤 |", "|---|---:|---:|---:|---:|"]
    for dataset, a in ablations.items():
        lines.append(f"| {dataset} | " + " | ".join(str(a.get(k, 0)) for k in ("nli_fixes_kept", "nli_fixes_blocked", "nli_harms_blocked", "nli_harms_kept")) + " |")
    lines += ["", "一致性与正确性是不同的性质：同一模型可以在正反判断上保持一致却共同犯错，也可能因反向错误而否决正向的正确修正。该方法没有形式化证明能力。", "", "## 分机制结果", "", "| 数据/机制 | A27 | 单次 NLI | 正反一致性 | 总数 |", "|---|---:|---:|---:|---:|"]
    for dataset, arms in metrics["datasets"].items():
        for mechanism, m in arms["baseline"]["mechanisms"].items():
            values = [arms[a]["mechanisms"][mechanism]["correct"] for a in names]
            lines.append(f"| {dataset}/{mechanism} | {values[0]} | {values[1]} | {values[2]} | {m['n']} |")
    lines += ["", "每个机制只有一个完整组，这些行只作描述，不代表该机制的总体效果。", "", "## 部署成本", "", "| 调用 | 次数 | 输入 token | 输出 token | 总 token |", "|---|---:|---:|---:|---:|"]
    for node, c in costs.items():
        lines.append(f"| {node} | {c['calls']} | {c['prompt_tokens']} | {c['completion_tokens']} | {c['total_tokens']} |")
    total = sum(c["total_tokens"] for c in costs.values())
    lines += ["", f"完整方案共 {sum(c['calls'] for c in costs.values())} 次调用，{total:,} token，为单独 A27 的 **{total/costs['baseline']['total_tokens']:.2f} 倍**。部署需要基线加正向判断，并在分歧时追加反向判断。历史缓存不抵扣部署成本。", "",
        "## 方法、约束与复核", "", "固定 Qwen-27B、reasoning_effort=none、temperature=0、seed=42。基线逐字复用 A27；NLI 逐字复用 V7。反向命题通过完整 claim 的确定性否定包装生成。只有正向与翻转后的反向标签一致才覆盖基线。不存在题型、关键词或 gold 路由，没有 SFT/LoRA 或外部检索。", "",
        "确认清单在本轮调用前冻结，与历史 pilot、V5 fresh 和所有 V7 组隔离。用户暂停时查看过部分结果，恢复后未修改策略、样本或输出；不存在中途挑选更有利子集。调用交错进行且发生额度暂停，不据端到端耗时推断模型速度。", "",
        f"独立审计已核验 {audit['raw_responses']} 个响应的模型身份、非思考可观察字段、输入/输出、标签映射、完整分组和指标。服务端共出现 {len(audit['system_fingerprints'])} 种 fingerprint，固定 seed 不保证逐位确定性。原始审计在 [confirm/audit.json](confirm/audit.json)，全部指标在 [confirm/metrics.json](confirm/metrics.json)，逐题结果在 [confirm/predictions.csv](confirm/predictions.csv)。", "",
        "复现：运行 `scripts/audit_negation_v8.py` 后运行 `scripts/report_negation_v8_final.py`。所有本地产物均在仓库内。"]
    atomic_bytes(folder / "RESULTS.md", ("\n".join(lines) + "\n").encode("utf-8"))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
