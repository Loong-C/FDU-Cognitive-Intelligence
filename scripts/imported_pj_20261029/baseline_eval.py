"""认知智能课程PJ事实判断Baseline入口。运行 --help 查看命令。"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from api_client import APIError, Client, ROOT, load_config, load_key
from benchmark import (DATASETS, LABELS, digest, grouped_scores, messages_for,
                       parse_response, read_sources, sample_rows, sha, write_json)


def stamp():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def percentage(value):
    return '—' if value is None else f'{100 * value:.2f}%'


def read_records(path):
    records = {}
    if path.exists():
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                records[row['id']] = row
            except (ValueError, KeyError, TypeError):
                raise ValueError(f'{path.name}第{number}行不完整；为保留原始记录，停止并等待修复') from None
    return records


def build_manifest(args, config, prompt, audit, selections):
    code_hashes = {p: sha((ROOT / p).read_bytes()) for p in ('api_client.py', 'benchmark.py', 'baseline_eval.py')}
    settings = {'config': config, 'phase': args.phase, 'seed': args.seed, 'workers': getattr(args, 'workers', 1),
                'prompt_sha256': audit['prompt_sha256'], 'data_audit': audit,
                'selected_ids': {key: [r['id'] for r in rows] for key, rows in selections.items()},
                'code_hashes': code_hashes}
    return {'created_at': stamp(), 'fingerprint': digest(settings), 'settings': settings,
            'system_message': messages_for({'evidence': '', 'claim': ''}, prompt)[0]['content'],
            'prompt_template': prompt,
            'warning': 'W8A8与A方Q8_0并非完全相同配置；量化格式为聊天记录说明，接口未独立验证。'}


def summarize(out, selections, manifest):
    reports = {}
    for key, rows in selections.items():
        records = read_records(out / f'{key}.jsonl')
        reports[key] = grouped_scores(rows, records)
        with (out / f'{key}-predictions.csv').open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['id', 'group', 'mechanism', 'gold', 'prediction', 'status', 'parse_error', 'latency_seconds'])
            for row in rows:
                r = records.get(row['id'], {})
                values = [row['id'], row['group'], row['mechanism'], row['label'], r.get('prediction', ''),
                          r.get('status', 'pending'), r.get('parse_error', ''), r.get('latency_seconds', '')]
                writer.writerow(values)
    result = {'updated_at': stamp(), 'fingerprint': manifest['fingerprint'], 'datasets': reports}
    write_json(out / 'summary.json', result)
    lines = ['# 事实判断 Baseline 评测结果', '',
             f"模型：{manifest['settings']['config']['model']}。阶段：{manifest['settings']['phase']}。",
             'zero-shot；temperature=0；请求关闭thinking；仅输入evidence与claim。', '',
             '两份数据分别评分。Accuracy、召回率和F1的分母保留请求失败、解析失败；未完成样本记为PENDING。',
             '只有完成全部目标样本后，才可将相应结果作为该阶段的最终分数。', '',
             '原始响应见各集合JSONL，逐条对照见CSV。请求失败率按最终失败样本数/已尝试样本数计算；重试失败次数另存于逐条记录。', '',
             manifest['warning'], '']
    for key, metrics in reports.items():
        lines += [f'## {DATASETS[key][0].removesuffix(".jsonl")}', '',
                  f"完成 {metrics['completed']}/{metrics['count']}；正确 {metrics['correct']}；Accuracy {percentage(metrics['accuracy'])}；Macro-F1 {metrics['macro_f1']:.4f}。", '',
                  f"解析失败率 {percentage(metrics['parse_failure_rate'])}；请求失败率 {percentage(metrics['request_failure_rate'])}；有效预测覆盖率 {percentage(metrics['valid_prediction_coverage'])}。", '',
                  '| 标签 | 样本数 | Precision | Recall | F1 |', '| --- | ---: | ---: | ---: | ---: |']
        for label, m in metrics['per_class'].items():
            lines.append(f"| {label} | {m['support']} | {percentage(m['precision'])} | {percentage(m['recall'])} | {m['f1']:.4f} |")
        lines += ['', '混淆矩阵：行为真实标签，列为预测；失败与未完成不丢弃。', '',
                  '| 真实\\预测 | SUPPORTS | REFUTES | NOT ENOUGH INFO | 解析失败 | 请求失败 | 未完成 |',
                  '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
        for label, cells in metrics['confusion_matrix'].items():
            lines.append('| ' + label + ' | ' + ' | '.join(str(v) for v in cells.values()) + ' |')
        lines += ['', '| 机制 | 条数 | Accuracy | NEI Recall | Macro-F1 |', '| --- | ---: | ---: | ---: | ---: |']
        for mechanism, m in metrics['by_mechanism'].items():
            lines.append(f"| {mechanism} | {m['count']} | {percentage(m['accuracy'])} | {percentage(m['per_class']['NOT ENOUGH INFO']['recall'])} | {m['macro_f1']:.4f} |")
        lines += ['']
    lines += ['## A方参考值', '',
              'A方数据说明记录：Qwen3.8-27B-Q8_0在核心挑战集590/885（66.67%），基础能力集99.00%。这些是A方参考值，本次抽样结果不可当作全量比较或量化方案的因果结论。', '',
              '后续优化与训练必须先按group划分开发集和保留测试集，再进行提示词或训练调整，避免同场景变体泄漏。']
    (out / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return reports


def evaluate_one(row, previous, config, key, prompt):
    client = Client(config, key)
    record = {'id': row['id'], 'group': row['group'], 'mechanism': row['mechanism'],
              'gold': row['label'], 'timestamp': stamp(), 'prediction': None,
              'evaluation_attempt': previous.get('evaluation_attempt', 1) + 1 if previous else 1}
    try:
        raw, elapsed, failures = client.chat(messages_for(row, prompt))
        prediction, error, text = parse_response(raw)
        record.update({'status': 'ok' if prediction else 'parse_error', 'prediction': prediction,
                       'parse_error': error, 'raw_text': text, 'raw_response': raw,
                       'latency_seconds': elapsed, 'failed_request_attempts': failures})
    except APIError as exc:
        record.update({'status': 'request_error', 'error_kind': exc.kind, 'http_status': exc.status,
                       'latency_seconds': exc.elapsed, 'failed_request_attempts': exc.failures})
    return record


def run(args, config, key):
    datasets, prompt, audit = read_sources()
    wanted = list(DATASETS) if args.dataset == 'all' else [args.dataset]
    limit = args.limit if args.limit is not None else (20 if args.phase == 'smoke' else None)
    if args.phase == 'full' and limit is not None:
        raise ValueError('full阶段必须评测全部数据；抽样请使用smoke阶段')
    workers = getattr(args, 'workers', 1)
    if not 1 <= workers <= 8:
        raise ValueError('并发数应在1至8之间')
    selections = {name: sample_rows(datasets[name], limit, args.seed) for name in wanted}
    manifest = build_manifest(args, config, prompt, audit, selections)
    out = Path(args.out).resolve() if args.out else ROOT / 'results' / (args.phase + '-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / 'manifest.json'
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not args.resume or old['fingerprint'] != manifest['fingerprint']:
            raise ValueError('已有结果需显式--resume，且数据、代码、配置与抽样必须完全一致；否则请用新目录')
        manifest = old
    else:
        if any(out.iterdir()):
            raise ValueError('结果目录非空且没有manifest，请使用新目录')
        write_json(manifest_path, manifest)
    client = Client(config, key)
    ids, _ = client.models()
    if config['model'] not in ids:
        raise ValueError('服务端模型列表中没有配置的模型')
    aborted = None
    try:
        for name, rows in selections.items():
            path = out / f'{name}.jsonl'
            records = read_records(path)
            selected_ids = {r['id'] for r in rows}
            if set(records) - selected_ids:
                raise ValueError('结果记录含不在manifest中的样本')
            pending = [row for row in rows if row['id'] not in records or
                       args.retry_failed and records[row['id']]['status'] != 'ok']
            with ThreadPoolExecutor(max_workers=workers) as pool:
                # 有界批次：遇到鉴权/服务错误时，不再发送后续批次。
                for offset in range(0, len(pending), workers):
                    futures = [pool.submit(evaluate_one, row, records.get(row['id']), config, key, prompt)
                               for row in pending[offset:offset + workers]]
                    for future in as_completed(futures):
                        record = future.result()
                        with path.open('a', encoding='utf-8') as f:
                            f.write(json.dumps(record, ensure_ascii=False) + '\n')
                            f.flush()
                            os.fsync(f.fileno())
                        records[record['id']] = record
                        print(f"{name}: {len(records)}/{len(rows)} {record['status']}", flush=True)
                        if record['status'] == 'request_error' or record.get('parse_error') == 'thinking_not_disabled':
                            aborted = record.get('error_kind') or record.get('parse_error')
                    if aborted:
                        break
            if aborted:
                break
    except KeyboardInterrupt:
        aborted = 'user_interrupted'
    finally:
        reports = summarize(out, selections, manifest)
        write_json(out / 'run_status.json', {'updated_at': stamp(), 'aborted_reason': aborted,
                   'complete': all(m['completed'] == m['count'] for m in reports.values()),
                   'all_outputs_valid': all(m['status_counts']['ok'] == m['count'] for m in reports.values())})
        print(f'结果已保存：{out}', flush=True)
    return 2 if aborted or any(m['status_counts']['ok'] != m['count'] for m in reports.values()) else 0


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description='认知智能课程PJ三分类事实核查Baseline')
    p.add_argument('command', choices=('audit', 'check', 'run'))
    p.add_argument('--config', type=Path)
    p.add_argument('--phase', choices=('smoke', 'full'), default='smoke')
    p.add_argument('--dataset', choices=('all', 'challenge', 'basic'), default='all')
    p.add_argument('--limit', type=int)
    p.add_argument('--seed', type=int, default=20261027)
    p.add_argument('--workers', type=int, default=1, help='同时在途请求数，1至8；首次建议1')
    p.add_argument('--out')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--retry-failed', action='store_true')
    args = p.parse_args()
    try:
        if args.command == 'audit':
            _, _, audit = read_sources()
            write_json(ROOT / 'data' / 'audit.json', audit)
            print(json.dumps(audit, ensure_ascii=False, indent=2))
            return 0
        config, key = load_config(args.config), load_key()
        if not key:
            raise ValueError('请先在本项目.env中填写QWEN_API_KEY')
        if args.command == 'check':
            ids, elapsed = Client(config, key).models()
            result = {'checked_at': stamp(), 'key_configured': bool(key), 'models': ids,
                      'expected_model_found': config['model'] in ids, 'elapsed_seconds': elapsed}
            (ROOT / 'results').mkdir(exist_ok=True)
            write_json(ROOT / 'results' / 'api_check.json', result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['expected_model_found'] else 2
        if args.retry_failed and not args.resume:
            raise ValueError('--retry-failed必须与--resume一起使用')
        return run(args, config, key)
    except (APIError, ValueError, KeyError, OSError) as exc:
        # 不打印服务端错误正文或密钥，只输出程序定义的错误。
        print(f'停止：{exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
