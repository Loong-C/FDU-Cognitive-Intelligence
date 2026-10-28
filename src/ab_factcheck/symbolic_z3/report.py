"""Offline replay and all-scheduled scoring; labels never construct or repair formulas."""
from collections import Counter
import json

from jsonschema import Draft202012Validator

from ..common import ROOT, atomic_bytes, atomic_json, file_hash, read_jsonl, write_jsonl
from ..prompts import PromptSet
from ..worlds_v5.evaluation import csv_file, metrics
from .experiment import EXPERIMENT, BASELINE, CONFIG, digest, messages, process, verify_freeze
from .logic import parse, solve
from .schema import load_schema, response_format

LABELS = ("SUPPORTS", "REFUTES", "NOT ENOUGH INFO")


def pct(value):
    return "N/A" if value is None else f"{100 * value:.2f}%"


def stable_solution(result):
    return {k: v for k, v in result.items() if k != "solve_seconds"}


def report(root=ROOT):
    manifest = verify_freeze(root)
    directory = root / EXPERIMENT
    config = json.loads((root / CONFIG).read_text(encoding="utf-8"))
    evaluation = {r["id"]: r for r in json.loads((directory / "evaluation.json").read_text(encoding="utf-8"))["rows"]}
    review_path = directory / "semantic_review.json"
    reviews = {r["id"]: r for r in json.loads(review_path.read_text(encoding="utf-8"))["rows"]} if review_path.exists() else {}
    historical_path = root / BASELINE / "api_records.jsonl"
    historical = {(r["dataset"], r["id"]): r for r in read_jsonl(historical_path) if r["arm"] == "A2"}
    direct = PromptSet(root / "prompts/v2", arms=("A2",))
    records, baseline_records, rows, attempts, response_ids = [], [], [], [], []
    validator = Draft202012Validator(load_schema(root))
    for item in manifest["rows"]:
        id_ = item["id"]
        old = historical[(item["dataset"], id_)]
        if old["request_payload"]["messages"] != direct.render("A2", evidence=item["evidence"], claim=item["claim"]):
            raise ValueError("Baseline input differs: " + id_)
        if old["predicted_label"] != evaluation[id_]["baseline_A27"]:
            raise ValueError("Baseline prediction differs: " + id_)
        baseline_records.append(old)
        row = {k: item[k] for k in ("id", "dataset", "group", "mechanism", "input_sha256")}
        row.update(gold=evaluation[id_]["gold"], A27=evaluation[id_]["baseline_A27"], V6=None,
                   corrected=None, semantic_correct=None, schema_valid=None, ast_executable=False,
                   sat_e=None, sat_e_c=None, sat_e_not_c=None, reason=None,
                   prompt_tokens=0, completion_tokens=0, total_tokens=0, latency_seconds=0,
                   server_seconds=0, solver_seconds=0, http_attempts=0,
                   A27_prompt_tokens=old["usage"]["prompt_tokens"],
                   A27_completion_tokens=old["usage"]["completion_tokens"],
                   A27_total_tokens=old["usage"]["total_tokens"],
                   record_sha256=None, corrected_ast_sha256=None, error_categories="")
        path = directory / "records" / (id_ + ".json")
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            completion = record["completion"]
            expected = {"messages": messages(item["evidence"], item["claim"], root),
                        "response_format": response_format(root), "max_completion_tokens": config["completion_limit"]}
            if record["request_sha256"] != digest(expected) or record["input_sha256"] != item["input_sha256"]:
                raise ValueError("Request hash mismatch: " + id_)
            if record["completion_sha256"] != digest(completion):
                raise ValueError("Completion hash mismatch: " + id_)
            payload = completion["request_payload"]
            if any(payload[k] != value for k, value in expected.items()):
                raise ValueError("Saved provider payload mismatch: " + id_)
            for key, value in {"model": "qwen/qwen3.8-27b", "reasoning_effort": "none", "temperature": 0, "seed": 42, "stream": False}.items():
                if payload[key] != value: raise ValueError("Provider parameter mismatch")
            result = process(record, item["evidence"])
            saved_path = directory / "solved" / (id_ + ".json")
            if saved_path.exists():
                saved = json.loads(saved_path.read_text(encoding="utf-8"))
                if stable_solution(result) != stable_solution(saved):
                    raise ValueError("Offline solve differs: " + id_)
            else:
                atomic_json(saved_path, result)
            try:
                ast = parse(completion["raw_response"])
                row["schema_valid"] = validator.is_valid(ast)
            except ValueError:
                row["schema_valid"] = False
            row.update(V6=result["label"], reason=result.get("reason"),
                ast_executable=result.get("constraints") is not None,
                solver_seconds=result.get("solve_seconds", 0),
                latency_seconds=completion["latency_seconds"], server_seconds=completion["usage"].get("total_time", 0),
                http_attempts=len(completion["attempts"]), record_sha256=file_hash(path))
            for key in ("sat_e", "sat_e_c", "sat_e_not_c"):
                row[key] = result.get(key)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                row[key] = completion["usage"].get(key, 0)
            attempts.extend(completion["attempts"])
            response_ids.append(completion["response_id_sha256"])
            records.append(record)
        reference_path = directory / "reviewed_asts" / (id_ + ".json")
        if reference_path.exists():
            result = solve(json.loads(reference_path.read_text(encoding="utf-8")), item["evidence"])
            atomic_json(directory / "reviewed_solved" / (id_ + ".json"), result)
            row.update(corrected=result["label"], corrected_ast_sha256=file_hash(reference_path))
        if id_ in reviews:
            review = reviews[id_]
            if not path.exists() or review["record_sha256"] != file_hash(path):
                raise ValueError("Review refers to a different completion")
            if review["corrected_ast_sha256"] != row["corrected_ast_sha256"]:
                raise ValueError("Review refers to a different diagnostic AST")
            row.update(semantic_correct=review["semantic_correct"], error_categories=";".join(review["categories"]))
        rows.append(row)
    if len(response_ids) != len(set(response_ids)) or any(x is None for x in response_ids):
        raise ValueError("Missing/duplicate provider response identities")
    aggregates = {}
    for name, subset in [("all", rows), *[(d, [r for r in rows if r["dataset"] == d]) for d in ("challenge", "basic")]]:
        aggregates[name] = {arm: metrics(subset, arm) for arm in ("A27", "V6", "corrected")}
        aggregates[name].update(semantic_reviewed=sum(r["semantic_correct"] is not None for r in subset),
            semantic_correct=sum(r["semantic_correct"] is True for r in subset),
            semantic_accuracy_all_scheduled=sum(r["semantic_correct"] is True for r in subset) / len(subset),
            schema_valid=sum(r["schema_valid"] is True for r in subset),
            ast_executable=sum(r["ast_executable"] for r in subset),
            cost={k: sum(r[k] for r in subset) for k in ("prompt_tokens", "completion_tokens", "total_tokens", "latency_seconds", "server_seconds", "solver_seconds", "http_attempts", "A27_total_tokens")})
    mechanisms = []
    for dataset, mechanism in sorted({(r["dataset"], r["mechanism"]) for r in rows}):
        subset = [r for r in rows if (r["dataset"], r["mechanism"]) == (dataset, mechanism)]
        mechanisms.append({"dataset": dataset, "mechanism": mechanism, "n": len(subset),
            "A27_correct": sum(r["A27"] == r["gold"] for r in subset),
            "V6_correct": sum(r["V6"] == r["gold"] for r in subset),
            "V6_covered": sum(r["V6"] in LABELS for r in subset),
            "semantic_correct": sum(r["semantic_correct"] is True for r in subset),
            "reviewed_AST_solved": sum(r["corrected"] in LABELS for r in subset)})
    totals = aggregates["all"]
    summary = {"purpose": manifest["purpose"], "scheduled": len(rows), "received": len(records),
        "semantic_review_complete": len(reviews) == len(rows), "metrics": aggregates, "mechanisms": mechanisms,
        "error_counts": dict(Counter(cat for r in reviews.values() for cat in r["categories"])),
        "corrected_disagrees_with_gold": [r["id"] for r in rows if r["corrected"] in LABELS and r["corrected"] != r["gold"]],
        "paired_improved": [r["id"] for r in rows if r["V6"] == r["gold"] and r["A27"] != r["gold"]],
        "paired_harmed": [r["id"] for r in rows if r["A27"] == r["gold"] and r["V6"] is not None and r["V6"] != r["gold"]],
        "baseline_source_sha256": file_hash(historical_path),
        "cost_note": "Tokens and observed times, not a verified bill; Free Plan inherited, no account upgrade. Latency includes pacing.",
        "reviewer": "Codex assistant; source-based semantic review, not independent human adjudication",
        "all_completed_records_replayed": True, "duplicate_completions": 0}
    atomic_json(directory / "metrics.json", summary)
    csv_file(directory / "predictions.csv", rows)
    csv_file(directory / "mechanisms.csv", mechanisms)
    write_jsonl(directory / "baseline_A27.jsonl", baseline_records)
    write_jsonl(directory / "attempts.jsonl", attempts)
    lines = ["# 第六轮：受限语义形式化 + Z3", "",
        f"真实形式化完成 {len(records)}/42；逐题语义复核 {len(reviews)}/42。历史 dev pilot 可行性实验，不是新的独立验证集。", "",
        f"本轮 V6 正确 {totals['V6']['correct']}/42，同题历史 A27 正确 {totals['A27']['correct']}/42。"
        "当前瓶颈是受限 AST 的语义翻译与表示合规性；本批独立复核 AST 全部可解，暂不建议直接扩大正式评测。", "",
        "|数据集|方法|正确/总数|准确率|覆盖率|S 召回|R 召回|NEI 召回|",
        "|---|---|---:|---:|---:|---:|---:|---:|"]
    for dataset in ("challenge", "basic", "all"):
        for arm in ("A27", "V6"):
            m = aggregates[dataset][arm]
            recalls = "|".join(pct(m["classes"][label]["recall"]) for label in LABELS)
            lines.append(f"|{dataset}|{arm}|{m['correct']}/{m['scheduled']}|{pct(m['accuracy_all_scheduled'])}|{pct(m['coverage'])}|{recalls}|")
    lines += ["", f"语义翻译严格正确：{totals['semantic_correct']}/42（{pct(totals['semantic_accuracy_all_scheduled'])}）；"
              f"JSON Schema 合规：{totals['schema_valid']}/42；可执行 AST：{totals['ast_executable']}/42。",
              f"独立复核 AST 求解覆盖：{totals['corrected']['valid']}/42；与冻结 gold 一致：{totals['corrected']['correct']}/42。", "",
              "UNSUPPORTED 计入端到端错误，并另报覆盖率。Schema 合规不等于类型正确、原文引用正确或语义正确。"
              "语义准确率按逐题原文审阅判定，不以标签碰巧相同代替。", "",
              "## 分机制", "", "|数据集|机制|A27 正确|V6 正确|V6 覆盖|语义正确|总数|", "|---|---|---:|---:|---:|---:|---:|"]
    for m in mechanisms:
        lines.append(f"|{m['dataset']}|{m['mechanism']}|{m['A27_correct']}|{m['V6_correct']}|{m['V6_covered']}|{m['semantic_correct']}|{m['n']}|")
    cost = totals["cost"]
    lines += ["", "## 成本与审计", "",
              f"正式输入 {cost['prompt_tokens']:,} token，输出 {cost['completion_tokens']:,} token，合计 {cost['total_tokens']:,} token；"
              f"平均每个已完成样本 {cost['total_tokens']/len(records) if records else 0:.1f} token。同题 A27 历史总量 {cost['A27_total_tokens']:,} token。",
              f"HTTP 尝试 {cost['http_attempts']} 次；客户端累计 {cost['latency_seconds']:.2f} 秒（含限速），"
              f"成功响应服务端时间 {cost['server_seconds']:.2f} 秒，离线校验/编译/Z3 求解累计 {cost['solver_seconds']:.3f} 秒。", "",
              "未查询账单，不能将免费额度参考或 token 用量冒充实际美元费用。探针成本和全阶段额度另见 execution_audit.json。",
              "逐题原始响应、实际请求参数、响应标识哈希、usage 和速率头位于 records/；公式和三次 SAT 状态位于 solved/。",
              "第四轮 A27 原始记录已按精确 Evidence/Claim 重新对齐，位于 baseline_A27.jsonl。", "",
              "## 语义复核与下一步", "",
              "逐题复核见 semantic_review.json，独立修正 AST 见 reviewed_asts/，其实际求解结果见 reviewed_solved/。"
              "这些是助手语义审阅，并非外部人工标注；修正只用于错误归因，不替换正式预测。",
              "具体错误、时间歧义与是否扩大到未使用 dev group 的建议见 [ANALYSIS.md](ANALYSIS.md)。"]
    atomic_bytes(directory / "RESULTS.md", ("\n".join(lines) + "\n").encode("utf-8"))
    return {"received": len(records), "reviewed": len(reviews), "V6_correct": totals["V6"]["correct"],
            "A27_correct": totals["A27"]["correct"], "semantic_correct": totals["semantic_correct"]}
