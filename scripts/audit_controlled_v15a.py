"""Independent Z3 labels and raw-response/CSV/metric reconciliation for V15."""
import argparse
from collections import Counter
import csv
import hashlib
from itertools import product
import json
from pathlib import Path
import sys

import z3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ab_factcheck.common import atomic_json

EXP = ROOT / 'experiments/015_controlled_comparison/amendment_1'
PARENT_EXP = ROOT / 'experiments/015_controlled_comparison'
OUT = ROOT / 'outputs/controlled_v15a'
LABELS = ('SUPPORTS', 'REFUTES', 'NOT ENOUGH INFO')

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

def z3_label(model):
    env = {}
    integers = set(model['integers'])
    def term(node):
        if isinstance(node, str):
            if node not in env: env[node] = z3.Int(node) if node in integers else z3.Bool(node)
            return env[node]
        if isinstance(node, (int, bool)): return node
        op = node[0]
        xs = [term(x) for x in node[1:]]
        if op == 'not': return z3.Not(xs[0])
        if op == 'and': return z3.And(*xs)
        if op == 'or': return z3.Or(*xs)
        if op == 'implies': return z3.Implies(*xs)
        if op == 'eq': return xs[0] == xs[1]
        if op == 'ge': return xs[0] >= xs[1]
        if op == 'le': return xs[0] <= xs[1]
        if op == 'lt': return xs[0] < xs[1]
        raise AssertionError(op)
    premise, claim = term(model['premise']), term(model['claim'])
    solver = z3.Solver()
    solver.add(premise, *[env[k] >= 0 for k in integers])
    assert solver.check() == z3.sat, 'Unsatisfiable evidence'
    possible = []
    for expr in (claim, z3.Not(claim)):
        solver.push()
        solver.add(expr)
        result = solver.check()
        assert result != z3.unknown
        possible.append(result == z3.sat)
        solver.pop()
    return {(True, False): 'SUPPORTS', (False, True): 'REFUTES', (True, True): 'NOT ENOUGH INFO'}[tuple(possible)]

def run(with_results=False):
    freeze = json.loads((EXP / 'freeze.json').read_text(encoding='utf-8'))
    for path, expected in freeze['files'].items(): assert sha(ROOT / path) == expected, path
    gold = [json.loads(s) for s in (EXP / 'gold.jsonl').read_text().splitlines()]
    inputs = [json.loads(s) for s in (EXP / 'inputs.jsonl').read_text().splitlines()]
    by_id = {r['id']: r for r in gold}
    assert len(gold) == len(by_id) == len(inputs) == 336
    assert {(r['evidence'], r['claim']) for r in gold}.__len__() == 336
    for item in inputs:
        assert set(item) == {'id', 'dataset', 'claim', 'evidence'}
        assert all(item[k] == by_id[item['id']][k] for k in item)
    for row in gold:
        assert z3_label(row['semantics']) == row['label'], row['id']
    for dataset in ('basic', 'challenge'):
        rows = [r for r in gold if r['dataset'] == dataset]
        assert len(rows) == 168
        assert Counter(r['label'] for r in rows) == Counter({k: 56 for k in LABELS})
        assert len({r['group'] for r in rows}) == 56
        assert len({r['template_family'] for r in rows}) == 14
        assert len({r['mechanism'] for r in rows}) == 7
        for group in {r['group'] for r in rows}:
            assert sorted(r['label'] for r in rows if r['group'] == group) == sorted(LABELS)
    schedule = json.loads((EXP / 'schedule.json').read_text())
    assert Counter((r['id'], r['arm']) for r in schedule) == Counter((r['id'], a) for r in gold for a in ('nli', 'pj_v3'))
    audit = {'passed': True, 'rows': 336, 'z3_all_labels_agree': True, 'input_boundary_checked': True,
             'freeze_sha256': digest(freeze), 'natural_language_independently_adjudicated': False,
             'source_audit': 'All formal models checked; English/formula alignment authored and reviewable, not independently established by Z3.'}
    atomic_json(EXP / 'data_audit.json', audit)
    if not with_results:
        print(json.dumps(audit))
        return
    results = json.loads((EXP / 'metrics.json').read_text())
    with (EXP / 'predictions.csv').open(newline='', encoding='utf-8') as source:
        predictions = list(csv.DictReader(source))
    assert len(predictions) == len({r['id'] for r in predictions}) == 336
    prediction_map = {r['id']: r for r in predictions}
    token_counts = {a: Counter() for a in ('nli', 'pj_v3')}
    for item in schedule:
        arm, row = item['arm'], by_id[item['id']]
        inventory = json.loads((EXP / 'reuse_inventory.json').read_text(encoding='utf-8'))
        reused = inventory.get(row['id'] + '/' + arm)
        path = ROOT / reused['path'] if reused else OUT / 'records' / row['dataset'] / row['id'] / (arm + '.json')
        if reused: assert sha(path) == reused['sha256']
        record = json.loads(path.read_text(encoding='utf-8'))
        assert record['record_sha256'] == digest({k: v for k, v in record.items() if k != 'record_sha256'})
        assert record['freeze_sha256'] == (digest(json.loads((PARENT_EXP / 'freeze.json').read_text(encoding='utf-8'))) if reused else digest(freeze))
        assert results['response_hashes'][str(path.relative_to(ROOT)).replace('\\', '/')] == sha(path)
        payload = record['request_payload']
        assert payload['model'] == record['actual_model_id'] == 'qwen38-27b'
        assert payload['temperature'] == 0 and payload['seed'] == 42 and payload['max_tokens'] == 1024
        assert payload['chat_template_kwargs'] == {'enable_thinking': False}
        assert payload['messages'] == [{'role': 'system', 'content': (EXP / 'prompts' / (arm + '.txt')).read_text(encoding='utf-8')},
                                       {'role': 'user', 'content': 'EVIDENCE:\n' + row['evidence'] + '\n\nCLAIM:\n' + row['claim']}]
        assert record['nonthinking_validation']['passed'] and not record['provider_validation_issues']
        predicted = 'INVALID'
        if record['finish_reason'] == 'stop':
            try:
                obj = json.loads(record['raw_response'])
                if isinstance(obj, dict) and set(obj) == {'justification', 'verdict'} and isinstance(obj['justification'], str) and obj['verdict'] in LABELS:
                    predicted = obj['verdict']
            except (TypeError, ValueError): pass
        assert prediction_map[row['id']][arm] == predicted
        assert prediction_map[row['id']]['label'] == row['label']
        for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'): token_counts[arm][k] += record['usage'][k]
    for arm, counts in token_counts.items():
        assert all(results['costs'][arm][k] == v for k, v in counts.items())
        assert results['costs'][arm]['calls'] == 336
    for dataset in ('basic', 'challenge'):
        selected = [r for r in predictions if r['dataset'] == dataset]
        for arm in ('nli', 'pj_v3'):
            saved = results['datasets'][dataset]['methods'][arm]
            correct = sum(r[arm] == r['label'] for r in selected)
            assert saved['correct'] == correct and saved['accuracy'] == correct / 168
            independent = Counter((r['label'], r[arm]) for r in selected)
            for label in LABELS:
                for pred in (*LABELS, 'INVALID'):
                    assert saved['confusion_matrix'][label][pred] == independent[label, pred]
                assert saved['classes'][label]['recall'] == independent[label, label] / 56
            for mechanism in {r['mechanism'] for r in selected}:
                subgroup = [r for r in selected if r['mechanism'] == mechanism]
                assert results['datasets'][dataset]['mechanisms'][mechanism][arm]['correct'] == sum(r[arm] == r['label'] for r in subgroup)
        deltas = []
        for family in sorted({r['template_family'] for r in selected}):
            rs = [r for r in selected if r['template_family'] == family]
            deltas.append(sum(int(r['pj_v3'] == r['label']) - int(r['nli'] == r['label']) for r in rs))
        observed = abs(sum(deltas))
        p = sum(abs(sum(v * s for v, s in zip(deltas, signs))) >= observed for signs in product((-1, 1), repeat=len(deltas))) / 2 ** len(deltas)
        assert p == results['datasets'][dataset]['paired']['two_sided_template_permutation_p']
    audit.update(raw_responses=672, raw_predictions_and_metrics_agree=True,
                 token_totals_agree=True, independent_exhaustive_permutation_agrees=True,
                 metrics_sha256=sha(EXP / 'metrics.json'), predictions_sha256=sha(EXP / 'predictions.csv'))
    atomic_json(EXP / 'audit.json', audit)
    print(json.dumps(audit))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', action='store_true')
    run(parser.parse_args().results)
