"""Independent label/count/F1/permutation audit; no original benchmark access."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
LABELS = ('SUPPORTS', 'REFUTES', 'NOT ENOUGH INFO')


def parse(record):
    if not record['finished'] or record.get('thinking_generated') or re.search(r'</?think\b', record.get('raw_text', '') + record['text'], re.I):
        return 'INVALID'
    lines = [v.strip() for v in record['text'].splitlines() if v.strip()]
    m = re.fullmatch(r'Verdict: (SUPPORTS|REFUTES|NOT ENOUGH INFO)', lines[-1]) if lines else None
    return m.group(1) if m else 'INVALID'


def group_p(effects):
    counts = Counter({0: 1})
    for effect in effects:
        next_counts = Counter()
        for value, count in counts.items():
            next_counts[value + effect] += count
            next_counts[value - effect] += count
        counts = next_counts
    return sum(count for value, count in counts.items() if abs(value) >= abs(sum(effects))) / (2 ** len(effects))


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(output, part, root=ROOT):
    exp = root / 'experiments/018_fusion'
    protocol = read(exp / 'protocol.json')
    rows = [json.loads(v) for v in (exp / f'{part}.jsonl').read_text(encoding='utf-8').splitlines()]
    result = read(output / part / 'results.json')
    predictions = {}
    record_hashes = {}
    for kind in ('direct', 'fusion'):
        for arm in protocol[kind]:
            predictions[arm] = {}
            for row in rows:
                key = row['dataset'] + '_' + row['id']
                record = read(output / part / kind / arm / (key + '.json'))
                checksum = hashlib.sha256(json.dumps({k: v for k, v in record.items() if k != 'record_sha256'},
                    sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
                assert checksum == record['record_sha256']
                assert (record['dataset'], record['id']) == (row['dataset'], row['id'])
                assert parse(record) == record['prediction']
                record_hashes[arm + '/' + key] = checksum
                predictions[arm][key] = parse(record)
    assert record_hashes == result['record_hashes']
    for dataset in ('basic', 'challenge'):
        selected = [r for r in rows if r['dataset'] == dataset]
        for arm in predictions:
            cells = Counter((r['label'], predictions[arm][dataset + '_' + r['id']]) for r in selected)
            metric = result['datasets'][dataset]['scores'][arm]
            assert metric['n'] == len(selected)
            assert metric['correct'] == sum(cells[label, label] for label in LABELS)
            assert metric['invalid'] == sum(cells[label, 'INVALID'] for label in LABELS)
            assert abs(metric['accuracy'] - metric['correct'] / len(selected)) < 1e-12
            f1s = []
            for label in LABELS:
                tp = cells[label, label]
                support = sum(v for (gold, _), v in cells.items() if gold == label)
                predicted = sum(v for (_, pred), v in cells.items() if pred == label)
                recall = tp / support if support else None
                f1s.append(2 * tp / (support + predicted) if support + predicted else 0.)
                assert metric['classes'][label]['recall'] == recall
                for pred in (*LABELS, 'INVALID'):
                    assert metric['confusion_matrix'][label][pred] == cells[label, pred]
            assert abs(metric['macro_f1'] - sum(f1s) / 3) < 1e-12
        pairs = result['datasets'][dataset]['pairs']
        assert len(pairs) == len(protocol['families']) - 1
        for pair in pairs:
            effects = defaultdict(int)
            for row in selected:
                key = dataset + '_' + row['id']
                for family, sign in ((pair['method'], 1), ('old_a0', -1)):
                    members = protocol['families'][family]
                    effects[row['group']] += sign * (3 // len(members)) * sum(predictions[m][key] == row['label'] for m in members)
            assert dict(effects) == pair['group_deltas_scaled_3']
            assert group_p(list(effects.values())) == pair['p']
        adjusted = 0.
        for index, item in enumerate(sorted(pairs, key=lambda v: v['p'])):
            adjusted = max(adjusted, min(1., item['p'] * (len(pairs) - index)))
            assert abs(adjusted - item['holm_p']) < 1e-12
        for name, members in protocol['families'].items():
            metrics = [result['datasets'][dataset]['scores'][a] for a in members]
            summary = result['datasets'][dataset]['families'][name]
            assert abs(summary['accuracy'] - sum(v['accuracy'] for v in metrics) / len(metrics)) < 1e-12
            assert abs(summary['macro_f1'] - sum(v['macro_f1'] for v in metrics) / len(metrics)) < 1e-12
    gains = {v['method']: v for v in result['datasets']['challenge']['pairs']}
    for name, members in protocol['families'].items():
        passed = True
        for arm in members:
            for dataset in ('basic', 'challenge'):
                scores = result['datasets'][dataset]['scores']; base, new = scores['base_a0'], scores[arm]
                if dataset == 'basic':
                    passed &= new['accuracy'] >= base['accuracy'] - .02 - 1e-12
                for label in LABELS:
                    passed &= new['classes'][label]['recall'] >= base['classes'][label]['recall'] - .05 - 1e-12
        assert bool(passed) == result['guardrails'][name]['passed']
        if name in gains:
            point = bool(passed and gains[name]['accuracy_delta'] > 0)
            assert point == result['success'][name]['point_improvement_and_guardrails']
            assert bool(point and gains[name]['holm_p'] <= .05) == result['success'][name]['development_statistical_support']
    receipt = {'passed': True, 'part': part, 'rows': len(rows), 'scored_cells': len(rows) * len(predictions),
               'results_sha256': sha(output / part / 'results.json'), 'independent_parser_metrics_statistics': True}
    target = output / part / 'audit.json'
    if target.exists():
        assert read(target) == receipt
    else:
        target.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('output', type=Path)
    parser.add_argument('--part', choices=['validation', 'evaluation'], required=True)
    args = parser.parse_args(); audit(args.output, args.part)
