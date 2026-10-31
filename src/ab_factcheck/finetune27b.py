"""Frozen, group-isolated 27B baseline-prompt fine-tuning experiment (stdlib core)."""
from collections import Counter, defaultdict
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

LABELS = ('SUPPORTS', 'REFUTES', 'NOT ENOUGH INFO')
EXPERIMENT = Path('experiments/016_finetune_27b')
ROOT = Path(__file__).resolve().parents[2]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(path)


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def prompts(root=ROOT):
    return {role: (root / f'prompts/v1/A0_{role}.txt').read_text(encoding='utf-8').strip()
            for role in ('system', 'user')}


def messages(row, prompt):
    # Never serialize metadata or gold into the model input.
    return [{'role': 'system', 'content': prompt['system']},
            {'role': 'user', 'content': prompt['user'].format(evidence=row['evidence'], claim=row['claim'])}]


def target_text(row):
    if row['label'] not in LABELS:
        raise ValueError('Unknown gold label')
    return 'Verdict: ' + row['label']


def parse_verdict(text, finished=True):
    if not finished or not isinstance(text, str) or '<think>' in text:
        return 'INVALID'
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 'INVALID'
    match = re.fullmatch(r'Verdict: (SUPPORTS|REFUTES|NOT ENOUGH INFO)', lines[-1])
    return match.group(1) if match else 'INVALID'


def split_dev(rows, seed=2026103016):
    """Choose groups solely from metadata; optimize label/count balance, never scores."""
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate IDs')
    groups = defaultdict(list)
    for row in rows:
        if row['label'] not in LABELS:
            raise ValueError('Invalid label')
        groups[row['group']].append(row)
    strata = defaultdict(list)
    for group, members in groups.items():
        mechanisms = {r['mechanism'] for r in members}
        if len(mechanisms) != 1:
            raise ValueError('Group crosses mechanisms')
        strata[next(iter(mechanisms))].append(group)
    total = Counter(r['label'] for r in rows)
    candidates = []
    for candidate in range(128):
        chosen = set()
        for mechanism, keys in sorted(strata.items()):
            count = max(1, min(len(keys) - 1, int(len(keys) * .2 + .5)))
            if len(keys) < 2:
                raise ValueError('Need at least two groups per mechanism')
            chosen.update(sorted(keys, key=lambda g: digest([seed, candidate, mechanism, g]))[:count])
        val = [r for r in rows if r['group'] in chosen]
        counts = Counter(r['label'] for r in val)
        error = (len(val) / len(rows) - .2) ** 2
        error += sum((counts[label] / total[label] - .2) ** 2 for label in LABELS if total[label])
        candidates.append((error, candidate, chosen))
    _, _, chosen = min(candidates, key=lambda x: (x[0], x[1]))
    return {part: sorted([r for r in rows if (r['group'] in chosen) == (part == 'validation')],
                         key=lambda r: r['id']) for part in ('train', 'validation')}


def describe(rows):
    return {d: {'rows': len(a), 'groups': len({r['group'] for r in a}),
                'labels': dict(Counter(r['label'] for r in a)),
                'mechanisms': dict(Counter(r['mechanism'] for r in a))}
            for d in ('basic', 'challenge') if (a := [r for r in rows if r['dataset'] == d])}


def prepare(root=ROOT):
    exp = root / EXPERIMENT
    if (exp / 'freeze.json').exists():
        return verify(root)
    exp.mkdir(parents=True, exist_ok=True)
    partitions = {'train': [], 'validation': []}
    source_hashes = {}
    for dataset in ('basic', 'challenge'):
        source = root / f'data/splits/v1/{dataset}/dev.jsonl'
        source_hashes[str(source.relative_to(root)).replace('\\', '/')] = file_hash(source)
        rows = [dict(r, dataset=dataset) for r in read_rows(source)]
        for part, members in split_dev(rows).items():
            partitions[part].extend(members)
    for part, members in partitions.items():
        path = exp / (part + '.jsonl')
        path.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in members), encoding='utf-8')
    protocol = {
        'experiment': '016_finetune_27b_baseline', 'model_id': 'Qwen/Qwen3.8-27B',
        'hypothesis': 'LoRA changes accuracy with the same 27B BF16 weights, A0 prompts and inference code.',
        'prompt': prompts(root), 'prompt_source': ['prompts/v1/A0_system.txt', 'prompts/v1/A0_user.txt'],
        'input_fields': ['evidence', 'claim'], 'label_only_target': 'Verdict: <gold label>',
        'rationale_policy': 'No invented or teacher-generated rationale. Supervise only verdict continuation and EOS; original A0 instruction remains unchanged in both arms.',
        'precision': 'bfloat16', 'quantization': None,
        'backend': 'transformers eager attention + torch reference gated-delta kernels, identical arms',
        'training': {'seed': 42, 'epochs': 3, 'learning_rate': 1e-4, 'weight_decay': 0.0,
                     'micro_batch_size': 1, 'gradient_accumulation_steps': 16, 'max_grad_norm': 1.0,
                     'max_sequence_length': 1536, 'truncate': False, 'gradient_checkpointing': True,
                     'lora_rank': 8, 'lora_alpha': 16, 'lora_dropout': 0.05,
                     'target_modules': ['q_proj', 'k_proj', 'v_proj', 'o_proj', 'in_proj_qkv', 'out_proj'],
                     'optimizer': 'AdamW', 'scheduler': 'constant', 'external_data': False,
                     'class_reweighting': False, 'data_augmentation': False},
        'selection': 'Lowest validation verdict-continuation NLL averaged equally over basic and challenge, after epochs 1/2/3; ties choose earliest. No test reads before selection.',
        'generation': {'do_sample': False, 'max_new_tokens': 1024, 'enable_thinking': False,
                       'batch_size': 1, 'use_cache': True},
        'final_evaluation': 'Paired baseline/adapter on existing v1 test only after checkpoint selection; strict last-line parser, failures count wrong; alternate arm order per ID.',
        'test_exposure': 'Not a pristine project-wide blind test: PJ historical optimization used full benchmark. Test is excluded from this training and checkpoint selection.',
        'primary': {'dataset': 'challenge', 'metric': 'accuracy_delta', 'minimum_gain': .05,
                    'group_sign_permutation': 'exact two-sided dynamic-programming distribution', 'alpha': .05},
        'guardrails': {'basic_accuracy_delta_min': -.02, 'each_class_recall_delta_min': -.05,
                      'interpretation': 'Point-estimate safeguards, not statistical noninferiority.'},
        'seed_scope': 'One predeclared training seed; no claim of training-seed robustness.',
        'source_hashes': source_hashes, 'summary': {k: describe(v) for k, v in partitions.items()},
    }
    save_json(exp / 'protocol.json', protocol)
    paths = [exp / name for name in ['protocol.json', 'train.jsonl', 'validation.jsonl', 'model_source.json']]
    paths += [root / name for name in protocol['prompt_source']]
    save_json(exp / 'freeze.json', {'files': {str(p.relative_to(root)).replace('\\', '/'): file_hash(p) for p in paths},
                                   'test_content_read': False})
    return verify(root)


def verify(root=ROOT):
    exp = root / EXPERIMENT
    freeze = json.loads((exp / 'freeze.json').read_text(encoding='utf-8'))
    for name, expected in freeze['files'].items():
        if file_hash(root / name) != expected:
            raise ValueError('Frozen file changed: ' + name)
    protocol = json.loads((exp / 'protocol.json').read_text(encoding='utf-8'))
    for name, expected in protocol['source_hashes'].items():
        if file_hash(root / name) != expected:
            raise ValueError('Development input changed: ' + name)
    parts = {p: read_rows(exp / (p + '.jsonl')) for p in ('train', 'validation')}
    keys = {p: {(r['dataset'], r['group']) for r in rows} for p, rows in parts.items()}
    if keys['train'] & keys['validation']:
        raise ValueError('Group leakage')
    for dataset in ('basic', 'challenge'):
        original = {r['id']: r for r in read_rows(root / f'data/splits/v1/{dataset}/dev.jsonl')}
        actual = [r for rows in parts.values() for r in rows if r['dataset'] == dataset]
        if len(actual) != len(original) or {r['id'] for r in actual} != set(original):
            raise ValueError('Development partition mismatch')
        for row in actual:
            if {k: v for k, v in row.items() if k != 'dataset'} != original[row['id']]:
                raise ValueError('Source content changed')
    return protocol


def exact_group_test(deltas):
    # DP is exact even for 29+ groups; zeros contribute the same probability twice.
    distribution = {0: 1}
    for delta in deltas:
        next_distribution = defaultdict(int)
        for score, count in distribution.items():
            next_distribution[score + delta] += count
            next_distribution[score - delta] += count
        distribution = dict(next_distribution)
    observed = abs(sum(deltas))
    return sum(n for score, n in distribution.items() if abs(score) >= observed) / (2 ** len(deltas))


def report(records, protocol):
    from .metrics import compute_metrics, paired_comparison
    output = {'datasets': {}, 'test_exposure': protocol['test_exposure']}
    if len({(r['dataset'], r['id']) for r in records}) != len(records):
        raise ValueError('Duplicate paired records')
    for dataset in ('basic', 'challenge'):
        arms = {}
        subset = [r for r in records if r['dataset'] == dataset]
        if not subset:
            raise ValueError('Missing dataset')
        for arm in ('baseline', 'adapter'):
            arms[arm] = [dict(r, gold_label=r['label'], predicted_label=r[arm]['prediction'],
                              parse_status='ok' if r[arm]['prediction'] in LABELS else 'invalid',
                              latency_seconds=r[arm].get('seconds'), usage={}) for r in subset]
        metrics = {a: compute_metrics(rows) for a, rows in arms.items()}
        deltas = defaultdict(int)
        for r in subset:
            deltas[r['group']] += int(r['adapter']['prediction'] == r['label']) - int(r['baseline']['prediction'] == r['label'])
        output['datasets'][dataset] = {'metrics': metrics,
            'paired': paired_comparison(arms['baseline'], arms['adapter']),
            'group_deltas': dict(deltas), 'two_sided_group_p': exact_group_test(list(deltas.values()))}
    b, c = output['datasets']['basic'], output['datasets']['challenge']
    guardrails = b['paired']['accuracy_delta'] >= protocol['guardrails']['basic_accuracy_delta_min'] - 1e-12
    for data in output['datasets'].values():
        for label in LABELS:
            a = data['metrics']['adapter']['classes'][label]['recall']
            z = data['metrics']['baseline']['classes'][label]['recall']
            if a is None or z is None:
                guardrails = False
            else:
                guardrails &= a - z >= protocol['guardrails']['each_class_recall_delta_min'] - 1e-12
    output['primary_pass'] = bool(c['paired']['accuracy_delta'] >= protocol['primary']['minimum_gain'] - 1e-12
                                  and c['two_sided_group_p'] <= protocol['primary']['alpha'] and guardrails)
    output['guardrails_pass'] = bool(guardrails)
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['prepare', 'verify'])
    p.add_argument('--root', type=Path, default=ROOT)
    a = p.parse_args()
    result = prepare(a.root) if a.action == 'prepare' else verify(a.root)
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))
