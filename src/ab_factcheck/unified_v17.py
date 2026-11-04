"""Frozen, development-only comparison on one BF16 inference implementation."""
import argparse
from collections import Counter, defaultdict
from contextlib import nullcontext
import csv
import io
import itertools
import json
from pathlib import Path
from statistics import mean, stdev
import subprocess
import time

from . import finetune27b_v2 as core

ROOT = Path(__file__).resolve().parents[2]
EXP = Path('experiments/017_unified_comparison')
OLD = Path('experiments/016_finetune_27b/revision_2')
ARMS = ('baseline', 'nli', 'pj_v3', 'lora42', 'lora43', 'lora44')
FAMILIES = {'baseline': ['baseline'], 'nli': ['nli'], 'pj_v3': ['pj_v3'],
            'lora': ['lora42', 'lora43', 'lora44']}


def git_text(branch, path):
    raw = subprocess.check_output(['git', 'show', f'{branch}:{path}'], cwd=ROOT).decode('utf-8')
    return raw.replace('\r\n', '\n').strip()


def normalize_prompts(base, nli, pj):
    output = 'Return a JSON object with relation and a brief justification.'
    if nli.count(output) != 1 or pj.count('\n\nEVIDENCE:') != 1:
        raise ValueError('Unexpected source prompt structure')
    nli = nli.replace(output, '').strip() + (
        '\nMap ENTAILMENT to SUPPORTS, CONTRADICTION to REFUTES, and NEUTRAL to NOT ENOUGH INFO.')
    pj = pj.split('\n\nEVIDENCE:', 1)[0].removeprefix('System: ').strip()
    return {'baseline': base, 'nli': dict(base, system=nli), 'pj_v3': dict(base, system=pj),
            **{f'lora{s}': base for s in core.SEEDS}}


def prepare():
    if (ROOT/EXP/'freeze.json').exists():
        return verify()
    p = core.read_json(ROOT/OLD/'training_protocol.json')
    data = core.rows(ROOT/OLD/'holdout.jsonl')
    other = core.rows(ROOT/OLD/'train.jsonl') + core.rows(ROOT/OLD/'validation.jsonl')
    groups = {(r['dataset'], r['group']) for r in data}
    if groups & {(r['dataset'], r['group']) for r in other}:
        raise ValueError('Training/selection group overlap')
    if {(r['evidence'], r['claim']) for r in data} & {(r['evidence'], r['claim']) for r in other}:
        raise ValueError('Training/selection text overlap')
    if Counter(r['dataset'] for r in data) != {'basic': 120, 'challenge': 141}:
        raise ValueError('Unexpected holdout size')
    base = core.prompt(ROOT)
    if base != p['prompt']:
        raise ValueError('Original A0 prompt changed')
    nli = git_text('ddfc4d2', 'prompts/v7/nli_system.txt')
    pj = git_text('8d8c4fb', 'prompts/imported_pj_20261029/challenge-prompt-v3-full-20261028/prompt-v3.txt')
    prompts = normalize_prompts(base, nli, pj)
    data.sort(key=lambda r: core.digest([2026103117, r['dataset'], r['id']]))
    core.write_rows(ROOT/EXP/'evaluation.jsonl', data)
    core.save(ROOT/EXP/'prompts.json', prompts)
    core.save(ROOT/EXP/'source_prompts.json', {'nli': nli, 'pj_v3': pj, 'A0': base})
    selections = {}
    for seed in core.SEEDS:
        source = ROOT/OLD/f'results/selection-{seed}.json'
        s = core.read_json(source)
        if s['holdout_used_for_selection']:
            raise ValueError('Adapter selected on holdout')
        selections[str(seed)] = dict(s['selected'], selection_sha256=core.sha(source))
    protocol = {
        'name': 'unified_bf16_development_v17', 'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'arms': ARMS, 'families': FAMILIES, 'n': 261, 'generations': 1566,
        'data_scope': 'Historical development data, 120 basic + 141 challenge; disjoint from this LoRA training and validation by group/text. PJ used full benchmark, NLI has prior development exposure, and prior LoRA holdout results are known. NOT independent blind testing.',
        'original_test_policy': 'No original test/raw benchmark files are read or packaged. Prior V16 engineering access deviation remains disclosed.',
        'sources': {'nli_commit': 'ddfc4d2', 'pj_commit': '8d8c4fb', 'finetune_commit': '888fc80',
                    'holdout_sha256': core.sha(ROOT/OLD/'holdout.jsonl'),
                    'training_freeze_sha256': core.sha(ROOT/OLD/'training_freeze.json')},
        'model': p['model_id'], 'model_manifest_sha256': core.sha(ROOT/p['model_manifest']),
        'generation': p['generation'], 'prompts': 'Common A0 user template and final Verdict contract; substantive NLI/PJ rules preserved. NLI JSON instruction replaced by explicit label mapping. Normalized methods, not original output protocols.',
        'compute': 'Same frozen BF16 backbone, FP32 LoRA, Transformers eager attention and torch gated-delta reference. Same model object per worker; disable adapter for baseline/NLI/PJ. No training or checkpoint reselection.',
        'schedule': 'Two identical 910B3 workers, fixed row index modulo 2. Every row evaluated in all six arms on the same worker; six-arm start order rotates by row index. Fresh responses for every cell; no historical prediction reuse.',
        'workers': 2, 'devices': [0, 1], 'selected_adapters': selections,
        'statistics': 'Separate basic/challenge scores. Six challenge family-pair comparisons, exact two-sided group sign permutation, Holm correction across all six. LoRA contributes per-item mean of three seeds, not three independent observations. Descriptive historical-development inference only.',
        'success_rule': {'challenge_gain_min': .05, 'holm_alpha': .05, 'basic_accuracy_min_delta': -.02,
                         'each_class_recall_min_delta': -.05, 'lora': 'Every seed must satisfy guardrails; mean accuracy used for family comparison.'},
        'failure_policy': 'Received errors, truncation and malformed outputs count wrong; never regenerate a received answer. Crash with unresolved inflight cell halts resume pending explicit failure accounting. No outcome-dependent stopping.',
        'cost': 'Report actual input/output tokens and generation seconds; no equal-token-cost claim. Warmup costs separate. Latencies are this engine/hardware experiment only.',
    }
    core.save(ROOT/EXP/'protocol.json', protocol)
    files = [EXP/n for n in ('evaluation.jsonl', 'prompts.json', 'source_prompts.json', 'protocol.json')]
    files += [OLD/'training_protocol.json', Path(p['model_manifest'])]
    files += [Path('src/ab_factcheck')/n for n in ('unified_v17.py', 'finetune27b_v2.py',
        'finetune27b_engine.py', 'finetune27b_training_v2.py', 'finetune27b_run_v2.py',
        'metrics.py', 'common.py', 'splitting.py', '__init__.py')]
    files += [Path('tests/test_unified_v17.py'), Path('scripts/audit_unified_v17.py'), Path('scripts/manage_unified_v17.py')]
    core.save(ROOT/EXP/'freeze.json', {str(f).replace('\\', '/'): core.sha(ROOT/f) for f in files})
    return verify()


def verify():
    for f, expected in core.read_json(ROOT/EXP/'freeze.json').items():
        if core.sha(ROOT/f) != expected:
            raise ValueError('Frozen file changed: ' + f)
    return core.read_json(ROOT/EXP/'protocol.json')


def read_records(output, data, freeze):
    predictions = {a: {} for a in ARMS}
    for row in data:
        key = core.record_key(row)
        for arm in ARMS:
            r = core.read_json(output/'records'/arm/(key+'.json'))
            if (r['freeze_sha256'] != freeze or r['arm'] != arm or r['id'] != row['id']
                    or r['dataset'] != row['dataset'] or r['record_sha256'] != core.digest({k:v for k,v in r.items() if k != 'record_sha256'})):
                raise ValueError('Record identity mismatch')
            expected = 'INVALID' if r.get('thinking_generated') else core.parse(r['text'], r['finished'])
            if r['prediction'] != expected:
                raise ValueError('Record parser mismatch')
            predictions[arm][key] = r
    return predictions


def family_pair(data, predictions, left, right):
    # Scale every family mean by three to retain exact integer group statistics.
    deltas = defaultdict(int)
    for row in data:
        key = core.record_key(row)
        def score(family):
            arms = FAMILIES[family]
            return (3//len(arms))*sum(predictions[a][key]['prediction'] == row['label'] for a in arms)
        deltas[row['group']] += score(right) - score(left)
    return {'left': left, 'right': right, 'n': len(data), 'groups': len(deltas),
            'accuracy_delta': sum(deltas.values())/(3*len(data)),
            'p': core.exact_group_test(list(deltas.values())), 'group_deltas_scaled_3': dict(deltas)}


def holm(comparisons):
    ordered = sorted(comparisons, key=lambda x: x['p'])
    previous = 0.
    for i, item in enumerate(ordered):
        previous = max(previous, min(1., item['p']*(len(ordered)-i)))
        item['holm_p'] = previous
    return comparisons


def report(output):
    from .metrics import compute_metrics
    p = verify()
    data = core.rows(ROOT/EXP/'evaluation.jsonl')
    freeze = core.sha(ROOT/EXP/'freeze.json')
    predictions = read_records(output, data, freeze)
    result = {'freeze_sha256': freeze, 'scope': p['data_scope'], 'datasets': {}}
    for dataset in ('basic', 'challenge'):
        rows = [r for r in data if r['dataset'] == dataset]
        scores = {}
        for arm in ARMS:
            records = {core.record_key(r): predictions[arm][core.record_key(r)] for r in rows}
            scored = core.metric_rows(rows, records)
            m = compute_metrics(scored)
            m['mechanisms'] = {g: compute_metrics([r for r in scored if r['mechanism'] == g])
                               for g in sorted({r['mechanism'] for r in rows})}
            m['input_tokens'] = sum(r['input_tokens'] for r in records.values())
            m['output_tokens'] = sum(r['output_tokens'] for r in records.values())
            m['missing_reason'] = sum(not r['reason_present'] for r in records.values())
            scores[arm] = m
        pairs = [family_pair(rows, predictions, a, b) for a,b in itertools.combinations(FAMILIES, 2)]
        result['datasets'][dataset] = {'n': len(rows), 'scores': scores, 'pairs': holm(pairs),
            'lora_accuracy_mean': mean(scores[a]['accuracy'] for a in FAMILIES['lora']),
            'lora_accuracy_stdev': stdev(scores[a]['accuracy'] for a in FAMILIES['lora'])}
    constraints = {}
    for arm in ARMS[1:]:
        reasons = []
        for d in ('basic', 'challenge'):
            scores = result['datasets'][d]['scores']; a, b = scores['baseline'], scores[arm]
            if d == 'basic' and b['accuracy']-a['accuracy'] < -.02-1e-12:
                reasons.append('basic accuracy decrease >2pp')
            for label in core.LABELS:
                delta = b['classes'][label]['recall']-a['classes'][label]['recall']
                if delta < -.05-1e-12:
                    reasons.append(f'{d}/{label} recall {delta*100:+.2f}pp')
        constraints[arm] = {'passed': not reasons, 'failures': reasons}
    result['guardrails'] = constraints
    result['baseline_success'] = {}
    for pair in result['datasets']['challenge']['pairs']:
        if pair['left'] == 'baseline':
            family = pair['right']
            result['baseline_success'][family] = (pair['accuracy_delta'] >= .05-1e-12
                and pair['holm_p'] <= .05 and all(constraints[a]['passed'] for a in FAMILIES[family]))
    result['record_hashes'] = {f'{a}/{key}': r['record_sha256'] for a, rs in predictions.items() for key,r in rs.items()}
    core.save(output/'results.json', result)
    lines = ['# 统一 BF16 开发比较', '', p['data_scope'], '',
        '全部 1,566 个评测单元重新生成；不是独立测试。三个适配器分别计分，未挑选保留集最高分种子。', '',
        '| 方法 | basic | challenge | challenge NEI召回 | challenge R召回 | 幅度限制 |', '|---|---:|---:|---:|---:|---|']
    for arm in ARMS:
        b = result['datasets']['basic']['scores'][arm]; c = result['datasets']['challenge']['scores'][arm]
        lines.append(f"| {arm} | {b['correct']}/{b['n']} ({b['accuracy']:.2%}) | {c['correct']}/{c['n']} ({c['accuracy']:.2%}) | {c['classes']['NOT ENOUGH INFO']['recall']:.2%} | {c['classes']['REFUTES']['recall']:.2%} | {constraints.get(arm, {}).get('passed', '参照')} |")
    lines += ['', '## 挑战集配对比较', '', '| 左侧 | 右侧 | 右减左 | 原始p | Holm p |', '|---|---|---:|---:|---:|']
    for v in result['datasets']['challenge']['pairs']:
        lines.append(f"| {v['left']} | {v['right']} | {v['accuracy_delta']*100:+.2f} pp | {v['p']:.8g} | {v['holm_p']:.8g} |")
    lines += ['', '## 相对共同基线的预定门槛', '', json.dumps(result['baseline_success'], ensure_ascii=False), '',
        '达到门槛只描述历史开发数据；不等于独立测试泛化或统计非劣效。', '', '## 幅度限制未通过项', '']
    for arm, value in constraints.items():
        if value['failures']:
            lines.append('- '+arm+': '+'; '.join(value['failures']))
    lines += ['', '## 实际生成成本', '', '| 方法 | 输入token | 输出token | 平均生成秒 |', '|---|---:|---:|---:|']
    for a in ARMS:
        rs = list(predictions[a].values())
        lines.append(f"| {a} | {sum(r['input_tokens'] for r in rs)} | {sum(r['output_tokens'] for r in rs)} | {mean(r['seconds'] for r in rs):.3f} |")
    lines += ['', '完整三类指标、分机制结果、无效输出、均值/标准差见 results.json；逐题原文与 token 见 records。',
        '原 A0、NLI、PJ 实质指导不同；统一的是数据、权重精度、计算路径、输入角色、输出协议、上限及评分，不声称提示词长度相等。',
        'PRESUP 在原 LoRA 审核训练中没有样本；训练理由是 AI 辅助标注。V16 原测试封存工程偏差仍保留披露。', '']
    (output/'RESULTS.md').write_text('\n'.join(lines), encoding='utf-8')
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=['dataset','id','group','mechanism','gold',*ARMS]); writer.writeheader()
    for row in data:
        writer.writerow({k: row[k] for k in ('dataset','id','group','mechanism')} | {'gold':row['label']} |
                        {a: predictions[a][core.record_key(row)]['prediction'] for a in ARMS})
    (output/'predictions.csv').write_text(stream.getvalue(), encoding='utf-8')
    return {'complete': True, 'results_sha256': core.sha(output/'results.json')}


def run(args):
    import fcntl
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file
    from . import finetune27b_engine as engine
    p = verify()
    if args.worker not in range(p['workers']):
        raise ValueError('Invalid worker')
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output/f'worker-{args.worker}.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    freeze = core.sha(ROOT/EXP/'freeze.json')
    train_p = core.read_json(ROOT/OLD/'training_protocol.json')
    model, tokenizer, torch, device, environment = engine.load(args.model, train_p)
    # Enforce core precision/package/code identity against the trained model receipt.
    smoke = core.read_json(args.formal/'smoke/receipt.json')['environment']
    for key in ('model_manifest_sha256','packages','precision','attention','gated_delta',
                'target_modules','trainable_parameters','original_parameter_count',
                'adapter_parameter_dtypes','backbone_parameter_dtypes','engine_sha256','code_sha256'):
        if environment[key] != smoke[key]:
            raise ValueError('Frozen inference environment mismatch: '+key)
    adapters = {}
    for seed, s in p['selected_adapters'].items():
        folder = args.formal/f'seed-{seed}'/s['checkpoint']
        if (core.sha(folder/'adapter_model.safetensors') != s['adapter_sha256']
                or core.sha(folder/'adapter_config.json') != s['adapter_config_sha256']
                or core.sha(args.formal/f'seed-{seed}/selection.json') != s['selection_sha256']):
            raise ValueError('Selected adapter changed')
        adapters['lora'+seed] = load_file(str(folder/'adapter_model.safetensors'))
    prompts = core.read_json(ROOT/EXP/'prompts.json')
    identity = {'freeze_sha256': freeze, 'worker': args.worker, 'environment': environment}
    identity_path = args.output/f'worker-{args.worker}-identity.json'
    if identity_path.exists() and core.read_json(identity_path) != identity:
        raise ValueError('Worker identity changed')
    core.save(identity_path, identity)
    for arm in ARMS:
        probe = args.output/'warmup'/f'{args.worker}-{arm}.json'
        if probe.exists():
            continue
        if arm in adapters:
            set_peft_model_state_dict(model, adapters[arm])
        model.eval()
        with model.disable_adapter() if arm not in adapters else nullcontext():
            result = engine.generate(model, tokenizer, {'id':'warmup','evidence':'The sealed box contains exactly two red cubes and no other objects.',
                'claim':'The sealed box contains a blue sphere.'}, dict(train_p, prompt=prompts[arm]), torch, device)
        core.save(probe, result)
    data = core.rows(ROOT/EXP/'evaluation.jsonl')
    assigned = [(i,r) for i,r in enumerate(data) if i % p['workers'] == args.worker]
    for position, (index, row) in enumerate(assigned):
        order = ARMS[index % len(ARMS):]+ARMS[:index % len(ARMS)]
        base_hashes = []
        for arm in order:
            key = core.record_key(row)
            path = args.output/'records'/arm/(key+'.json')
            current_p = dict(train_p, prompt=prompts[arm])
            prefix = engine.encode(row, tokenizer, current_p, require_target=False, enforce_limit=False)['prefix']
            expected_input = core.digest(core.messages(row, prompts[arm]))
            inflight = path.with_suffix('.inflight')
            if path.exists():
                r = core.read_json(path)
                if (r['freeze_sha256'] != freeze or r['input_sha256'] != expected_input
                        or r['input_token_sha256'] != core.digest(prefix)
                        or r['record_sha256'] != core.digest({k:v for k,v in r.items() if k != 'record_sha256'})):
                    raise ValueError('Existing record identity mismatch')
                if inflight.exists():
                    inflight.unlink()
            else:
                if inflight.exists():
                    raise ValueError('Unresolved interrupted generation: '+str(inflight))
                core.save(inflight, {'worker': args.worker, 'arm': arm, 'id': row['id'], 'freeze_sha256': freeze})
                if arm in adapters:
                    set_peft_model_state_dict(model, adapters[arm])
                model.eval()
                started = time.perf_counter()
                failure = None
                try:
                    with model.disable_adapter() if arm not in adapters else nullcontext():
                        r = engine.generate(model, tokenizer, row, current_p, torch, device)
                except Exception as exc:
                    failure = exc
                    r = {'text':'','raw_text':'','prediction':'INVALID','finished':False,'status':'request_failed',
                         'reason_present':False,'seconds':time.perf_counter()-started,'input_sha256':expected_input,
                         'input_token_sha256':core.digest(prefix),'input_tokens':len(prefix),'output_tokens':0,
                         'output_token_ids':[], 'error_type':type(exc).__name__}
                r.update(freeze_sha256=freeze, worker=args.worker, arm=arm, dataset=row['dataset'], id=row['id'],
                         worker_identity_sha256=core.digest(identity))
                r['record_sha256'] = core.digest(r)
                core.save(path, r)
                inflight.unlink()
                if failure:
                    raise failure
            if arm in ('baseline', *adapters):
                base_hashes.append(r['input_token_sha256'])
            print(json.dumps({'phase':'generation','worker':args.worker,'row':position+1,'rows':len(assigned),
                              'arm':arm,'seconds':r['seconds']}), flush=True)
        if len(set(base_hashes)) != 1:
            raise ValueError('Baseline and adapter inputs differ')
    core.save(args.output/f'worker-{args.worker}-complete.json', {'complete':True,'n':len(assigned)*6,'freeze_sha256':freeze})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare','verify','run','report'])
    parser.add_argument('--worker',type=int,default=0)
    parser.add_argument('--model',type=Path,default=Path('/root/ab_finetune27b_20261030/models/Qwen3.8-27B'))
    parser.add_argument('--formal',type=Path,default=Path('/root/ab_finetune27b_20261030/revision_2_runs/formal'))
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/unified_v17')
    args = parser.parse_args()
    if args.action == 'run':
        run(args)
    else:
        result = {'prepare':prepare,'verify':verify,'report':lambda:report(args.output)}[args.action]()
        print(json.dumps(result,ensure_ascii=True))


if __name__ == '__main__':
    main()
