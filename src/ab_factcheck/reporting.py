"""Recompute separate dataset reports from actual per-item inference records."""

import csv
import io
import json

from .common import ARMS, DATASETS, LABELS, ROOT, atomic_bytes, atomic_json, experiment_arms, file_hash, now, read_jsonl, sha256
from .metrics import compute_metrics, paired_comparison, prediction
from .pilot import load_pilot


def csv_file(path, rows: list[dict], fields: list[str]):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_bytes(path, output.getvalue().encode("utf-8-sig"))


def pct(value):
    return "N/A" if value is None else f"{100 * value:.2f}%"


def decimal(value):
    return "N/A" if value is None else f"{value:.3f}"


def report(config: dict) -> dict:
    arms = experiment_arms(config)
    structured = config.get("output_protocol") == "json_schema_v2"
    run_directory = ROOT / config["output_root"] / config["run_id"]
    destination = ROOT / config["report_root"] / config["run_id"]
    fingerprint = json.loads((run_directory / "fingerprint.json").read_text(encoding="utf-8"))
    if fingerprint["configuration"] != config:
        raise ValueError("Report configuration differs from the frozen run")
    fingerprint_sha = file_hash(run_directory / "fingerprint.json")
    all_records, datasets, changed, invalid, review, mechanism_rows = [], {}, [], [], [], []
    source_hashes = {}
    for dataset in DATASETS:
        source = run_directory / f"{dataset}.jsonl"
        records = read_jsonl(source)
        source_hashes[dataset] = file_hash(source)
        expected_rows = {row["id"]: row for row in load_pilot(config, dataset)}
        keys = [(row["arm"], row["id"]) for row in records]
        expected_keys = {(arm, sample_id) for arm in arms for sample_id in expected_rows}
        if len(keys) != len(set(keys)) or set(keys) != expected_keys:
            raise ValueError(f"Incomplete or duplicate comparison records: {dataset}")
        for row in records:
            if row["status"] not in ("completed", "request_failed"):
                raise ValueError("Experiment is incomplete; not_run records are not experimental results")
            if row["dataset"] != dataset or row["run_id"] != config["run_id"] or row.get("run_fingerprint_sha256") != fingerprint_sha:
                raise ValueError("Record provenance does not match this run")
            original = expected_rows[row["id"]]
            if any(row[key] != original[source_key] for key, source_key in (("gold_label", "label"), ("group", "group"), ("mechanism", "mechanism"))):
                raise ValueError("Result metadata differs from the frozen pilot")
        by_arm = {arm: [r for r in records if r["arm"] == arm] for arm in arms}
        results = {arm: compute_metrics(rows) for arm, rows in by_arm.items()}
        pairs = {}
        comparisons = list(zip(arms, arms[1:])) + ([("A2", "C2")] if structured and "C2" in arms else [])
        for before, after in comparisons:
            pair = paired_comparison(by_arm[before], by_arm[after])
            pairs[f"{after}-{before}"] = pair
            left = {r["id"]: r for r in by_arm[before]}
            right = {r["id"]: r for r in by_arm[after]}
            for sample_id in sorted(left):
                a, b = left[sample_id], right[sample_id]
                if prediction(a) != prediction(b):
                    direction = "improved" if sample_id in pair["improved_ids"] else "harmed" if sample_id in pair["harmed_ids"] else "changed_but_both_wrong"
                    changed.append({"dataset": dataset, "comparison": f"{after}-{before}", "id": sample_id,
                                    "group": a["group"], "mechanism": a["mechanism"], "gold_label": a["gold_label"],
                                    "before": prediction(a), "after": prediction(b), "direction": direction})
        mechanisms = {}
        for mechanism in sorted({row["mechanism"] for row in records}):
            mechanisms[mechanism] = {}
            for arm in arms:
                metric = compute_metrics([r for r in by_arm[arm] if r["mechanism"] == mechanism])
                mechanisms[mechanism][arm] = metric
                mechanism_rows.append({"dataset": dataset, "mechanism": mechanism, "arm": arm, "n": metric["n"],
                                       "accuracy": metric["accuracy"], "nei_n": metric["classes"]["NOT ENOUGH INFO"]["support"],
                                       "nei_recall": metric["classes"]["NOT ENOUGH INFO"]["recall"], "invalid": metric["invalid"]})
        datasets[dataset] = {"arms": results, "paired": pairs, "mechanisms": mechanisms}
        flat = []
        for arm, metric in results.items():
            record = {"arm": arm, **{k: v for k, v in metric.items() if not isinstance(v, dict)}}
            for label in LABELS:
                for key, value in metric["classes"][label].items():
                    record[f"{label}_{key}"] = value
            flat.append(record)
        csv_file(destination / f"metrics_{dataset}.csv", flat, list(flat[0]))
        for row in records:
            fields = {k: row.get(k) for k in ("dataset", "arm", "id", "group", "mechanism", "gold_label", "predicted_label", "parse_status", "parse_error", "consistency_status", "finish_reason", "error")}
            if row["parse_status"] != "ok":
                invalid.append(fields)
            if row["parse_status"] != "ok" or row.get("consistency_status") in ("inconsistent", "both_impossible") or prediction(row) != row["gold_label"] or row.get("reason_quality_flags"):
                review.append({**fields, "claim": expected_rows[row["id"]]["claim"], "evidence": expected_rows[row["id"]]["evidence"],
                               "record_path": (run_directory / "records" / dataset / row["arm"] / f"{sha256(row['id'].encode())}.json").relative_to(ROOT).as_posix(),
                               "review_status": "requires_human_review"})
        all_records.extend(records)
    arm_starts = {}
    for row in all_records:
        key = (row["dataset"], row["arm"])
        if row.get("created_at"):
            arm_starts[key] = min(arm_starts.get(key, row["created_at"]), row["created_at"])
    observed_order = [f"{dataset}/{arm}" for (dataset, arm), _ in sorted(arm_starts.items(), key=lambda item: item[1])]
    receipt = {"run_id": config["run_id"], "generated_at": now(), "source_jsonl_sha256": source_hashes,
               "observed_arm_start_order": observed_order,
               "fingerprint_sha256": fingerprint_sha, "record_count": len(all_records), "datasets": datasets}
    atomic_json(destination / "metrics.json", receipt)
    atomic_json(destination / "configuration.json", config)
    atomic_json(destination / "run_fingerprint.json", fingerprint)
    csv_file(destination / "changed_predictions.csv", changed, ["dataset", "comparison", "id", "group", "mechanism", "gold_label", "before", "after", "direction"])
    invalid_fields = ["dataset", "arm", "id", "group", "mechanism", "gold_label", "predicted_label", "parse_status", "parse_error", "consistency_status", "finish_reason", "error"]
    csv_file(destination / "invalid_outputs.csv", invalid, invalid_fields)
    csv_file(destination / "review_queue.csv", review, invalid_fields + ["claim", "evidence", "record_path", "review_status"])
    csv_file(destination / "metrics_by_mechanism.csv", mechanism_rows, ["dataset", "mechanism", "arm", "n", "accuracy", "nei_n", "nei_recall", "invalid"])
    prediction_rows = [{**row, **{key: row.get("usage", {}).get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}} for row in all_records]
    csv_file(destination / "predictions.csv", prediction_rows, ["run_id", "dataset", "arm", "id", "group", "mechanism", "gold_label", "predicted_label", "status", "parse_status", "parse_error", "claim_true_world", "claim_false_world", "derived_label", "consistency_status", "finish_reason", "latency_seconds", "prompt_tokens", "completion_tokens", "total_tokens", "preflight_prompt_tokens", "completion_request_attempts", "messages_sha256"])
    if structured:
        if config.get("model_upgrade_v3") or arms == ("A2", "B2"):
            from .reporting_v3 import write_upgrade_report
            write_upgrade_report(config, receipt, all_records, destination)
            return {"report_directory": str(destination), "record_count": len(all_records), "datasets": datasets}
        from .reporting_v2 import write_structured_report
        write_structured_report(config, receipt, all_records, destination)
        return {"report_directory": str(destination), "record_count": len(all_records), "datasets": datasets}
    lines = ["# 首轮双世界提示词 pilot 实验报告", "", f"运行：`{config['run_id']}`。所有数字由本地模型真实逐题记录计算，未使用封存测试集。", "",
             f"模型：`{config['model']['repository']}`，量化 `{config['model']['quantization']}`，后端 `{config['model']['backend_release']}`。",
             "温度 0、请求种子 42、输出上限 512 tokens、上下文 8192、串行运行。种子不构成 GPU 逐位确定性的保证。", "",
             "实际各条件首次请求顺序：" + (" → ".join(observed_order) if observed_order else "记录未提供时间戳") + "。A0 为原始零样本分类；B1 为双世界零样本；C1 增加一个 NEI 虚构示例。", "",
             "## 统计口径", "", "准确率以全部预定样本为分母，无效输出和请求失败计错；保留模型原始 Verdict，不以世界状态推导结果替换。混淆矩阵包含 INVALID 列。普通逻辑不一致单独统计；双 IMPOSSIBLE 为无效。", "",
             "本次是开发集上的小规模探索，组内样本相关，不声称统计显著或最终泛化改善。基础能力集原始审核状态为 pending；未修改标签。语言模型的可能世界判断不是 SAT/SMT 证明。", ""]
    for dataset in DATASETS:
        d = datasets[dataset]
        lines += [f"## {'核心挑战集' if dataset == 'challenge' else '基础能力集'}", "",
                  "| 条件 | 样本 | 正确 | 准确率 | 有效条件准确率 | 宏 F1 | S 召回 | R 召回 | NEI 召回 | NEI→R | 无效 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for arm in ARMS:
            m = d["arms"][arm]
            recalls = [pct(m["classes"][label]["recall"]) for label in LABELS]
            lines.append(f"| {arm} | {m['n']} | {m['correct']} | {pct(m['accuracy'])} | {pct(m['valid_only_accuracy'])} | {decimal(m['macro_f1'])} | {' | '.join(recalls)} | {m['nei_to_refutes']} ({pct(m['nei_to_refutes_rate'])}) | {m['invalid']} |")
        lines += ["", "### 配对变化", "", "| 比较 | 准确率差（百分点） | 错→对 | 对→错 | NEI→R 条数变化 |", "| --- | ---: | ---: | ---: | ---: |"]
        for comparison, p in d["paired"].items():
            after, before = comparison.split("-")
            delta = d["arms"][after]["nei_to_refutes"] - d["arms"][before]["nei_to_refutes"]
            lines.append(f"| {comparison} | {p['accuracy_delta'] * 100:+.2f} | {p['improved']} | {p['harmed']} | {delta:+d} |")
        lines += ["", "### 分机制结果", "", "| 机制 | 样本 / NEI | A0 准确率 / NEI召回 | B1 准确率 / NEI召回 | C1 准确率 / NEI召回 |", "| --- | ---: | --- | --- | --- |"]
        for mechanism, values in d["mechanisms"].items():
            cells = [f"{pct(values[arm]['accuracy'])} / {pct(values[arm]['classes']['NOT ENOUGH INFO']['recall'])}" for arm in ARMS]
            lines.append(f"| {mechanism} | {values['A0']['n']} / {values['A0']['classes']['NOT ENOUGH INFO']['support']} | {' | '.join(cells)} |")
        lines += ["", "### 耗时与输出可靠性", "", "| 条件 | 平均秒 | 中位秒 | 平均生成 tokens | 请求失败 | 逻辑不一致 / 全部 | 双 IMPOSSIBLE |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for arm in ARMS:
            m = d["arms"][arm]
            lines.append(f"| {arm} | {decimal(m['latency_mean_seconds'])} | {decimal(m['latency_median_seconds'])} | {decimal(m['mean_completion_tokens'])} | {m['request_failed_count']} | {m['inconsistent_count']} / {m['n']} | {m['both_impossible_count']} |")
        for arm in ARMS:
            lines += ["", f"### {arm} 混淆矩阵", "", "行是真实标签，列是预测标签。", "", "| 真实标签 | SUPPORTS | REFUTES | NOT ENOUGH INFO | INVALID |", "| --- | ---: | ---: | ---: | ---: |"]
            for label, cells in d["arms"][arm]["confusion_matrix"].items():
                lines.append(f"| {label} | " + " | ".join(str(cells[key]) for key in (*LABELS, "INVALID")) + " |")
        lines.append("")
    lines += ["## 解释与复核", "", "B1−A0 衡量双世界提示词流程的变化，C1−B1 衡量加入单个 NEI 示例后的变化。C1−A0 不能单独归因于双世界方法。", "",
              "逐题改进和误伤见 changed_predictions.csv；无效输出见 invalid_outputs.csv；错误、格式异常和逻辑不一致的原始证据及本地响应路径见 review_queue.csv。完整响应仅保存在被 Git 忽略的 outputs 目录。该队列尚未由人类裁决，不自动将错误归因为某种语义推理缺陷。", "",
              "是否值得进入 SMT 阶段需要结合配对收益、基础能力损失、额外推理成本和人工复核判断；本轮无论正负结果都保留，不根据 pilot 结果回改本版提示词。", "",
              "## 可复算来源", "", f"原始 JSONL：仓库根目录下 `{config['output_root']}/{config['run_id']}/`。",
              "`metrics.json` 保存来源 JSONL 与运行指纹的 SHA-256；`predictions.csv` 提供逐题可复算摘要；完整环境与响应保存在本地运行目录。", ""]
    atomic_bytes(destination / "pilot_report.md", "\n".join(lines).encode("utf-8"))
    return {"report_directory": str(destination), "record_count": len(all_records), "datasets": datasets}
