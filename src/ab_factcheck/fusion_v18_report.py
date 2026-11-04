"""Complete, separately scored development reports and validation-only choice."""
import argparse
from collections import defaultdict
import csv
import io
from pathlib import Path
from statistics import mean, stdev

from . import finetune27b_v2 as c
from . import fusion_v18 as f
from .metrics import compute_metrics


def records(output, part, protocol):
    rows = f.data(part)
    result = {}
    for kind in ('direct', 'fusion'):
        for arm in protocol[kind]:
            result[arm] = {}
            for row in rows:
                key = c.record_key(row)
                record = f.check_record(c.read_json(output / part / kind / arm / (key + '.json')))
                if (record['dataset'], record['id']) != (row['dataset'], row['id']):
                    raise ValueError('Record row mismatch')
                if kind == 'fusion':
                    component_refs = [(Path(part) / 'direct' / a / (key + '.json')).as_posix() for a in protocol[kind][arm]['components']]
                    expected_refs = component_refs + ([(Path(part) / 'review_calls' / arm / (key + '.json')).as_posix()] if record['route'] == 'review' else [])
                    if record['call_refs'] != expected_refs:
                        raise ValueError('Fusion route uses unexpected component calls')
                    deps = [f.check_record(c.read_json(output / ref)) for ref in record['call_refs']]
                    if [v['record_sha256'] for v in deps] != record['call_hashes']:
                        raise ValueError('Fusion dependencies changed')
                    if record['logical_calls'] != len(deps):
                        raise ValueError('Fusion call accounting mismatch')
                    for field in ('input_tokens', 'output_tokens', 'seconds'):
                        if abs(record[field] - sum(v[field] for v in deps)) > 1e-7:
                            raise ValueError('Fusion cost mismatch')
                    expected = f.consensus(deps[:len(protocol[kind][arm]['components'])])
                    if expected:
                        if record['route'] != 'consensus' or record['prediction'] != expected:
                            raise ValueError('Consensus route mismatch')
                    elif record['route'] != 'review' or record['prediction'] != deps[-1]['prediction']:
                        raise ValueError('Review route mismatch')
                    if record['route'] == 'review':
                        prompt = f.review_prompt(row, deps[:-1], part)
                        if deps[-1]['identity']['adapter_sha256'] is not None or deps[-1]['input_sha256'] != c.digest(c.messages(row, prompt)):
                            raise ValueError('Reviewer must be the unadapted model with original evidence and anonymous analyses')
                else:
                    if record['identity']['freeze'] != c.sha(f.ROOT / f.EXP / 'freeze.json'):
                        raise ValueError('Direct record freeze mismatch')
                    prompt = c.read_json(f.ROOT / f.EXP / 'prompts.json')[protocol['direct'][arm]['prompt']]
                    if record['input_sha256'] != c.digest(c.messages(row, prompt)):
                        raise ValueError('Direct record input mismatch')
                    adapter = protocol['direct'][arm]['adapter']
                    expected_adapter = None
                    if adapter and adapter.startswith('old_'):
                        expected_adapter = protocol['old_adapters'][adapter.split('_')[-1]]['adapter_sha256']
                    elif adapter:
                        _, source, seed = adapter.split('_')
                        expected_adapter = c.read_json(output / 'training' / source / f'seed-{seed}/selection.json')['selected']['adapter_sha256']
                    if record['identity']['adapter_sha256'] != expected_adapter:
                        raise ValueError('Direct method has wrong adapter')
                result[arm][key] = record
    return rows, result


def pair(rows, predictions, families, candidate):
    effects = defaultdict(int)
    rescued = harmed = 0.
    for row in rows:
        key = c.record_key(row)
        def score(name):
            arms = families[name]
            return sum(predictions[a][key]['prediction'] == row['label'] for a in arms) * (3 // len(arms))
        base, new = score(f.INCUMBENT), score(candidate)
        effects[row['group']] += new - base
        # Expected correction/harm against seed-matched incumbent where possible.
        arms = families[candidate]
        comparisons = [(a, families[f.INCUMBENT][i]) for i, a in enumerate(arms)] if len(arms) == 3 else [(arms[0], b) for b in families[f.INCUMBENT]]
        rescued += sum(predictions[a][key]['prediction'] == row['label'] and predictions[b][key]['prediction'] != row['label'] for a, b in comparisons) / 3
        harmed += sum(predictions[a][key]['prediction'] != row['label'] and predictions[b][key]['prediction'] == row['label'] for a, b in comparisons) / 3
    return {'method': candidate, 'n': len(rows), 'groups': len(effects), 'group_deltas_scaled_3': dict(effects),
            'accuracy_delta': sum(effects.values()) / (3 * len(rows)), 'p': c.exact_group_test(list(effects.values())),
            'rescued_mean': rescued, 'harmed_mean': harmed}


def holm(pairs):
    previous = 0.
    for i, item in enumerate(sorted(pairs, key=lambda x: x['p'])):
        previous = max(previous, min(1., item['p'] * (len(pairs) - i)))
        item['holm_p'] = previous


def summarize(rows, predictions, protocol):
    datasets = {}
    for dataset in ('basic', 'challenge'):
        selected = [r for r in rows if r['dataset'] == dataset]
        scores = {}
        for arm, rs in predictions.items():
            subset = {c.record_key(r): rs[c.record_key(r)] for r in selected}
            scored = c.metric_rows(selected, subset)
            value = compute_metrics(scored)
            value['mechanisms'] = {m: compute_metrics([r for r in scored if r['mechanism'] == m]) for m in sorted({r['mechanism'] for r in selected})}
            value['mean_calls'] = mean(r['logical_calls'] for r in subset.values())
            value['mean_tokens'] = mean(r['input_tokens'] + r['output_tokens'] for r in subset.values())
            value['input_tokens'] = sum(r['input_tokens'] for r in subset.values())
            value['output_tokens'] = sum(r['output_tokens'] for r in subset.values())
            value['mean_seconds'] = mean(r['seconds'] for r in subset.values())
            value['missing_reason'] = sum(not r['reason_present'] for r in subset.values())
            scores[arm] = value
        families = {}
        for name, arms in protocol['families'].items():
            values = [scores[a] for a in arms]
            families[name] = {k: mean(v[k] for v in values) for k in ('accuracy', 'macro_f1', 'mean_calls', 'mean_tokens', 'mean_seconds')}
            families[name]['seed_accuracy_stdev'] = stdev(v['accuracy'] for v in values) if len(values) > 1 else None
            families[name]['recall'] = {label: mean(v['classes'][label]['recall'] for v in values) for label in c.LABELS}
        pairs = [pair(selected, predictions, protocol['families'], name) for name in protocol['families'] if name != f.INCUMBENT]
        holm(pairs)
        datasets[dataset] = {'n': len(selected), 'scores': scores, 'families': families, 'pairs': pairs}
    constraints = {}
    for name, arms in protocol['families'].items():
        failures = []
        for arm in arms:
            for dataset in ('basic', 'challenge'):
                scores = datasets[dataset]['scores']; base, value = scores['base_a0'], scores[arm]
                if dataset == 'basic' and value['accuracy'] < base['accuracy'] - .02 - 1e-12:
                    failures.append(f'{arm}: basic accuracy decrease >2pp')
                for label in c.LABELS:
                    if value['classes'][label]['recall'] < base['classes'][label]['recall'] - .05 - 1e-12:
                        failures.append(f'{arm}: {dataset}/{label} recall decrease >5pp')
        constraints[name] = {'passed': not failures, 'failures': failures}
    gains = {v['method']: v for v in datasets['challenge']['pairs']}
    return {'datasets': datasets, 'guardrails': constraints, 'success': {
        name: {'point_improvement_and_guardrails': constraints[name]['passed'] and gains[name]['accuracy_delta'] > 0,
               'development_statistical_support': constraints[name]['passed'] and gains[name]['accuracy_delta'] > 0 and gains[name]['holm_p'] <= .05}
        for name in gains}}


def recommend(result, protocol):
    legacy = {'base_a0', 'base_nli', 'base_pj', f.INCUMBENT}
    eligible = [name for name in protocol['families'] if name not in legacy and result['success'][name]['point_improvement_and_guardrails']]
    def key(name):
        b = result['datasets']['basic']['families'][name]
        t = result['datasets']['challenge']['families'][name]
        return (-int(result['guardrails'][name]['passed']), -t['accuracy'], -b['accuracy'], -t['macro_f1'],
                b['mean_calls'] + t['mean_calls'], b['mean_tokens'] + t['mean_tokens'], name)
    return min(eligible or legacy, key=key), bool(eligible)


def report(output, part):
    protocol = f.verify()
    rows, predictions = records(output, part, protocol)
    result = summarize(rows, predictions, protocol)
    result.update(part=part, scope=protocol['scope'], freeze=c.sha(f.ROOT / f.EXP / 'freeze.json'),
                  record_hashes={f'{a}/{k}': r['record_sha256'] for a, records_by_key in predictions.items() for k, r in records_by_key.items()})
    physical = {}
    for kind in ('direct', 'review_calls'):
        for path in (output / part / kind).rglob('*.json'):
            r = f.check_record(c.read_json(path))
            physical[r['physical_call']] = r
    result['physical_cost'] = {'calls': len(physical), 'input_tokens': sum(r['input_tokens'] for r in physical.values()),
                               'output_tokens': sum(r['output_tokens'] for r in physical.values()),
                               'seconds': sum(r['seconds'] for r in physical.values()),
                               'note': 'Deduplicated physical calls; per-method cost includes every component it needs in deployment.'}
    destination = output / part
    f.immutable(destination / 'results.json', result)
    if part == 'validation':
        name, improved = recommend(result, protocol)
        paths = [Path('training') / source / f'seed-{seed}/selection.json' for source in f.SOURCES for seed in f.SEEDS]
        f.immutable(output / 'recommendation.json', {'method_family': name, 'new_fusion_selected': improved,
            'validation_results_sha256': c.sha(destination / 'results.json'), 'freeze': result['freeze'],
            'selection_hashes': {q.as_posix(): c.sha(output / q) for q in paths},
            'deployment_seed': 42, 'selection_used_evaluation': False, 'members': protocol['families'][name]})
    lines = ['# V18 融合开发比较', '', protocol['scope'], '',
        '| 方法族 | 基础准确率 | 挑战准确率 | 挑战 R 召回 | 挑战 NEI 召回 | 幅度限制 |', '|---|---:|---:|---:|---:|---|']
    for name in protocol['families']:
        b = result['datasets']['basic']['families'][name]; t = result['datasets']['challenge']['families'][name]
        lines.append(f"| {name} | {b['accuracy']:.2%} | {t['accuracy']:.2%} | {t['recall']['REFUTES']:.2%} | {t['recall']['NOT ENOUGH INFO']:.2%} | {result['guardrails'][name]['passed']} |")
    lines += ['', '含 LoRA 的方法为三个种子均值；逐种子、标准差、各类与机制指标、修正/损害、23 项 Holm 校正见 results.json。',
              '标签歧义不通过修改主评分或删题处理。PRESUP 训练覆盖缺失、AI 辅助标注、历史暴露及 V16 封存偏差继续披露。',
              '物理调用按实际缓存去重；每种方法的部署成本包含其全部初判和裁决。训练、教师生成、烟测成本另列。',
              '最终推荐由验证集提前冻结，不根据本表重选；本轮结果不证明独立泛化。']
    (destination / 'RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=['dataset', 'id', 'group', 'mechanism', 'gold', *predictions])
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row[k] for k in ('dataset', 'id', 'group', 'mechanism')} | {'gold': row['label']} |
                        {a: rs[c.record_key(row)]['prediction'] for a, rs in predictions.items()})
    (destination / 'predictions.csv').write_text(buffer.getvalue(), encoding='utf-8')
    if part == 'evaluation':
        recommendation = c.read_json(output / 'recommendation.json')
        new_adapters = {}
        for source in f.SOURCES:
            for seed in f.SEEDS:
                selected = c.read_json(output / 'training' / source / f'seed-{seed}/selection.json')['selected']
                new_adapters[f'distill_{source}_{seed}'] = {k: selected[k] for k in ('checkpoint', 'adapter_sha256', 'adapter_config_sha256')}
                new_adapters[f'distill_{source}_{seed}']['relative_directory'] = f"training/{source}/seed-{seed}/{selected['checkpoint']}"
        f.immutable(destination / 'recommended_method.json', {'validation_choice': recommendation,
            'development_comparison_passed': result['success'].get(recommendation['method_family']),
            'recipe': {a: protocol['direct'].get(a, protocol['fusion'].get(a)) for a in recommendation['members']},
            'prompts': c.read_json(f.ROOT / f.EXP / 'prompts.json'), 'generation': protocol['generation'],
            'old_adapters': protocol['old_adapters'], 'new_adapters': new_adapters,
            'method_catalog': {'direct': protocol['direct'], 'fusion': protocol['fusion']},
            'model': 'Qwen/Qwen3.8-27B', 'precision': 'BF16'})
    return result


def costs(output):
    physical, steps, smokes, interrupted = {}, [], [], []
    for path in output.rglob('*.json'):
        value = c.read_json(path)
        if isinstance(value, dict) and 'physical_call' in value:
            previous = physical.setdefault(value['physical_call'], value)
            if previous != value:
                raise ValueError('A physical call has conflicting aliases')
        if 'steps' in path.parts and isinstance(value, dict) and 'grad_norm' in value:
            steps.append(value)
        if path.name == 'receipt.json' and 'smoke' in path.parts and isinstance(value, dict) and 'inference_cost' in value:
            smokes.append(value['inference_cost'])
        if path.name == 'accounting.json' and isinstance(value, list):
            interrupted.extend(value)
    phases = {}
    for record in physical.values():
        phase = record['identity']['phase']
        item = phases.setdefault(phase, {'calls': 0, 'input_tokens': 0, 'output_tokens': 0, 'seconds': 0.})
        item['calls'] += 1
        for field in ('input_tokens', 'output_tokens', 'seconds'):
            item[field] += record[field]
    value = {'physical_by_phase': phases, 'training_updates': len(steps),
             'training_step_seconds': sum(v['seconds'] for v in steps), 'training_smoke_inference': smokes,
             'unanswered_attempts_unknown_cost': sum(v['unanswered_cost_unknown'] for v in interrupted),
             'limits': 'Observed shared-hardware time; checkpoint replay work and failed generations may have unmeasured compute. Not a deployment throughput guarantee.'}
    f.immutable(output / 'costs.json', value)
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('output', type=Path)
    parser.add_argument('--part', choices=['validation', 'evaluation'], required=True)
    args = parser.parse_args(); report(args.output, args.part)
