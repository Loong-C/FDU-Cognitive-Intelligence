"""Auditable Groq reports: missing inference remains missing, never fabricated."""
from collections import Counter
import csv
import io
import json
from pathlib import Path

from .common import ROOT, DATASETS, LABELS, atomic_bytes, atomic_json, file_hash, json_bytes, now, read_jsonl, sha256, write_jsonl
from .groq_client import MODEL
from .metrics import compute_metrics, paired_comparison, prediction
from .reporting import csv_file, pct, decimal

ARMS = ("A2", "B2")
HISTORY = {
    "4B": ROOT / "experiments/002_constrained_output/reports/pilot_qwen3_4b_q4_struct_v2_r2",
    "14B": ROOT / "experiments/003_model_scaling_14b/reports/pilot_qwen3_14b_q4_nonthink_v3_r3",
}


def read_optional(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def records_for(exp):
    """Load atomic records, validating identity, metadata, and exact input boundary."""
    found = []
    for d in DATASETS:
        for a in ARMS:
            for row in exp.rows[d]:
                p = exp.directory / f"records/{d}/{a}/{sha256(row['id'].encode())}.json"
                if not p.exists():
                    continue
                r = read_optional(p)
                if r.get("status") != "completed":
                    raise ValueError("Partial atomic record; recovery/verification required")
                if r.get("run_fingerprint_sha256") != exp.fp_hash:
                    raise ValueError("Record fingerprint mismatch")
                for k, expected in {"run_id": exp.config["run_id"], "dataset": d, "arm": a, "id": row["id"],
                                    "gold_label": row["label"], "group": row["group"], "mechanism": row["mechanism"], "split": "pilot"}.items():
                    if r.get(k) != expected:
                        raise ValueError("Record metadata mismatch: " + k)
                expected = exp.prompts.render(a, claim=row["claim"], evidence=row["evidence"])
                if r["request_payload"]["messages"] != expected:
                    raise ValueError("Prompt input differs; only claim/evidence permitted")
                found.append(r)
    paths = list((exp.directory / "records").glob("*/*/*.json"))
    if len(paths) != len(found):
        raise ValueError("Unexpected atomic records or non-pilot IDs")
    return found


def independent_parse(r):
    """Independent parser, intentionally not calling the experimental parser."""
    def pairs(items):
        obj = {}
        for k, v in items:
            if k in obj: raise ValueError("duplicate")
            obj[k] = v
        return obj
    valid, logic, label = False, None, None
    try:
        obj = json.loads(r["raw_response"], object_pairs_hook=pairs)
        keys = {"verdict", "reason"} if r["arm"] == "A2" else {"true_world", "false_world", "true_reason", "false_reason"}
        valid = isinstance(obj, dict) and set(obj) == keys and all(isinstance(v, str) for v in obj.values())
        if valid:
            reasons = [k for k in keys if "reason" in k]
            valid = all(len(obj[k]) <= 320 for k in reasons)
            if r["arm"] == "A2":
                valid &= obj["verdict"] in LABELS
            else:
                valid &= all(obj[k] in ("POSSIBLE", "IMPOSSIBLE") for k in ("true_world", "false_world"))
        valid = bool(valid and r["finish_reason"] == "stop")
        if valid and r["arm"] == "A2": label = obj["verdict"]
        if valid and r["arm"] == "B2":
            label = {("POSSIBLE", "IMPOSSIBLE"): "SUPPORTS", ("IMPOSSIBLE", "POSSIBLE"): "REFUTES",
                     ("POSSIBLE", "POSSIBLE"): "NOT ENOUGH INFO"}.get((obj["true_world"], obj["false_world"]))
            logic = label is not None
    except (ValueError, TypeError):
        pass
    return valid, logic, label


def audit(exp):
    saved = read_optional(exp.directory / "fingerprint.json")
    if saved != exp.fp:
        raise ValueError("Inference source/config changed; use a new run ID")
    records = records_for(exp)
    for r in records:
        valid, logic, label = independent_parse(r)
        if (r["protocol_valid"], r["logic_valid"], r["predicted_label"]) != (valid, logic, label):
            raise ValueError("Independent parsing disagrees")
        if valid:
            obj = json.loads(r["raw_response"])
            mapping = {"reason": "direct_reason"} if r["arm"] == "A2" else {
                "true_world": "claim_true_world", "false_world": "claim_false_world",
                "true_reason": "world_reason_true", "false_reason": "world_reason_false"}
            if any(obj[k] != r.get(v) for k, v in mapping.items()):
                raise ValueError("Parsed reasons/worlds differ from the raw response")
        payload = r["request_payload"]
        expected = {"model": MODEL, "temperature": 0, "seed": 42, "reasoning_effort": "none", "stream": False, "max_completion_tokens": 1024}
        if any(payload.get(k) != v for k, v in expected.items()):
            raise ValueError("Request parameters differ")
        if payload["response_format"] != exp.fp["response_formats"][r["arm"]]:
            raise ValueError("Schema differs")
        raw = r["response_json"]
        if raw["model"] != MODEL or r.get("provider_validation_issues"):
            raise ValueError("Provider validation failed")
        message = raw["choices"][0]["message"]
        if message["content"] != r["raw_response"] or raw["usage"] != r["usage"]:
            raise ValueError("Raw/API record mismatch")
        if any(message.get(k) for k in ("reasoning", "reasoning_content")) or "<think" in r["raw_response"].lower():
            raise ValueError("Reasoning detected")
        def check_tokens(v):
            if isinstance(v, dict):
                for k, x in v.items():
                    if k in ("reasoning_tokens", "thinking_tokens") and x not in (None, 0): raise ValueError("Reasoning token detected")
                    check_tokens(x)
            elif isinstance(v, list):
                for x in v: check_tokens(x)
        check_tokens(raw["usage"])
        if r["usage"]["total_tokens"] != r["usage"]["prompt_tokens"] + r["usage"]["completion_tokens"]:
            raise ValueError("Usage mismatch")
    for dataset in DATASETS:
        exported = read_jsonl(exp.directory / f"{dataset}.jsonl")
        if exported != [r for r in records if r["dataset"] == dataset]:
            raise ValueError("Export differs from atomic records")
    gates = {}
    for name in ("technical", "smoke", "integration"):
        gate = read_optional(exp.directory / f"{name}_gate.json")
        gates[name] = bool(gate and gate.get("passed") and gate.get("fingerprint_sha256") == exp.fp_hash)
        if gate:
            folder = exp.directory / ("technical" if name == "technical" else "smoke")
            for file, digest in gate.get("evidence_sha256", {}).items():
                if file_hash(folder / file) != digest: raise ValueError("Gate evidence changed")
    if records and not all(gates.values()):
        # Integration prefix may exist before integration gate is written.
        if not gates["technical"] or not gates["smoke"] or len(records) > 20:
            raise ValueError("Formal results exist without required preflight gates")
    receipt = {"generated_at": now(), "run_id": exp.config["run_id"], "artifact_integrity_passed": True,
               "formal_complete": len(records) == 294, "formal_records": len(records), "gates": gates,
               "fingerprint_sha256": exp.fp_hash, "independent_parse_checked": len(records),
               "interpretation": "Integrity is not proof that a blocked or partial model experiment completed."}
    destination = ROOT / exp.config["report_root"] / exp.config["run_id"]
    atomic_json(destination / "execution_audit.json", receipt)
    print(json.dumps(receipt, indent=2))
    return receipt


def costs(rows):
    return {"completed_requests": len(rows), "request_attempts": sum(r["completion_request_attempts"] for r in rows),
            "request_seconds": sum(r["latency_seconds"] for r in rows),
            **{k: sum(r["usage"].get(k, 0) for r in rows) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "server_fingerprints": sorted({r.get("system_fingerprint") for r in rows if r.get("system_fingerprint")})}


def report(exp):
    audit_receipt = audit(exp)
    records = records_for(exp)
    complete = len(records) == 294
    dest = ROOT / exp.config["report_root"] / exp.config["run_id"]
    history = {name: read_optional(p / "metrics.json") for name, p in HISTORY.items()}
    history_predictions = {name: list(csv.DictReader(io.StringIO((p / "predictions.csv").read_text(encoding="utf-8-sig")))) for name, p in HISTORY.items()}
    ledger = read_optional(ROOT / "outputs/groq/quota.json", {"attempts": []})
    # Scope shared quota ledger to this run's recorded request hashes and chronology.
    started = (exp.directory / "fingerprint.json").stat().st_mtime
    attempts = [a for a in ledger["attempts"] if a["timestamp"] >= started - 1]
    api = {"attempts": attempts, "completed_formal": len(records), "expected_formal": 294,
           "successful_usage_tokens": sum(a.get("usage", {}).get("total_tokens", 0) for a in attempts),
           "budget_reserved_or_actual_tokens": sum(a["charged_tokens"] for a in attempts),
           "http_status_counts": dict(Counter(str(a.get("http_status", a["status"])) for a in attempts)),
           "free_plan_confirmation": "User confirmed Free Plan in chat on 2026-10-23; not an API billing attestation",
           "billing_verified": False}
    datasets, groups, mechanisms, changes = {}, [], [], []
    for d in DATASETS:
        by_arm = {a: [r for r in records if r["dataset"] == d and r["arm"] == a] for a in ARMS}
        full_dataset = all(len(by_arm[a]) == len(exp.rows[d]) for a in ARMS)
        arms = {}
        for a in ARMS:
            pending = len(exp.rows[d]) - len(by_arm[a])
            placeholders = [{"gold_label": r["label"], "predicted_label": None, "status": "not_run", "output_protocol": "json_schema_v2"}
                            for r in exp.rows[d] if r["id"] not in {x["id"] for x in by_arm[a]}]
            m = compute_metrics(by_arm[a] + placeholders)
            m.update(completed=len(by_arm[a]), missing=pending, measured_complete=pending == 0)
            if pending:
                # Strict partial lower bound is separate from an empirical full-run accuracy.
                m["strict_accuracy_lower_bound"] = m["accuracy"]
                m["accuracy"] = None
                m["macro_f1"] = None
                m["strict_confusion_lower_bound"] = m["confusion_matrix"]
                m["confusion_matrix"] = None
                for item in m["classes"].values():
                    for field in ("precision", "recall", "f1"):
                        item[field] = None
                for field in ("nei_to_refutes", "nei_to_refutes_rate", "supports_to_nei", "refutes_to_nei", "valid_only_accuracy"):
                    m[field] = None
                m["interpretation"] = "Incomplete; missing items are not model inferences. No full-run score is reported."
            arms[a] = m
        paired = {"B2-A2": paired_comparison(by_arm["A2"], by_arm["B2"])} if full_dataset else {}
        datasets[d] = {"arms": arms, "paired": paired, "mechanisms": {}}
        if full_dataset:
            p = paired["B2-A2"]
            left = {r["id"]: r for r in by_arm["A2"]}
            for r in by_arm["B2"]:
                before = left[r["id"]]
                if prediction(before) != prediction(r):
                    changes.append({"dataset": d, "id": r["id"], "group": r["group"], "mechanism": r["mechanism"], "gold_label": r["gold_label"],
                                    "before": prediction(before), "after": prediction(r), "direction": "improved" if r["id"] in p["improved_ids"] else "harmed" if r["id"] in p["harmed_ids"] else "both_wrong"})
            for field, target in (("group", groups), ("mechanism", mechanisms)):
                for value in sorted({r[field] for r in exp.rows[d]}):
                    for a in ARMS:
                        m = compute_metrics([r for r in by_arm[a] if r[field] == value])
                        target.append({"dataset": d, field: value, "arm": a, **m})
                        if field == "mechanism": datasets[d]["mechanisms"].setdefault(value, {})[a] = m
        csv_file(dest / f"metrics_{d}.csv", [{"arm": a, **m} for a, m in arms.items()],
                 ["arm", "n", "completed", "missing", "correct", "accuracy", "macro_f1", "invalid", "not_run_count", "nei_to_refutes", "supports_to_nei", "refutes_to_nei"])
    receipt = {"run_id": exp.config["run_id"], "generated_at": now(), "status": "formal_complete" if complete else "blocked_or_partial",
               "record_count": len(records), "expected_record_count": 294, "fingerprint_sha256": exp.fp_hash, "datasets": datasets,
               "source_jsonl_sha256": {d: file_hash(exp.directory / f"{d}.jsonl") for d in DATASETS}}
    atomic_json(dest / "metrics.json", receipt)
    atomic_json(dest / "configuration.json", exp.config)
    atomic_json(dest / "run_fingerprint.json", exp.fp)
    atomic_json(dest / "api_diagnostics.json", api)
    atomic_json(dest / "costs.json", {d: {a: costs([r for r in records if r["dataset"] == d and r["arm"] == a]) for a in ARMS} for d in DATASETS})
    atomic_json(dest / "history_provenance.json", {name: {"metrics_sha256": file_hash(p / "metrics.json"), "predictions_sha256": file_hash(p / "predictions.csv")} for name, p in HISTORY.items()})
    fields = ["dataset", "arm", "id", "group", "mechanism", "gold_label", "predicted_label", "status", "parse_status", "parse_error", "protocol_valid", "logic_valid",
              "claim_true_world", "claim_false_world", "world_reason_true", "world_reason_false", "direct_reason", "finish_reason", "latency_seconds", "prompt_tokens", "completion_tokens", "total_tokens"]
    csv_file(dest / "predictions.csv", [{**r, **r["usage"]} for r in records], fields)
    csv_file(dest / "changed_predictions.csv", changes, ["dataset", "id", "group", "mechanism", "gold_label", "before", "after", "direction"])
    for name, rows, key in (("metrics_by_group", groups, "group"), ("metrics_by_mechanism", mechanisms, "mechanism")):
        csv_file(dest / (name + ".csv"), rows, ["dataset", key, "arm", "n", "correct", "accuracy", "macro_f1", "invalid", "nei_to_refutes", "supports_to_nei", "refutes_to_nei"])
    # Only these fictional/dev outputs are exported. No credentials or request headers are present.
    write_jsonl(dest / "api_records.jsonl", records)
    typical = []
    bykey = {(r["dataset"], r["arm"], r["id"]): r for r in records}
    for sample_id in exp.config["review"]["typical_ids"]:
        d, source = next((d, r) for d in DATASETS for r in exp.rows[d] if r["id"] == sample_id)
        for a in ARMS:
            row = {"dataset": d, "id": sample_id, "arm": a, "gold": source["label"], "claim": source["claim"], "evidence": source["evidence"]}
            for model in ("4B", "14B", "27B"):
                prior = bykey.get((d, a, sample_id), {}) if model == "27B" else next(x for x in history_predictions[model] if x["dataset"] == d and x["arm"] == a and x["id"] == sample_id)
                for key in ("predicted_label", "claim_true_world", "claim_false_world", "world_reason_true", "world_reason_false", "direct_reason"):
                    row[f"{model}_{key}"] = prior.get(key)
            typical.append(row)
    csv_file(dest / "typical_errors.csv", typical, list(typical[0]))
    review = []
    for d in DATASETS:
        for label in LABELS:
            chosen = [r for r in exp.rows[d] if r["label"] == label][:3]
            for source in chosen:
                r = bykey.get((d, "B2", source["id"]), {})
                review.append({"dataset": d, "id": source["id"], "gold_label": label, "claim": source["claim"], "evidence": source["evidence"],
                               **{k: r.get(k) for k in ("claim_true_world", "claim_false_world", "world_reason_true", "world_reason_false")},
                               "semantic_review_status": "pending_manual_review" if r else "not_run", "review_note": ""})
    if not (dest / "reason_consistency_review.csv").exists():
        csv_file(dest / "reason_consistency_review.csv", review, list(review[0]))
    lines = ["# 第四轮：GroqCloud 27B 双世界对照实验", "", f"运行 `{exp.config['run_id']}`；基线 `codex/14b-nonthink-v3` / `a99a5d8`。",
             "", f"**状态：{'正式完成' if complete else '未完成'}，正式模型回答 {len(records)}/294。** 技术门槛：" + json.dumps(audit_receipt["gates"], ensure_ascii=False) + "。",
             "", "复用第三轮冻结开发集：challenge 87题/14完整组，basic 60题/7完整组；同序ID及manifest哈希已核对。仅输入claim/evidence及原版A2/B2提示词；无C2示例、无test推理、无训练。",
             "", "## 接口、配额与真实执行", "", "请求固定模型 `qwen/qwen3.8-27b`，`reasoning_effort=none`、temperature=0、seed=42、stream=false、max_completion_tokens=1024；严格JSON Schema保留maxLength=320。API接受seed也不代表逐位确定性，是否实际生效不可独立证明。",
             "", f"已记录HTTP状态：`{json.dumps(api['http_status_counts'])}`。已收到的usage记录合计token={api['successful_usage_tokens']}；保守预留/实际记账={api['budget_reserved_or_actual_tokens']}。没有usage记录时实际用量未知；预留token不是服务端用量或账单。",
             "", "用户已确认Free Plan。参考上限30 RPM、8000 TPM、1000 RPD、200000 TPD；本地采用25 RPM、7000 TPM、800次/滚动24h、180000 token/滚动24h。服务端响应头只显示RPD/TPM，不能证明免费套餐或剩余TPD；没有升级套餐、没有换模型、没有授权收费请求。",
             "", "当HTTP 401/403/400出现时立即停止；429尊重Retry-After和reset，超过60秒则保存暂停；网络/5xx有限重试。预算在发请求前原子预留，成功后使用usage结算。单并发锁、逐题原子文件、固定指纹；未知中断留下inflight标记，禁止自动重复生成。",
             "", "## 两组结果", "", "所有完整实验统计按全部应测样本计分，无效/截断计错。未完成时不公布完整准确率；metrics.json另列已完成数量和严格完成下界，缺失项不能当作真实模型失败。"]
    for d in DATASETS:
        lines += ["", f"### {d}", "", "| 模型/方法 | 正确/应测 | 准确率 | 宏F1 | S召回 | R召回 | NEI召回 | NEI→R | S→NEI | R→NEI |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for model in ("4B", "14B", "27B"):
            for a in ARMS:
                m = datasets[d]["arms"][a] if model == "27B" else history[model]["datasets"][d]["arms"][a]
                display = ("A" if a == "A2" else "B") + model.removesuffix("B")
                if model == "27B" and not m["measured_complete"]:
                    lines.append(f"| {display} | 未完成（{m['completed']}/{m['n']}已返回） | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |")
                else:
                    lines.append(f"| {display} | {m['correct']}/{m['n']} | {pct(m['accuracy'])} | {decimal(m['macro_f1'])} | " + " | ".join(pct(m['classes'][l]['recall']) for l in LABELS) + f" | {m['nei_to_refutes']} | {m['supports_to_nei']} | {m['refutes_to_nei']} |")
        if datasets[d]["paired"]:
            p = datasets[d]["paired"]["B2-A2"]
            lines += ["", f"B27−A27：准确率变化{100*p['accuracy_delta']:+.2f}个百分点，错→对{p['improved']}题，对→错{p['harmed']}题。逐题清单见changed_predictions.csv。"]
            for a in ARMS:
                m = datasets[d]["arms"][a]
                lines += ["", f"{a} 混淆矩阵（行gold，列预测）：", "", "| gold | SUPPORTS | REFUTES | NEI | INVALID |", "|---|---:|---:|---:|---:|"]
                for l, cells in m["confusion_matrix"].items(): lines.append(f"| {l} | " + " | ".join(str(cells[x]) for x in (*LABELS, "INVALID")) + " |")
    lines += ["", "## 验收问题与证据边界", "",
        "1. **真正关闭thinking？** 请求显式none；只有成功返回后才能检查reasoning字段/think标记及reasoning_tokens。未收到回答时无法实测确认。缺少reasoning token字段仅表示未暴露，不能证明内部实现。",
        "2. **结构化输出稳定？** 必须先通过无约束NOT_JSON对照、A/B独立Schema枚举哨兵、400字符对照与320上限约束，再通过6次独立虚构smoke。HTTP 200或合法JSON不足以通过。门槛结果见execution_audit.json；尚未通过不得宣称稳定。",
        "3. **正确数、NEI提升与S/R误伤？** 完整结果见上表；未完成时无法回答。不得用历史14B数字代替27B结果。",
        "4. **非法反例是否减少？** 预指定Salem、2026、124999/125000、only one的逐题对照见typical_errors.csv。固定18条语义复核见reason_consistency_review.csv；尚无27B输出的条目明确not_run。不能根据gold自动归因或修复。",
        "5. **成本及免费额度？** costs.json按数据/方法记录真实usage和请求耗时，api_diagnostics.json另列技术请求和失败预算预留。未返回usage的请求，实际token与账单均未知；不能写成已验证零费用。",
        "6. **与A组Q8_0严格比较还缺什么？** 需要相同模型版本/权重来源与可核对量化、相同数据顺序/提示词/Schema/解码预算/非思考设置，以及独立确认的运行环境和完整逐题记录。Groq不公开权重SHA、tokenizer/chat template及硬件，不能宣称与本地Q8_0严格受控等价。",
        "", "4B/14B/27B属于不同模型代际、量化与后端；历史比较仅描述，不把差异归因于参数规模。14/7个group内样本相关，不假设逐题独立或宣称统计显著。basic冻结gold仍为pending审核，本轮不修改历史数据。",
        "", "本地模型SHA、GPU卸载、DLL、/apply-template与精确预分词指标均N/A。API接受的请求参数、返回模型ID、服务端fingerprint和usage才是远程证据。",
        "", "## 官方资料", "", "[模型](https://console.groq.com/docs/model/qwen/qwen3.8-27b)、[API参数](https://console.groq.com/docs/api-reference)、[JSON Schema](https://console.groq.com/docs/structured-outputs)、[限速与响应头](https://console.groq.com/docs/rate-limits)。查询于2026-10-23，真实探针结果优先。", ""]
    atomic_bytes(dest / "pilot_report.md", "\n".join(lines).encode("utf-8"))
    print(f"Report written: {dest}; completed {len(records)}/294")
    return receipt
