"""Additive scheduling amendment: early complete-validation descriptive reports.

All physical calls use the unchanged frozen Runtime/direct/fusion functions.
This module neither chooses checkpoints nor writes a final recommendation.
"""
import argparse
from collections import Counter
from contextlib import ExitStack
import csv
import io
from pathlib import Path
from statistics import mean, stdev

from . import finetune27b_v2 as c, fusion_v18 as f, fusion_v18_run as run
from .fusion_v18_report import records
from .metrics import compute_metrics

MANIFEST = f.EXP / 'priority_schedule.json'


def stages(protocol):
    first = ['base_a0', 'old_a0_42', 'old_np_42']
    seeds = first + ['old_a0_43', 'old_np_43', 'old_a0_44', 'old_np_44']
    direct = seeds + [a for a in protocol['direct'] if not a.startswith('distill_') and a not in seeds]
    fusion = [a for a, spec in protocol['fusion'].items()
              if not any(x.startswith('distill_') for x in spec['components'])]
    return {'seed42': {'direct': first, 'fusion': []},
            'three_seeds': {'direct': seeds, 'fusion': []},
            'direct_all': {'direct': direct, 'fusion': []},
            'fusion_all': {'direct': direct, 'fusion': fusion}}


def verify():
    protocol = f.verify()
    runtime = run.verify_runtime()
    manifest = c.read_json(f.ROOT / MANIFEST)
    if (manifest['original_runtime_sha256'] != runtime
            or manifest['original_freeze_sha256'] != c.sha(f.ROOT / f.EXP / 'freeze.json')
            or manifest['supervision_sha256'] != c.sha(f.ROOT / f.EXP / 'supervision/completion.json')
            or manifest['stages'] != stages(protocol)
            or manifest['stage_order'] != list(stages(protocol))):
        raise ValueError('Priority amendment identity changed')
    for relative, digest in manifest['files'].items():
        if c.sha(f.ROOT / relative) != digest:
            raise ValueError('Priority execution code changed: ' + relative)
    return manifest, protocol


def subset(protocol, stage):
    selected = stages(protocol)[stage]
    result = {**protocol}
    for kind in ('direct', 'fusion'):
        result[kind] = {a: protocol[kind][a] for a in selected[kind]}
    return result


def execute(rt, stage):
    """Only change traversal order/catalogue; computation and cache identities stay fixed."""
    original = rt.p
    chosen = subset(original, stage)
    try:
        for arm in chosen['direct']:
            rt.args.arm = arm
            run.direct(rt)
        if chosen['fusion']:
            rt.p = chosen
            run.fusion(rt)
    finally:
        rt.p = original


def independent_check(rows, predictions, scores):
    """Recompute strict labels/counts and F1 without the metrics implementation."""
    import re
    for dataset in ('basic', 'challenge'):
        selected = [r for r in rows if r['dataset'] == dataset]
        for arm, values in predictions.items():
            cells = Counter()
            for row in selected:
                record = values[c.record_key(row)]
                lines = [s.strip() for s in record['text'].splitlines() if s.strip()]
                match = re.fullmatch(r'Verdict: (SUPPORTS|REFUTES|NOT ENOUGH INFO)', lines[-1]) if lines else None
                invalid = (not record['finished'] or record.get('thinking_generated')
                           or re.search(r'</?think\b', record.get('raw_text', '') + record['text'], re.I))
                label = match.group(1) if match and not invalid else 'INVALID'
                if label != record['prediction']:
                    raise ValueError('Independent priority parser differs')
                cells[row['label'], label] += 1
            metric = scores[dataset][arm]
            assert metric['n'] == len(selected)
            assert metric['correct'] == sum(cells[label, label] for label in c.LABELS)
            assert metric['invalid'] == sum(cells[label, 'INVALID'] for label in c.LABELS)
            f1s = []
            for label in c.LABELS:
                support = sum(n for (gold, _), n in cells.items() if gold == label)
                predicted = sum(n for (_, prediction), n in cells.items() if prediction == label)
                assert metric['classes'][label]['recall'] == (cells[label, label] / support if support else None)
                if support:
                    f1s.append(2 * cells[label, label] / (support + predicted))
            assert abs(metric['macro_f1'] - mean(f1s)) < 1e-12


def descriptive(rows, predictions, protocol):
    scores, families, corrections = {}, {}, {}
    for dataset in ('basic', 'challenge'):
        selected = [r for r in rows if r['dataset'] == dataset]
        scores[dataset] = {a: compute_metrics(c.metric_rows(selected,
            {c.record_key(r): values[c.record_key(r)] for r in selected})) for a, values in predictions.items()}
        families[dataset] = {}
        corrections[dataset] = {}
        for family, members in protocol['families'].items():
            available = [a for a in members if a in predictions]
            if not available:
                continue
            values = [scores[dataset][a] for a in available]
            families[dataset][family] = {'members': available, 'all_seeds_present': available == members,
                'accuracy_mean': mean(v['accuracy'] for v in values),
                'accuracy_stdev': stdev(v['accuracy'] for v in values) if len(values) > 1 else None,
                'macro_f1_mean': mean(v['macro_f1'] for v in values)}
        for arm, values in predictions.items():
            spec = protocol['direct'].get(arm, protocol['fusion'].get(arm))
            if 'seed' in spec:
                incumbents = [f"old_a0_{spec['seed']}"]
            else:
                incumbents = [a for a in protocol['families']['old_a0'] if a in predictions]
            changes = {}
            for base in incumbents:
                rescued, harmed = [], []
                for row in selected:
                    key = c.record_key(row)
                    old = predictions[base][key]['prediction'] == row['label']
                    new = values[key]['prediction'] == row['label']
                    if new and not old: rescued.append(key)
                    if old and not new: harmed.append(key)
                changes[base] = {'rescued': len(rescued), 'harmed': len(harmed),
                                 'rescued_ids': rescued, 'harmed_ids': harmed}
            corrections[dataset][arm] = changes
    guards = {}
    for arm in predictions:
        failures = []
        for dataset in ('basic', 'challenge'):
            old, new = scores[dataset]['base_a0'], scores[dataset][arm]
            if dataset == 'basic' and new['accuracy'] < old['accuracy'] - .02 - 1e-12:
                failures.append('basic_accuracy')
            for label in c.LABELS:
                if new['classes'][label]['recall'] < old['classes'][label]['recall'] - .05 - 1e-12:
                    failures.append(dataset + '/' + label)
        guards[arm] = {'passed': not failures, 'failures': failures}
    independent_check(rows, predictions, scores)
    return {'scores': scores, 'families': families, 'corrections': corrections, 'per_arm_guardrails': guards}


def report(output, stage):
    manifest, protocol = verify()
    rows, predictions = records(output, 'validation', subset(protocol, stage))
    result = descriptive(rows, predictions, protocol)
    result.update(stage=stage, n=len(rows), part='validation', descriptive_only=True,
                  no_final_recommendation=True, no_p_values_until_all_23_comparisons=True,
                  schedule_sha256=c.sha(f.ROOT / MANIFEST),
                  record_hashes={a+'/'+k: r['record_sha256'] for a, values in predictions.items() for k, r in values.items()})
    dest = output / 'priority' / stage
    f.immutable(dest / 'results.json', result)
    f.immutable(dest / 'audit.json', {'passed': True, 'rows': len(rows), 'methods': len(predictions),
                'results_sha256': c.sha(dest / 'results.json'), 'independent_parser_counts_f1': True,
                'original_record_provenance_and_fusion_dependencies_verified': True})
    lines = ['# V18 阶段性验证结果', '',
             '完整259题验证集；历史开发数据；本表只作描述，不作最终推荐或显著性结论。',
             '首阶段种子42事前固定，不按成绩挑选。后续仍补齐所有种子、方法及261题比较。', '',
             '| 方法 | 基础准确率 | 挑战准确率 | 挑战 Macro-F1 | 幅度限制 |',
             '|---|---:|---:|---:|---|']
    for arm in predictions:
        b, t = result['scores']['basic'][arm], result['scores']['challenge'][arm]
        lines.append(f"| {arm} | {b['accuracy']:.2%} | {t['accuracy']:.2%} | {t['macro_f1']:.4f} | {result['per_arm_guardrails'][arm]['passed']} |")
    lines += ['', '逐类别、无效输出、逐题修正/损害、种子均值与标准差见 results.json；主金标和题目不变。']
    (dest / 'RESULTS.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=['dataset', 'id', 'group', 'mechanism', 'gold', *predictions])
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row[k] for k in ('dataset', 'id', 'group', 'mechanism')} | {'gold': row['label']} |
                        {a: values[c.record_key(row)]['prediction'] for a, values in predictions.items()})
    (dest / 'predictions.csv').write_text(buffer.getvalue(), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['worker', 'report'])
    parser.add_argument('--stage', choices=list(stages(f.verify())), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', type=int, choices=(0, 1), default=0)
    parser.add_argument('--model', type=Path, default=Path('/root/ab_finetune27b_20261030/models/Qwen3.8-27B'))
    parser.add_argument('--formal', type=Path, default=Path('/root/ab_finetune27b_20261030/revision_2_runs/formal'))
    args = parser.parse_args()
    verify()
    if args.action == 'report':
        report(args.output, args.stage)
        return
    import fcntl
    with ExitStack() as stack:
        for action in ('direct', 'fusion'):
            path = args.output / 'locks' / f'{action}-validation-None-42-{args.worker}.lock'
            path.parent.mkdir(parents=True, exist_ok=True)
            lock = stack.enter_context(path.open('a'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        args.part = 'validation'
        args.arm = 'base_a0'
        rt = run.Runtime(args)
        f.immutable(args.output / 'priority/execution' / f'{args.stage}-{args.worker}.json',
                    {'schedule_sha256': c.sha(f.ROOT / MANIFEST), 'runtime_sha256': rt.runtime_sha,
                     'worker': args.worker, 'stage': args.stage, 'catalogue': stages(rt.p)[args.stage]})
        execute(rt, args.stage)


if __name__ == '__main__':
    main()
