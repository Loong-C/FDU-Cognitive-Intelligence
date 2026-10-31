"""Revision 2: development-only, reviewed-rationale, three-seed experiment.

This module deliberately has no original-test reader. All preparation is stdlib-only.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parents[2]
EXP = Path('experiments/016_finetune_27b/revision_2')
SEEDS = (42, 43, 44)
LABELS = ('SUPPORTS', 'REFUTES', 'NOT ENOUGH INFO')
PARTS = ('train', 'validation', 'holdout')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def write_rows(path, values):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in values), encoding='utf-8')
    temporary.replace(path)


def prompt(root=ROOT):
    return {role: (root / f'prompts/v1/A0_{role}.txt').read_text(encoding='utf-8').strip()
            for role in ('system', 'user')}


def messages(row, p):
    return [{'role': 'system', 'content': p['system']},
            {'role': 'user', 'content': p['user'].format(evidence=row['evidence'], claim=row['claim'])}]


def parse(text, finished=True):
    if not isinstance(text, str) or not finished or re.search(r'</?think\b', text, re.I):
        return 'INVALID'
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    match = re.fullmatch(r'Verdict: (SUPPORTS|REFUTES|NOT ENOUGH INFO)', lines[-1]) if lines else None
    return match.group(1) if match else 'INVALID'


def has_reason(text):
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    return any(not s.startswith('Verdict:') for s in lines[:-1])


def split(rows_in, dataset, seed=2026103016):
    if len({r['id'] for r in rows_in}) != len(rows_in):
        raise ValueError('Duplicate IDs')
    grouped = defaultdict(list)
    mechanisms = defaultdict(set)
    for r in rows_in:
        if r['label'] not in LABELS:
            raise ValueError('Invalid label')
        grouped[(r['mechanism'], r['group'])].append(r)
        mechanisms[r['group']].add(r['mechanism'])
    if any(len(ms) != 1 for ms in mechanisms.values()):
        raise ValueError('A group crosses mechanisms')
    strata = defaultdict(list)
    for m, g in grouped:
        strata[m].append(g)
    counts = Counter(r['label'] for r in rows_in)
    best = None
    for candidate in range(512):
        parts = {p: [] for p in PARTS}
        for m, groups in sorted(strata.items()):
            ordered = sorted(groups, key=lambda g: (hashlib.sha256(
                f'{seed}|{dataset}|{m}|{candidate}|{g}'.encode()).hexdigest(), g))
            n = max(1, int(len(groups) * .2 + .5))
            if 2 * n >= len(groups):
                raise ValueError('Need training groups in every mechanism')
            for i, g in enumerate(ordered):
                parts['validation' if i < n else 'holdout' if i < 2*n else 'train'].extend(grouped[(m, g)])
        if any(len({r['label'] for r in a}) < 3 for a in parts.values()):
            continue
        error = sum((len(a)/len(rows_in)-fraction)**2 + sum(
            (sum(r['label'] == label for r in a)/count-fraction)**2 for label, count in counts.items())
            for (_, a), fraction in zip(parts.items(), (.6, .2, .2)))
        if best is None or (error, candidate) < best[0]:
            best = ((error, candidate), parts)
    if best is None:
        raise ValueError('No valid partition')
    return {p: sorted(a, key=lambda r: r['id']) for p, a in best[1].items()}, best[0][1]


def describe(data):
    return {d: {'rows': len(a), 'groups': len({r['group'] for r in a}),
                'labels': dict(Counter(r['label'] for r in a)),
                'mechanisms': dict(Counter(r['mechanism'] for r in a))}
            for d in ('basic', 'challenge') if (a := [r for r in data if r['dataset'] == d])}


def prepare(root=ROOT):
    exp = root / EXP
    if (exp / 'data_freeze.json').exists():
        return verify_data(root)
    parts = {p: [] for p in PARTS}
    candidates = {}
    sources = {}
    for d in ('basic', 'challenge'):
        source = Path(f'data/splits/v1/{d}/dev.jsonl')
        sources[source.as_posix()] = sha(root / source)
        values, candidates[d] = split([dict(r, dataset=d) for r in rows(root / source)], d)
        for part in PARTS:
            parts[part].extend(values[part])
    protocol = {
        'experiment': '016_finetune_27b_revision_2', 'model_id': 'Qwen/Qwen3.8-27B',
        'model_manifest': 'experiments/016_finetune_27b/model_source.json',
        'precision': 'bfloat16', 'quantization': None, 'seeds': list(SEEDS),
        'prompt': prompt(root), 'input_fields': ['evidence', 'claim'],
        'split_seed': 2026103016, 'split_candidates': candidates,
        'summary': {p: describe(a) for p, a in parts.items()},
        'generation': {'do_sample': False, 'enable_thinking': False,
                       'max_new_tokens': 1024, 'batch_size': 1, 'use_cache': True},
        'training': {'epochs': 3, 'learning_rate': 1e-4, 'weight_decay': 0.,
                     'lora_rank': 8, 'lora_alpha': 16, 'lora_dropout': .05,
                     'target_modules': ['q_proj', 'k_proj', 'v_proj', 'o_proj', 'in_proj_qkv', 'out_proj'],
                     'max_sequence_length': 1536, 'truncate': False,
                     'micro_batch_size': 1, 'effective_batch_size': 16,
                     'max_grad_norm': 1., 'optimizer': 'AdamW', 'scheduler': 'constant',
                     'gradient_checkpointing': True, 'class_reweighting': False,
                     'external_data': False, 'data_augmentation': False},
        'rationales': {'author': 'same BF16 baseline', 'reviewer': 'AI agent, per-example evidence review',
                       'max_words': 60, 'all_training_rows_reviewed': True},
        'selection': 'guardrails pass, challenge accuracy, basic accuracy, challenge macro-F1, earliest epoch',
        'guardrails': {'basic_accuracy_delta_min': -.02, 'each_class_recall_delta_min': -.05},
        'primary': {'metric': 'mean challenge accuracy delta across three seeds',
                    'minimum_gain': .05, 'alpha': .05, 'test': 'two-sided exact group sign permutation'},
        'evaluation': 'Frozen development holdout only, baseline once plus three selected adapters',
        'scope': 'Previously used development data; not a pristine project-wide blind test.',
        'source_hashes': sources,
    }
    for p, a in parts.items():
        write_rows(exp / f'{p}.jsonl', a)
    save(exp / 'protocol.json', protocol)
    paths = [EXP / 'protocol.json', *[EXP / f'{p}.jsonl' for p in PARTS],
             Path(protocol['model_manifest']), Path('prompts/v1/A0_system.txt'), Path('prompts/v1/A0_user.txt')]
    save(exp / 'data_freeze.json', {'files': {p.as_posix(): sha(root / p) for p in paths},
                                   'original_test_content_read': False})
    return verify_data(root)


def verify_files(manifest, root):
    for rel, expected in manifest['files'].items():
        path = (root / rel).resolve()
        if not path.is_relative_to(root.resolve()) or sha(path) != expected:
            raise ValueError('Frozen file changed: ' + rel)


def verify_data(root=ROOT):
    exp = root / EXP
    verify_files(read_json(exp / 'data_freeze.json'), root)
    p = read_json(exp / 'protocol.json')
    verify_files({'files': p['source_hashes']}, root)
    if p['prompt'] != prompt(root):
        raise ValueError('Baseline prompt differs')
    parts = {part: rows(exp / f'{part}.jsonl') for part in PARTS}
    ids, groups, texts, evidence_texts, claim_texts = {}, {}, {}, {}, {}
    for part, data in parts.items():
        for r in data:
            for key, seen in ((r['id'], ids), ((r['dataset'], r['group']), groups),
                              ((r['evidence'].strip(), r['claim'].strip()), texts),
                              (' '.join(r['evidence'].split()).casefold(), evidence_texts),
                              (' '.join(r['claim'].split()).casefold(), claim_texts)):
                if key in seen and (seen is ids or seen[key] != part):
                    raise ValueError('Duplicate ID or cross-partition leakage')
                seen[key] = part
    for d in ('basic', 'challenge'):
        original = {r['id']: r for r in rows(root / f'data/splits/v1/{d}/dev.jsonl')}
        actual = [r for a in parts.values() for r in a if r['dataset'] == d]
        if len(actual) != len(original) or {r['id'] for r in actual} != set(original):
            raise ValueError('Incomplete development partition')
        for r in actual:
            if {k: v for k, v in r.items() if k != 'dataset'} != original[r['id']]:
                raise ValueError('Original content changed')
    return p


def record_key(row):
    return row['dataset'] + '_' + row['id']


def validate_reviews(reviews, drafts_dir, root=ROOT):
    p = verify_data(root)
    draft_identity = read_json(Path(drafts_dir) / 'identity.json')
    draft_engine = root / EXP / 'draft_source/finetune27b_engine.py'
    if (draft_identity.get('phase') != 'training_rationale_drafts'
            or draft_identity.get('data_freeze_sha256') != sha(root / EXP / 'data_freeze.json')
            or draft_identity.get('generation') != p['generation']
            or draft_identity['environment'].get('model_manifest_sha256') != sha(root / p['model_manifest'])
            or draft_identity['environment'].get('precision') != 'bfloat16'
            or draft_identity['environment'].get('prompt_sha256') != digest(p['prompt'])
            or draft_identity['environment'].get('engine_sha256') != sha(draft_engine)):
        raise ValueError('Draft model/prompt/data provenance mismatch')
    data = rows(root / EXP / 'train.jsonl')
    review_map = {r['id']: r for r in reviews}
    if len(review_map) != len(reviews) or set(review_map) != {r['id'] for r in data}:
        raise ValueError('Every training row must have exactly one review')
    excluded = set()
    for r in data:
        a = review_map[r['id']]
        draft = Path(drafts_dir) / (record_key(r) + '.json')
        receipt = read_json(draft)
        if receipt.get('identity') != digest(draft_identity):
            raise ValueError('Draft run identity mismatch')
        if receipt['input_sha256'] != digest(messages(r, prompt(root))):
            raise ValueError('Wrong draft input')
        if a.get('draft_sha256') != sha(draft) or a.get('label') != r['label']:
            raise ValueError('Review source mismatch')
        if not a.get('review_note', '').strip() or a.get('reviewer') != 'agent':
            raise ValueError('Missing explicit review provenance')
        if a.get('status') == 'exclude_group':
            excluded.add((r['dataset'], r['group']))
        elif a.get('status') == 'approved':
            rationale = a.get('rationale', '').strip()
            if not rationale or len(rationale.split()) > 60 or '\n' in rationale or 'Verdict:' in rationale or '<think' in rationale.lower():
                raise ValueError('Invalid reviewed rationale: ' + r['id'])
        else:
            raise ValueError('Review is not approved/excluded: ' + r['id'])
    accepted = [dict(r, rationale=review_map[r['id']]['rationale']) for r in data
                if (r['dataset'], r['group']) not in excluded]
    if set(r['label'] for r in accepted) != set(LABELS):
        raise ValueError('Reviewed training lacks a class')
    return accepted, sorted(excluded)


def target(row):
    if row['label'] not in LABELS or not row.get('rationale', '').strip():
        raise ValueError('Reviewed rationale and gold required')
    return row['rationale'].strip() + '\nVerdict: ' + row['label']


def freeze_training(review_file, drafts_dir, token_audit, root=ROOT):
    exp = root / EXP
    if (exp / 'training_freeze.json').exists():
        p = verify_training(root)
        if (sha(review_file) != sha(exp/'reviews.jsonl')
                or read_json(token_audit) != read_json(exp/'token_audit.json')):
            raise ValueError('Refuse replacing an existing training freeze')
        history = Path(review_file).with_name('reviews_history.jsonl')
        frozen_history = exp/'reviews_history.jsonl'
        if history.exists() != frozen_history.exists() or (history.exists() and sha(history) != sha(frozen_history)):
            raise ValueError('Refuse replacing frozen review history')
        for key, expected in read_json(exp/'training_freeze.json')['draft_hashes'].items():
            if sha(Path(drafts_dir)/(key+'.json')) != expected:
                raise ValueError('Frozen draft changed')
        return p
    accepted, excluded = validate_reviews(rows(review_file), drafts_dir, root)
    audit = read_json(token_audit)
    if audit.get('data_freeze_sha256') != sha(exp / 'data_freeze.json') or audit.get('reviews_sha256') != sha(review_file):
        raise ValueError('Stale token audit')
    if audit.get('truncated') != 0 or not isinstance(audit.get('max_tokens'), int) or audit['max_tokens'] <= 0:
        raise ValueError('Invalid token coverage audit')
    if (audit.get('rows') != len(accepted)
            or audit.get('excluded_groups') != [list(g) for g in excluded]):
        raise ValueError('Token audit coverage mismatch')
    write_rows(exp / 'reviewed_train.jsonl', accepted)
    write_rows(exp / 'reviews.jsonl', rows(review_file))
    save(exp / 'token_audit.json', audit)
    save(exp / 'draft_identity.json', read_json(Path(drafts_dir) / 'identity.json'))
    write_rows(exp / 'rationale_drafts.jsonl', [
        {'key': record_key(r), 'receipt': read_json(Path(drafts_dir)/(record_key(r)+'.json'))}
        for r in rows(exp/'train.jsonl')])
    p = verify_data(root)
    p['training']['max_sequence_length'] = max(1536, math.ceil(audit['max_tokens'] / 256) * 256)
    p['training']['world_size'] = audit['world_size']
    if audit['world_size'] not in (1, 2):
        raise ValueError('Unsupported training world size')
    p['training']['gradient_accumulation_steps'] = 16 // audit['world_size']
    p['excluded_training_groups'] = excluded
    p['reviewed_training_summary'] = describe(accepted)
    save(exp / 'training_protocol.json', p)
    files = [EXP / name for name in ('training_protocol.json', 'reviewed_train.jsonl', 'reviews.jsonl', 'token_audit.json', 'draft_identity.json', 'rationale_drafts.jsonl', 'data_freeze.json')]
    files += [f.relative_to(root) for f in sorted((exp/'draft_source').glob('*.py'))]
    history=Path(review_file).with_name('reviews_history.jsonl')
    if history.exists():
        write_rows(exp/'reviews_history.jsonl',rows(history))
        files.append(EXP/'reviews_history.jsonl')
    save(exp / 'training_freeze.json', {'files': {f.as_posix(): sha(root / f) for f in files},
        'draft_hashes': {record_key(r): sha(Path(drafts_dir) / (record_key(r) + '.json')) for r in rows(exp / 'train.jsonl')},
        'original_test_content_read': False})
    return verify_training(root)


def verify_training(root=ROOT):
    verify_data(root)
    verify_files(read_json(root / EXP / 'training_freeze.json'), root)
    return read_json(root / EXP / 'training_protocol.json')


def exact_group_test(deltas):
    distribution = {0: 1}
    for d in deltas:
        new = defaultdict(int)
        for x, n in distribution.items():
            new[x + d] += n
            new[x - d] += n
        distribution = new
    return sum(n for x, n in distribution.items() if abs(x) >= abs(sum(deltas))) / 2**len(deltas)


def metric_rows(data, predictions):
    if set(predictions) != {record_key(r) for r in data}:
        raise ValueError('Prediction coverage mismatch')
    return [dict(r, gold_label=r['label'], predicted_label=predictions[record_key(r)]['prediction'],
                 parse_status='ok' if predictions[record_key(r)]['prediction'] in LABELS else 'invalid',
                 status=predictions[record_key(r)].get('status', 'completed'),
                 latency_seconds=predictions[record_key(r)].get('seconds'),
                 usage={'completion_tokens': predictions[record_key(r)].get('output_tokens')}) for r in data]


def paired_metrics(data, base, adapter, p):
    from .metrics import compute_metrics, paired_comparison
    left, right = metric_rows(data, base), metric_rows(data, adapter)
    out = {}
    guard = True
    for d in ('basic', 'challenge'):
        a, b = [r for r in left if r['dataset'] == d], [r for r in right if r['dataset'] == d]
        if not a:
            raise ValueError('Both datasets required')
        ma, mb = compute_metrics(a), compute_metrics(b)
        pair = paired_comparison(a, b)
        out[d] = {'baseline': ma, 'adapter': mb, 'paired': pair}
        out[d]['by_mechanism'] = {m: {
            'baseline': compute_metrics([r for r in a if r['mechanism'] == m]),
            'adapter': compute_metrics([r for r in b if r['mechanism'] == m])}
            for m in sorted({r['mechanism'] for r in a})}
        for arm, predictions, metric in (('baseline', base, ma), ('adapter', adapter, mb)):
            selected = [predictions[record_key(r)] for r in data if r['dataset'] == d]
            metric['missing_reason_count'] = sum(not v.get('reason_present', False) for v in selected)
            metric['missing_reason_rate'] = metric['missing_reason_count'] / len(selected)
            metric['truncated_count'] = sum(v.get('status') == 'truncated' for v in selected)
            metric['thinking_count'] = sum(v.get('thinking_generated', False) for v in selected)
            metric['request_failure_count'] = sum(v.get('status') == 'request_failed' for v in selected)
            metric['total_input_tokens'] = sum(v.get('input_tokens', 0) for v in selected)
            metric['total_output_tokens'] = sum(v.get('output_tokens', 0) for v in selected)
            metric['supports_to_nei'] = metric['confusion_matrix']['SUPPORTS']['NOT ENOUGH INFO']
            metric['refutes_to_nei'] = metric['confusion_matrix']['REFUTES']['NOT ENOUGH INFO']
        if d == 'basic':
            guard &= pair['accuracy_delta'] >= p['guardrails']['basic_accuracy_delta_min'] - 1e-12
        for label in LABELS:
            aa, bb = ma['classes'][label]['recall'], mb['classes'][label]['recall']
            guard &= aa is not None and bb is not None and bb - aa >= p['guardrails']['each_class_recall_delta_min'] - 1e-12
    return {'datasets': out, 'guardrails_pass': bool(guard)}


def selection_key(entry):
    ds = entry['metrics']['datasets']
    return (entry['metrics']['guardrails_pass'], ds['challenge']['adapter']['accuracy'],
            ds['basic']['adapter']['accuracy'], ds['challenge']['adapter']['macro_f1'], -entry['epoch'])


def seed_summary(metrics):
    result = {}
    for name in metrics[0]:
        values = [m[name] for m in metrics]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            result[name] = {'mean': mean(values), 'stdev': stdev(values)}
        elif all(isinstance(v, dict) for v in values):
            result[name] = seed_summary(values)
    return result


def final_report(data, base, adapters, p):
    if set(adapters) != {str(s) for s in SEEDS}:
        raise ValueError('All three seeds required')
    by_seed = {s: paired_metrics(data, base, predictions, p) for s, predictions in adapters.items()}
    result = {'by_seed': by_seed, 'datasets': {}, 'scope': p['scope']}
    for d in ('basic', 'challenge'):
        subset = [r for r in data if r['dataset'] == d]
        deltas = defaultdict(int)
        for r in subset:
            key = record_key(r)
            deltas[r['group']] += sum(int(adapters[str(s)][key]['prediction'] == r['label']) for s in SEEDS) - 3*int(base[key]['prediction'] == r['label'])
        acc = [v['datasets'][d]['adapter']['accuracy'] for v in by_seed.values()]
        differences = [v['datasets'][d]['paired']['accuracy_delta'] for v in by_seed.values()]
        result['datasets'][d] = {'mean_accuracy': mean(acc), 'seed_accuracy_stdev': stdev(acc),
            'mean_accuracy_delta': mean(differences), 'group_integer_deltas': dict(deltas),
            'two_sided_group_p': exact_group_test(list(deltas.values()))}
        metrics = [v['datasets'][d]['adapter'] for v in by_seed.values()]
        result['datasets'][d]['seed_summary'] = seed_summary(metrics)
        mechanisms = by_seed['42']['datasets'][d]['by_mechanism']
        result['datasets'][d]['seed_summary_by_mechanism'] = {
            mechanism: seed_summary([v['datasets'][d]['by_mechanism'][mechanism]['adapter']
                                    for v in by_seed.values()]) for mechanism in mechanisms}
        result['datasets'][d]['seed_recall_summary'] = {
            label: {'mean': mean(m['classes'][label]['recall'] for m in metrics),
                    'stdev': stdev(m['classes'][label]['recall'] for m in metrics)} for label in LABELS}
    c = result['datasets']['challenge']
    result['guardrails_pass'] = all(v['guardrails_pass'] for v in by_seed.values())
    result['primary_pass'] = (result['guardrails_pass'] and c['mean_accuracy_delta'] >= .05 - 1e-12
                              and c['two_sided_group_p'] <= .05)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'verify', 'freeze'])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--reviews', type=Path)
    parser.add_argument('--drafts', type=Path)
    parser.add_argument('--token-audit', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(args.root)
    elif args.action == 'verify':
        result = verify_data(args.root)
    else:
        if not all((args.reviews, args.drafts, args.token_audit)):
            parser.error('freeze requires --reviews, --drafts and --token-audit')
        result = freeze_training(args.reviews, args.drafts, args.token_audit, args.root)
    print(json.dumps(result.get('summary', result), ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
