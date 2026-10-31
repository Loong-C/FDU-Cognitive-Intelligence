"""Read-only audit of all three completed validation selections.

Uses received validation answers, never generates responses or reads original
test files. Run through remote_finetune.py after all selections are present.
"""
from collections import Counter
import json
from pathlib import Path
from statistics import mean
import sys

base = Path('/root/ab_finetune27b_20261030')
sys.path.insert(0, str(base/'revision_2_formal_workspace/src'))
from ab_factcheck import finetune27b_v2 as c
from ab_factcheck.finetune27b_training_v2 import identity


def scores(rows, predictions):
    gold = [r['label'] for r in rows]
    pred = [predictions[c.record_key(r)]['prediction'] for r in rows]
    recall, f1 = {}, []
    for label in c.LABELS:
        positives = gold.count(label)
        true_positive = sum(a == b == label for a, b in zip(gold, pred))
        recall[label] = true_positive/positives if positives else None
        if positives:
            f1.append(2*true_positive/(positives+pred.count(label)))
    return {'accuracy': sum(a == b for a, b in zip(gold, pred))/len(rows),
            'macro_f1': mean(f1), 'recall': recall}


def received(directory, expected, rows, baseline=None):
    if c.read_json(directory/'identity.json') != expected:
        raise ValueError('Validation identity mismatch')
    keys = {c.record_key(r) for r in rows}
    if {f.stem for f in directory.glob('*_e_*.json')} != keys:
        raise ValueError('Validation answer coverage differs from frozen IDs')
    answers = {}
    for row in rows:
        key = c.record_key(row)
        answer = c.read_json(directory/(key+'.json'))
        raw = answer.get('raw_text', '').lower()
        thinking = '<think' in raw or '</think' in raw
        parsed = 'INVALID' if thinking else c.parse(answer['text'], answer['finished'])
        if (answer['identity'] != c.digest(expected)
                or answer['input_sha256'] != c.digest(c.messages(row, protocol['prompt']))
                or answer['prediction'] != parsed
                or thinking != answer.get('thinking_generated', False)):
            raise ValueError('Received validation answer failed its identity/parse check')
        if baseline and answer.get('input_token_sha256') != baseline[key].get('input_token_sha256'):
            raise ValueError('Paired validation input tokens differ')
        answers[key] = answer
    return answers


run = base/'revision_2_runs/formal'
if not all((run/f'seed-{seed}/selection.json').exists() for seed in c.SEEDS):
    print(json.dumps({'ready': False, 'reason': 'All three selections are required'}))
    raise SystemExit(0)
protocol = c.verify_training()
environment = c.read_json(run/'smoke/receipt.json')['environment']
common = {'training_freeze_sha256': c.sha(c.ROOT/c.EXP/'training_freeze.json'),
          'environment': environment, 'generation': protocol['generation'], 'phase': 'validation'}
data = c.rows(c.ROOT/c.EXP/'validation.jsonl')
baseline = received(run/'validation/baseline', common, data)
results, configs = [], []
for seed in c.SEEDS:
    directory = run/f'seed-{seed}'
    selected = c.read_json(directory/'selection.json')
    if selected['identity'] != identity(protocol, environment, seed) or selected['holdout_used_for_selection']:
        raise ValueError('Selection provenance mismatch')
    if [v['epoch'] for v in selected['candidates']] != [1, 2, 3]:
        raise ValueError('All three epochs must be compared exactly once')
    ranked, statuses = [], Counter()
    for candidate in selected['candidates']:
        epoch = candidate['epoch']
        checkpoint = directory/candidate['checkpoint']
        if (c.sha(checkpoint/'adapter_model.safetensors') != candidate['adapter_sha256']
                or c.sha(checkpoint/'adapter_config.json') != candidate['adapter_config_sha256']):
            raise ValueError('Candidate adapter or configuration changed')
        config = c.read_json(checkpoint/'adapter_config.json')
        config['target_modules'] = sorted(config['target_modules'])
        configs.append(config)
        expected = {**common, 'seed': seed, 'epoch': epoch, 'adapter_sha256': candidate['adapter_sha256']}
        answers = received(run/f'validation/seed-{seed}/epoch-{epoch}', expected, data, baseline)
        statuses.update(answer['status'] for answer in answers.values())
        metrics, guards = {}, []
        for dataset in ('basic', 'challenge'):
            subset = [r for r in data if r['dataset'] == dataset]
            left, right = scores(subset, baseline), scores(subset, answers)
            saved = candidate['metrics']['datasets'][dataset]
            for arm, computed in (('baseline', left), ('adapter', right)):
                for metric in ('accuracy', 'macro_f1'):
                    if abs(computed[metric]-saved[arm][metric]) > 1e-12:
                        raise ValueError('Independent validation score disagrees')
                if computed['recall'] != {k: v['recall'] for k, v in saved[arm]['classes'].items()}:
                    raise ValueError('Independent validation recall disagrees')
            if dataset == 'basic':
                guards.append(right['accuracy']-left['accuracy'] >= protocol['guardrails']['basic_accuracy_delta_min']-1e-12)
            guards.extend(left['recall'][label] is not None and right['recall'][label] is not None
                          and right['recall'][label]-left['recall'][label] >= protocol['guardrails']['each_class_recall_delta_min']-1e-12
                          for label in c.LABELS)
            metrics[dataset] = right
        passed = all(guards)
        if passed != candidate['metrics']['guardrails_pass']:
            raise ValueError('Validation guardrail decision differs')
        key = (passed, metrics['challenge']['accuracy'], metrics['basic']['accuracy'],
               metrics['challenge']['macro_f1'], -epoch)
        ranked.append((key, candidate))
    if max(ranked, key=lambda v: v[0])[1] != selected['selected']:
        raise ValueError('Selected checkpoint differs from the preregistered ordering')
    results.append({'seed': seed, 'selected_epoch': selected['selected']['epoch'],
                    'validation_guardrails_pass': selected['selected']['metrics']['guardrails_pass'],
                    'answers_verified': len(data)*3, 'statuses': dict(statuses),
                    'selection_sha256': c.sha(directory/'selection.json')})
if any(value != configs[0] for value in configs):
    raise ValueError('LoRA configuration differs between seeds or epochs')
receipt = {'passed': True, 'seeds': results, 'baseline_answers_verified': len(data),
           'independent_accuracy_f1_recall_and_ranking': True,
           'paired_input_hashes_equal': True, 'lora_configs_semantically_equal': True,
           'target_module_order_ignored_for_semantic_comparison': True,
           'received_answers_modified_or_retried': False}
c.save(run/'selection_integrity.json', receipt)
print(json.dumps(receipt))
