"""Explicit V18 deadline amendment; original training and generation code is unchanged."""
import argparse
from collections import Counter, defaultdict
import csv
import importlib.util
import io
from pathlib import Path
import shutil
import time

from . import finetune27b_v2 as c, fusion_v18 as f
from . import fusion_v18_run as run, fusion_v18_report as full, fusion_v18_priority as priority

MANIFEST = f.EXP / 'quick24_schedule.json'
NEW = [f'distill_{s}_{seed}' for s in f.SOURCES for seed in f.SEEDS]
CORE = ['base_a0', *[f'old_a0_{seed}' for seed in f.SEEDS], *NEW]


def verify():
    p = f.verify()
    runtime = run.verify_runtime()
    priority.verify()
    m = c.read_json(f.ROOT / MANIFEST)
    if (m['original_runtime_sha256'] != runtime
            or m['original_freeze_sha256'] != c.sha(f.ROOT / f.EXP / 'freeze.json')
            or m['supervision_sha256'] != c.sha(f.ROOT / f.EXP / 'supervision/completion.json')
            or m['core_arms'] != CORE or m['fixed_epoch'] != 3 or m['holm_family_size'] != 23
            or m['stop_compute_unix'] > m['deadline_unix'] - 3600):
        raise ValueError('Quick amendment identity changed')
    for name, digest in m['files'].items():
        if c.sha(f.ROOT / name) != digest:
            raise ValueError('Quick execution file changed: ' + name)
    return m, p


def check_deadline(now=None):
    m = c.read_json(f.ROOT / MANIFEST)
    if (time.time() if now is None else now) >= m['stop_compute_unix']:
        raise TimeoutError('Quick24 compute deadline reached')


def catalog(p, part):
    if part not in ('validation', 'evaluation'):
        raise ValueError('Only frozen development partitions allowed')
    if part == 'validation':
        keep = priority.stages(p)['fusion_all']
        direct, fusion = [*keep['direct'], *NEW], keep['fusion']
    else:
        direct, fusion = CORE, []
    arms = set(direct + fusion)
    return {**p, 'direct': {a: p['direct'][a] for a in direct},
            'fusion': {a: p['fusion'][a] for a in fusion},
            'families': {n: v for n, v in p['families'].items() if set(v) <= arms}}


def snapshot_adapter(old, output, arm):
    """A fixed-epoch receipt, deliberately NOT an original selection.json."""
    if arm not in NEW:
        raise ValueError('Only new three-epoch adapters have quick receipts')
    _, source, seed = arm.split('_')
    folder = old / 'training' / source / f'seed-{seed}'
    done = c.read_json(folder / 'training_complete.json')
    entry = c.read_json(folder / 'epoch-3.json')
    receipt = entry['receipt']
    from .fusion_v18_training import identity
    smoke = c.read_json(old / 'training' / source / 'smoke/receipt.json')
    expected = identity(f.training_protocol(source), smoke['environment'], int(seed))
    if (not smoke['passed'] or done != {'identity': expected, 'epochs': 3}
            or entry['epoch'] != 3 or receipt['epoch'] != 3 or receipt['cursor'] != 728
            or receipt['identity'] != expected):
        raise ValueError('Incomplete or wrong third-epoch training')
    checkpoint = folder / entry['checkpoint']
    if not checkpoint.resolve().is_relative_to(folder.resolve()):
        raise ValueError('Checkpoint outside training directory')
    if c.read_json(checkpoint / 'receipt.json') != receipt:
        raise ValueError('Checkpoint receipt changed')
    for name, key in [('adapter_model.safetensors', 'adapter_sha256'),
                      ('adapter_config.json', 'adapter_config_sha256')]:
        if c.sha(checkpoint / name) != receipt[key]:
            raise ValueError('Third-epoch weights changed')
    value = {'arm': arm, 'policy': 'fixed_epoch_3_no_validation_selection',
             'source': source, 'seed': int(seed), 'checkpoint': checkpoint.relative_to(old).as_posix(),
             'training_complete': done, 'epoch_receipt': entry,
             'training_complete_sha256': c.sha(folder / 'training_complete.json'),
             'epoch_file_sha256': c.sha(folder / 'epoch-3.json')}
    f.immutable(output / 'adapters' / (arm + '.json'), value)
    return checkpoint, value


def import_validation(old, output):
    """Copy immutable answers; a source manifest keeps aliases from being new calls."""
    _, p = verify()
    source = old / 'priority/fusion_all'
    if not c.read_json(source / 'audit.json')['passed']:
        raise ValueError('Old priority report not audited')
    expected = c.read_json(source / 'results.json')
    rows, predictions = full.records(old, 'validation', priority.subset(p, 'fusion_all'))
    hashes = {a + '/' + k: r['record_sha256'] for a, rs in predictions.items() for k, r in rs.items()}
    if hashes != expected['record_hashes']:
        raise ValueError('Imported old records changed')
    paths = set()
    for arm, values in predictions.items():
        kind = 'direct' if arm in p['direct'] else 'fusion'
        for key, record in values.items():
            paths.add(Path('validation') / kind / arm / (key + '.json'))
            paths.update(Path(x) for x in record.get('call_refs', []))
    imports = {}
    for rel in sorted(paths):
        src, dest = old / rel, output / rel
        if not src.resolve().is_relative_to((old / 'validation').resolve()):
            raise ValueError('Invalid import path')
        imports[rel.as_posix()] = c.sha(src)
        if dest.exists() and c.sha(dest) != c.sha(src):
            raise ValueError('Import would overwrite a different answer')
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    f.immutable(output / 'imported_validation.json', {
        'source_run': str(old), 'source_report_sha256': c.sha(source / 'results.json'),
        'files': imports, 'new_physical_calls': 0, 'rows': len(rows)})


def recommendation_gate(output):
    rec = c.read_json(output / 'quick_recommendation.json')
    audit = c.read_json(output / 'validation/audit.json')
    if (not audit['passed'] or rec['validation_results_sha256'] != c.sha(output / 'validation/results.json')
            or audit['results_sha256'] != rec['validation_results_sha256']
            or rec['schedule_sha256'] != c.sha(f.ROOT / MANIFEST)):
        raise ValueError('Quick validation/recommendation gate failed')
    for arm, digest in rec['adapter_receipt_hashes'].items():
        if c.sha(output / 'adapters' / (arm + '.json')) != digest:
            raise ValueError('Fixed adapter changed after recommendation')
    return rec


def dependencies(output, arm):
    values = [c.sha(f.ROOT / MANIFEST)]
    if arm in NEW:
        values.append(c.sha(output / 'adapters' / (arm + '.json')))
    return values


def worker(args):
    verify(); check_deadline()
    smoke_count = getattr(args, 'smoke_count', 0)
    if smoke_count and (smoke_count != 3 or args.part != 'validation' or args.arm != 'distill_nli_42'):
        raise ValueError('Smoke is the three fixed first NLI-42 validation calls only')
    if args.part == 'evaluation':
        recommendation_gate(args.output)
        arms = CORE
    else:
        if args.arm not in NEW:
            raise ValueError('Old validation answers must be reused')
        arms = [args.arm]
    import fcntl
    lock = args.output / 'locks' / f'{args.part}-{args.arm}-{args.worker}.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rt = run.Runtime(args)
        env = {'environment_sha256': c.digest(rt.env), 'runtime_sha256': rt.runtime_sha,
               'schedule_sha256': c.sha(f.ROOT / MANIFEST)}
        with (args.output / 'locks/inference-environment.lock').open('a') as shared:
            fcntl.flock(shared, fcntl.LOCK_EX)
            f.immutable(args.output / 'inference_environment.json', env)
        all_rows = f.data(args.part)
        rows = [r for i, r in enumerate(all_rows) if args.part == 'validation' or i % 2 == args.worker]
        # Same inputs and greedy inference; run the longest actual token input first.
        longest = max(rows, key=lambda r: len(run.engine.encode(r, rt.tokenizer, rt.train_p,
                      require_target=False, enforce_limit=False)['prefix']))
        rows = [longest] + [r for r in rows if c.record_key(r) != c.record_key(longest)]
        if smoke_count: rows = rows[:smoke_count]
        smoke_records = []
        for arm in arms:
            check_deadline()
            if arm in NEW:
                folder, _ = snapshot_adapter(args.old_output, args.output, arm)
                rt.activate(arm, folder)
            else:
                rt.activate(rt.p['direct'][arm]['adapter'])
            for row in rows:
                check_deadline()
                relative = Path(args.part) / 'direct' / arm / (c.record_key(row) + '.json')
                record = rt.call(row, rt.prompts['a0'], relative, 'quick24_' + args.part,
                                 dependencies(args.output, arm))
                if smoke_count: smoke_records.append(record)
        if smoke_count:
            f.immutable(args.output / 'smoke_receipt.json', {
                'completed': True, 'calls_reused_in_validation': len(smoke_records),
                'longest_actual_validation_input_first': True,
                'valid_outputs': sum(r['prediction'] != 'INVALID' for r in smoke_records),
                'seconds': [r['seconds'] for r in smoke_records],
                'record_hashes': [r['record_sha256'] for r in smoke_records]})


def load_records(output, part, p):
    rows = f.data(part)
    selected = catalog(p, part)
    result = {}
    if part == 'validation':
        imports = c.read_json(output / 'imported_validation.json')
        for rel, digest in imports['files'].items():
            if c.sha(output / rel) != digest:
                raise ValueError('Imported answer bytes changed')
        _, result = full.records(output, part, priority.subset(p, 'fusion_all'))
    env = c.read_json(output / 'inference_environment.json')
    prompts = c.read_json(f.ROOT / f.EXP / 'prompts.json')
    for arm in (NEW if part == 'validation' else CORE):
        expected_adapter = None
        if arm in NEW:
            snap = c.read_json(output / 'adapters' / (arm + '.json'))
            expected_adapter = snap['epoch_receipt']['receipt']['adapter_sha256']
            if snap['policy'] != 'fixed_epoch_3_no_validation_selection' or snap['epoch_receipt']['epoch'] != 3:
                raise ValueError('Wrong checkpoint policy')
        elif arm.startswith('old_'):
            expected_adapter = p['old_adapters'][arm.rsplit('_', 1)[1]]['adapter_sha256']
        result[arm] = {}
        for row in rows:
            key = c.record_key(row)
            rel = Path(part) / 'direct' / arm / (key + '.json')
            value = f.check_record(c.read_json(output / rel)); ident = value['identity']
            expected_input = c.digest(c.messages(row, prompts['a0']))
            expected = {'freeze': c.sha(f.ROOT / f.EXP / 'freeze.json'),
                        'runtime': env['runtime_sha256'], 'environment': env['environment_sha256'],
                        'adapter_sha256': expected_adapter, 'phase': 'quick24_' + part,
                        'input_sha256': expected_input, 'input_token_sha256': value['input_token_sha256'],
                        'generation': p['generation'], 'dependencies': dependencies(output, arm)}
            if (ident != expected or value['input_sha256'] != expected_input
                    or value['physical_call'] != rel.as_posix()
                    or (value['dataset'], value['id']) != (row['dataset'], row['id'])):
                raise ValueError('Quick answer provenance mismatch')
            result[arm][key] = value
    if set(result) != set(selected['direct']) | set(selected['fusion']):
        raise ValueError('Wrong quick method catalogue')
    return rows, result, selected


def summarize(rows, predictions, selected, original):
    value = full.summarize(rows, predictions, selected)
    # Preserve all 23 planned contrasts, even though the scope was reduced.
    for data in value['datasets'].values():
        pairs = data['pairs']
        available = {v['method'] for v in pairs}
        for item in pairs:
            item['evaluated'] = True
        pairs.extend({'method': family, 'p': 1., 'evaluated': False, 'reason': 'not_in_quick_scope'}
                     for family in original['families'] if family != f.INCUMBENT and family not in available)
        if len(pairs) != 23:
            raise ValueError('Holm family must retain 23 hypotheses')
        full.holm(pairs)
    gains = {v['method']: v for v in value['datasets']['challenge']['pairs'] if v['evaluated']}
    for name, state in value['success'].items():
        state['development_statistical_support'] = bool(state['point_improvement_and_guardrails']
                                                        and gains[name]['holm_p'] <= .05)
    value['corrections'] = priority.descriptive(rows, predictions, selected)['corrections']
    return value


def choose(result, p):
    # Recommendation domain is fixed before evaluation: five families / 13 arms.
    eligible = [f'distill_{s}' for s in f.SOURCES
                if result['success'][f'distill_{s}']['point_improvement_and_guardrails']]
    def key(name):
        b = result['datasets']['basic']['families'][name]
        t = result['datasets']['challenge']['families'][name]
        return (-int(result['guardrails'][name]['passed']), -t['accuracy'], -b['accuracy'],
                -t['macro_f1'], b['mean_calls'] + t['mean_calls'], b['mean_tokens'] + t['mean_tokens'], name)
    return min(eligible or ['base_a0', f.INCUMBENT], key=key), bool(eligible)


def physical_cost(output):
    calls = {}
    for part in ('validation', 'evaluation'):
        for kind in ('direct', 'review_calls'):
            for path in (output / part / kind).glob('*/*.json'):
                r = f.check_record(c.read_json(path))
                identity = (r['identity']['phase'], r['physical_call'])
                previous = calls.setdefault(identity, r)
                if previous != r:
                    raise ValueError('Conflicting physical call aliases')
    phases = {}
    for r in calls.values():
        item = phases.setdefault(r['identity']['phase'], {'calls': 0, 'input_tokens': 0, 'output_tokens': 0, 'seconds': 0.})
        item['calls'] += 1
        for field in ('input_tokens', 'output_tokens', 'seconds'):
            item[field] += r[field]
    return {'physical_by_phase': phases, 'calls': len(calls),
            'note': 'Original validation imports are reused calls; fusion logical component costs are not extra physical calls.'}


def independent_audit(output, part, rows, predictions, protocol, result):
    spec = importlib.util.spec_from_file_location('independent_quick_base', f.ROOT / 'scripts/audit_fusion_v18.py')
    audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
    for dataset in ('basic', 'challenge'):
        group = [r for r in rows if r['dataset'] == dataset]
        scores = result['datasets'][dataset]['scores']
        for arm, rs in predictions.items():
            cells = Counter()
            for row in group:
                record = rs[c.record_key(row)]
                label = audit.parse(record)
                assert label == record['prediction']
                cells[row['label'], label] += 1
            metric = scores[arm]
            assert metric['n'] == len(group)
            assert metric['correct'] == sum(cells[label, label] for label in c.LABELS)
            assert metric['invalid'] == sum(cells[label, 'INVALID'] for label in c.LABELS)
            assert metric['accuracy'] == metric['correct'] / len(group)
            f1s = []
            for label in c.LABELS:
                support = sum(n for (gold, _), n in cells.items() if gold == label)
                predicted = sum(n for (_, pred), n in cells.items() if pred == label)
                assert metric['classes'][label]['recall'] == cells[label, label] / support
                for pred in (*c.LABELS, 'INVALID'):
                    assert metric['confusion_matrix'][label][pred] == cells[label, pred]
                f1s.append(2 * cells[label, label] / (support + predicted))
            assert abs(metric['macro_f1'] - sum(f1s) / 3) < 1e-12
        pairs = result['datasets'][dataset]['pairs']; assert len(pairs) == 23
        for pair in pairs:
            if not pair['evaluated']:
                assert pair['p'] == 1 and pair['method'] not in protocol['families']
                continue
            effects = defaultdict(int)
            for row in group:
                key = c.record_key(row)
                for family, sign in ((pair['method'], 1), (f.INCUMBENT, -1)):
                    members = protocol['families'][family]
                    effects[row['group']] += sign * (3 // len(members)) * sum(predictions[a][key]['prediction'] == row['label'] for a in members)
            assert dict(effects) == pair['group_deltas_scaled_3']
            assert audit.group_p(list(effects.values())) == pair['p']
        previous = 0.
        for index, pair in enumerate(sorted(pairs, key=lambda v: v['p'])):
            previous = max(previous, min(1., pair['p'] * (23 - index)))
            assert abs(previous - pair['holm_p']) < 1e-12
    for family, members in protocol['families'].items():
        passed = True
        for arm in members:
            for dataset in ('basic', 'challenge'):
                scores = result['datasets'][dataset]['scores']; base, v = scores['base_a0'], scores[arm]
                if dataset == 'basic': passed &= v['accuracy'] >= base['accuracy'] - .02 - 1e-12
                passed &= all(v['classes'][l]['recall'] >= base['classes'][l]['recall'] - .05 - 1e-12 for l in c.LABELS)
        assert bool(passed) == result['guardrails'][family]['passed']
        for dataset in ('basic', 'challenge'):
            scores = result['datasets'][dataset]['scores']
            summary = result['datasets'][dataset]['families'][family]
            for field in ('accuracy', 'macro_f1'):
                assert abs(summary[field] - sum(scores[a][field] for a in members) / len(members)) < 1e-12
        if family != f.INCUMBENT:
            contrast = next(v for v in result['datasets']['challenge']['pairs'] if v['method'] == family)
            success = bool(passed and contrast['accuracy_delta'] > 0)
            assert result['success'][family]['point_improvement_and_guardrails'] == success
            assert result['success'][family]['development_statistical_support'] == bool(success and contrast['holm_p'] <= .05)
    receipt = {'passed': True, 'part': part, 'rows': len(rows), 'methods': len(predictions),
               'results_sha256': c.sha(output / part / 'results.json'),
               'independent_parser_metrics_statistics': True, 'holm_planned_comparisons': 23}
    f.immutable(output / part / 'audit.json', receipt)
    return receipt


def report(output, part):
    _, p = verify()
    if part == 'evaluation': recommendation_gate(output)
    rows, predictions, selected = load_records(output, part, p)
    value = summarize(rows, predictions, selected, p)
    value.update(part=part, quick24=True, original_full_plan_complete=False,
                 fixed_new_epoch=3, original_adapter_selection_unchanged=True,
                 scope='Historical development comparison; scope reduced after earlier validation results at user deadline request.',
                 schedule_sha256=c.sha(f.ROOT / MANIFEST),
                 record_hashes={a + '/' + k: r['record_sha256'] for a, rs in predictions.items() for k, r in rs.items()})
    dest = output / part
    f.immutable(dest / 'results.json', value)
    independent_audit(output, part, rows, predictions, selected, value)
    if part == 'validation':
        name, improved = choose(value, p)
        f.immutable(output / 'quick_recommendation.json', {
            'method_family': name, 'new_fusion_selected': improved, 'members': p['families'][name],
            'deployment_seed': 42, 'selection_used_evaluation': False,
            'validation_results_sha256': c.sha(dest / 'results.json'),
            'schedule_sha256': c.sha(f.ROOT / MANIFEST),
            'adapter_receipt_hashes': {a: c.sha(output / 'adapters' / (a + '.json')) for a in NEW}})
    lines = ['# V18 24小时快速比较', '',
             f'分区：{part}，完整{len(rows)}题，{len(predictions)}个配置。不是原62配置完整实验。',
             '新模型固定第3轮，旧LoRA保持原冻结选型；历史开发数据，不作独立泛化声明。', '',
             '| 方法族 | 基础准确率 | 挑战准确率 | 挑战标准差 | 挑战Macro-F1 | 幅度限制 |',
             '|---|---:|---:|---:|---:|---|']
    for name in selected['families']:
        b = value['datasets']['basic']['families'][name]; t = value['datasets']['challenge']['families'][name]
        sd = '—' if t['seed_accuracy_stdev'] is None else f"{t['seed_accuracy_stdev']:.2%}"
        lines.append(f"| {name} | {b['accuracy']:.2%} | {t['accuracy']:.2%} | {sd} | {t['macro_f1']:.4f} | {value['guardrails'][name]['passed']} |")
    lines += ['', '三个种子分别保存在results.json；不当作三倍独立题目。分组配对检验保留23项Holm范围，未评估项p=1。',
              '逐类别、机制、无效、修正/损害和统计详见results.json；题目与金标未改。',
              'AI辅助解释审核、PRESUP训练缺失、原标签歧义、历史暴露和V16封存偏差继续披露。',
              '新增复核、逐轮选优、其余261题配置延期；已经完成的提示/复核结果仅在验证表保留。']
    (dest / 'RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    stream = io.StringIO(newline=''); writer = csv.DictWriter(stream, fieldnames=['dataset', 'id', 'group', 'mechanism', 'gold', *predictions])
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row[k] for k in ('dataset', 'id', 'group', 'mechanism')} | {'gold': row['label']} |
                        {a: rs[c.record_key(row)]['prediction'] for a, rs in predictions.items()})
    (dest / 'predictions.csv').write_text(stream.getvalue(), encoding='utf-8')
    if part == 'evaluation':
        rec = recommendation_gate(output)
        f.immutable(dest / 'recommended_method.json', {
            'validation_choice': rec, 'development_comparison_passed': value['success'].get(rec['method_family']),
            'recipe': {a: p['direct'][a] for a in rec['members']},
            'adapters': {a: c.read_json(output / 'adapters' / (a + '.json')) for a in NEW},
            'old_adapters': p['old_adapters'], 'prompt': c.read_json(f.ROOT / f.EXP / 'prompts.json')['a0'],
            'generation': p['generation'], 'model': 'Qwen/Qwen3.8-27B', 'precision': 'BF16'})
    return value


def coverage(output):
    _, p = verify()
    result = {}
    for part in ('validation', 'evaluation'):
        n = len(f.data(part)); proto = catalog(p, part)
        result[part] = {a: {'received': len(list((output / part / kind / a).glob('*.json'))), 'expected': n}
                       for kind in ('direct', 'fusion') for a in proto[kind]}
    return result


def finish(output, status):
    """Always produce coverage and costs, including a deadline/failed partial run."""
    value = {'status': status, 'quick_scope_complete': status == 'complete',
             'original_full_plan_complete': False, 'coverage': coverage(output),
             'schedule_sha256': c.sha(f.ROOT / MANIFEST), 'time_unix': time.time(),
             'partial_methods_not_scored_as_complete': True,
             'deferred': ['epoch_1_2_checkpoint_validation', 'new_distillation_review_routes',
                          'remaining_49_evaluation_configurations']}
    c.save(output / 'completion.json', value)
    c.save(output / 'costs.json', physical_cost(output))
    if status != 'complete':
        # Score only methods with the complete predetermined question set.
        partial = {}
        for part, arms in value['coverage'].items():
            rows = f.data(part); predictions = {}
            for arm, count in arms.items():
                if count['received'] != count['expected']: continue
                kind = 'direct' if (output / part / 'direct' / arm).exists() else 'fusion'
                records = {}
                for row in rows:
                    key = c.record_key(row)
                    record = f.check_record(c.read_json(output / part / kind / arm / (key + '.json')))
                    if (record['dataset'], record['id']) != (row['dataset'], row['id']):
                        raise ValueError('Partial report row mismatch')
                    records[key] = record
                predictions[arm] = records
            scores = {}
            for dataset in ('basic', 'challenge'):
                selected = [r for r in rows if r['dataset'] == dataset]
                scores[dataset] = {a: full.compute_metrics(c.metric_rows(selected,
                    {c.record_key(r): rs[c.record_key(r)] for r in selected})) for a, rs in predictions.items()}
            priority.independent_check(rows, predictions, scores)
            partial[part] = {'scores': scores, 'complete_methods': list(predictions),
                             'independent_parser_metrics': True, 'no_family_inference_or_new_recommendation': True}
        c.save(output / 'partial_results.json', partial)
    lines = ['# V18快速比较运行回执', '', f'状态：{status}。原完整版未完成。',
             '完整结果见validation/和evaluation/；未完成方法不以部分题目准确率纳入主比较。', '',
             '| 分区 | 方法 | 已收到/预期 |', '|---|---|---:|']
    for part, arms in value['coverage'].items():
        for arm, count in arms.items(): lines.append(f"| {part} | {arm} | {count['received']}/{count['expected']} |")
    (output / 'STATUS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['worker', 'report'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--old-output', type=Path, default=Path('/root/ab_finetune27b_20261030/fusion_v18_runs'))
    parser.add_argument('--part', choices=['validation', 'evaluation'], required=True)
    parser.add_argument('--arm', default='all')
    parser.add_argument('--worker', type=int, choices=(0, 1), default=0)
    parser.add_argument('--smoke-count', type=int, choices=(0, 3), default=0)
    parser.add_argument('--model', type=Path, default=Path('/root/ab_finetune27b_20261030/models/Qwen3.8-27B'))
    parser.add_argument('--formal', type=Path, default=Path('/root/ab_finetune27b_20261030/revision_2_runs/formal'))
    args = parser.parse_args()
    if args.action == 'worker': worker(args)
    else: report(args.output, args.part)


if __name__ == '__main__':
    main()
