"""比较相同数据与提示词、不同输出长度上限的两轮完整评测。"""
import argparse
import json
import sys
from pathlib import Path

from baseline_eval import percentage, read_records
from benchmark import DATASETS, LABELS, write_json


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    p.add_argument('first', type=Path)
    p.add_argument('second', type=Path)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    paths = [args.first, args.second]
    manifests = [json.loads((d / 'manifest.json').read_text(encoding='utf-8')) for d in paths]
    statuses = [json.loads((d / 'run_status.json').read_text(encoding='utf-8')) for d in paths]
    if not all(s['complete'] for s in statuses):
        raise SystemExit('两轮均完成后才生成对照')
    settings = [m['settings'] for m in manifests]
    for field in ('phase', 'seed', 'workers', 'prompt_sha256', 'data_audit', 'selected_ids', 'code_hashes'):
        if settings[0][field] != settings[1][field]:
            raise SystemExit('两轮对照条件不一致：' + field)
    configs = [{k: v for k, v in s['config'].items() if k != 'max_tokens'} for s in settings]
    if configs[0] != configs[1]:
        raise SystemExit('除max_tokens外的参数不一致')
    caps = [s['config']['max_tokens'] for s in settings]
    summaries = [json.loads((d / 'summary.json').read_text(encoding='utf-8'))['datasets'] for d in paths]
    if set(summaries[0]) != set(DATASETS) or set(summaries[1]) != set(DATASETS):
        raise SystemExit('每轮必须分别完成两份集合')
    result = {'max_tokens': caps, 'datasets': {}, 'other_settings_match': True}
    lines = ['# 输出长度上限的两轮对照', '',
             f'两轮分别使用max_tokens={caps[0]}与{caps[1]}；模型、提示词、数据、并发和其他请求参数一致。temperature均为0，关闭thinking。', '',
             '每轮均重新请求所有样本，未把第一轮截断样本的重试结果混入第一轮。两轮结果的差异还可能包含服务端响应波动，不能仅归因为输出上限。', '']
    for name in DATASETS:
        old, new = [s[name] for s in summaries]
        records = [read_records(d / (name + '.jsonl')) for d in paths]
        if set(records[0]) != set(records[1]):
            raise SystemExit('两轮实际样本ID不一致')
        counts = {}
        for i, rows in enumerate(records):
            counts[str(caps[i])] = {
                'truncated': sum(r.get('parse_error') == 'truncated' for r in rows.values()),
                'completion_tokens': sum((r.get('raw_response', {}).get('usage') or {}).get('completion_tokens', 0) for r in rows.values()),
                'reasoning_tokens': sum(((r.get('raw_response', {}).get('usage') or {}).get('completion_tokens_details') or {}).get('reasoning_tokens', 0) or 0 for r in rows.values()),
            }
        transitions = {'wrong_to_correct': 0, 'correct_to_wrong': 0, 'same_prediction': 0,
                       'first_truncated_then_valid': 0, 'both_truncated': 0}
        for sample_id, a in records[0].items():
            b = records[1][sample_id]
            ac, bc = a['prediction'] == a['gold'], b['prediction'] == b['gold']
            transitions['wrong_to_correct'] += not ac and bc
            transitions['correct_to_wrong'] += ac and not bc
            transitions['same_prediction'] += a['prediction'] == b['prediction']
            transitions['first_truncated_then_valid'] += a.get('parse_error') == 'truncated' and b['status'] == 'ok'
            transitions['both_truncated'] += a.get('parse_error') == 'truncated' and b.get('parse_error') == 'truncated'
        result['datasets'][name] = {'first': old, 'second': new, 'output_usage': counts,
                                     'transitions': transitions, 'accuracy_delta_percentage_points': 100 * (new['accuracy'] - old['accuracy'])}
        lines += [f'## {DATASETS[name][0].removesuffix(".jsonl")}', '',
                  f'| 指标 | 上限{caps[0]} | 上限{caps[1]} |', '| --- | ---: | ---: |',
                  f"| 正确/总数 | {old['correct']}/{old['count']} | {new['correct']}/{new['count']} |",
                  f"| Accuracy | {percentage(old['accuracy'])} | {percentage(new['accuracy'])} |",
                  f"| Macro-F1 | {old['macro_f1']:.4f} | {new['macro_f1']:.4f} |"]
        for label in LABELS:
            lines.append(f"| {label} Recall | {percentage(old['per_class'][label]['recall'])} | {percentage(new['per_class'][label]['recall'])} |")
        lines += [f"| 截断数 | {counts[str(caps[0])]['truncated']} | {counts[str(caps[1])]['truncated']} |",
                  f"| 请求失败率 | {percentage(old['request_failure_rate'])} | {percentage(new['request_failure_rate'])} |",
                  f"| 解析失败率 | {percentage(old['parse_failure_rate'])} | {percentage(new['parse_failure_rate'])} |",
                  f"| 平均请求耗时（秒） | {old['mean_latency_seconds']:.3f} | {new['mean_latency_seconds']:.3f} |",
                  f"| 输出token总数 | {counts[str(caps[0])]['completion_tokens']} | {counts[str(caps[1])]['completion_tokens']} |", '',
                  f"Accuracy变化：{100 * (new['accuracy'] - old['accuracy']):+.2f}个百分点；错误→正确{transitions['wrong_to_correct']}条，正确→错误{transitions['correct_to_wrong']}条。", '',
                  f"第一轮截断而第二轮正常解析{transitions['first_truncated_then_valid']}条，两轮均截断{transitions['both_truncated']}条。", '']
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / '两轮对照.json', result)
    (args.out / '两轮对照.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('两轮对照已生成。')


if __name__ == '__main__':
    main()
