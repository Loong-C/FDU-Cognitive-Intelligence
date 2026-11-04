"""Post-run checks of F1, metadata, costs and protocol decisions, without model calls."""
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / 'experiments/015_controlled_comparison/amendment_1'
LABELS = ('SUPPORTS', 'REFUTES', 'NOT ENOUGH INFO')

def main():
    metrics = json.loads((EXP / 'metrics.json').read_text(encoding='utf-8'))
    gold = {r['id']: r for r in map(json.loads, (EXP / 'gold.jsonl').read_text(encoding='utf-8').splitlines())}
    with (EXP / 'predictions.csv').open(encoding='utf-8', newline='') as source:
        rows = list(csv.DictReader(source))
    for r in rows:
        assert all(r[k] == gold[r['id']][k] for k in ('dataset', 'group', 'template_family', 'mechanism', 'label'))
    for dataset in ('basic', 'challenge'):
        selected = [r for r in rows if r['dataset'] == dataset]
        for arm in ('nli', 'pj_v3'):
            fs = []
            saved = metrics['datasets'][dataset]['methods'][arm]
            for label in LABELS:
                tp = sum(r['label'] == label and r[arm] == label for r in selected)
                fp = sum(r['label'] != label and r[arm] == label for r in selected)
                fn = sum(r['label'] == label and r[arm] != label for r in selected)
                precision = tp / (tp + fp) if tp + fp else 0
                f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0
                assert abs(precision - saved['classes'][label]['precision']) < 1e-12
                assert abs(f1 - saved['classes'][label]['f1']) < 1e-12
                fs.append(f1)
            assert abs(sum(fs) / 3 - saved['macro_f1']) < 1e-12
    observed = Counter()
    fingerprints = Counter()
    for folder in ('outputs/controlled_v15', 'outputs/controlled_v15a', 'outputs/controlled_v15a_setup/responses'):
        base = ROOT / folder
        paths = list((base / 'records').glob('*/*/*.json')) + list((base / 'preflight').glob('*.json'))
        for path in paths:
            if path.name not in ('nli.json', 'pj_v3.json'): continue
            record = json.loads(path.read_text(encoding='utf-8'))
            observed['calls'] += 1
            for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'): observed[k] += record['usage'][k]
            fingerprints[str(record['system_fingerprint'])] += 1
    assert observed['calls'] == metrics['operational_costs']['received_calls_including_replaced_and_preflight'] == 732
    assert all(observed[k] == metrics['operational_costs'][k] for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
    assert len(metrics['response_hashes']) == 672
    assert len(json.loads((EXP / 'reuse_inventory.json').read_text())) == 282
    assert metrics['pj_primary_passed'] is False and metrics['basic_point_guardrail_passed'] is True
    paired = metrics['datasets']['challenge']['paired']
    assert paired['accuracy_delta'] < .05 and paired['two_sided_template_permutation_p'] > .05
    result = {'passed': True, 'metadata_and_all_class_precision_f1_checked': True,
              'operational_costs_reconciled': dict(observed), 'fingerprints': dict(fingerprints),
              'formal_response_count': 672, 'reused': 282, 'new_formal': 390,
              'archived_replaced_responses': 54, 'preflight_responses': 6,
              'interrupted_unreceived_usage': '4 requests; unknown, not zero',
              'source_tests': {'command': '.venv/Scripts/python.exe -m pytest -q', 'passed': 250},
              'pj_to_nli_evaluated_token_ratio': metrics['costs']['pj_v3']['total_tokens'] / metrics['costs']['nli']['total_tokens'],
              'note': 'No raw answers regenerated. This validates calculations, not independent natural-language adjudication or natural-text generalization.'}
    (EXP / 'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))

if __name__ == '__main__': main()
