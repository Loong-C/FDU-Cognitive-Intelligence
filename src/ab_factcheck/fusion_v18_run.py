"""V18 physical calls, checkpoint selection and deterministic fusion execution."""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import time

from . import finetune27b_v2 as c
from . import finetune27b_engine as engine
from . import fusion_v18 as f


def verify_runtime():
    path = f.ROOT / f.EXP / 'runtime.json'
    for name, sha in c.read_json(path)['files'].items():
        if c.sha(f.ROOT / name) != sha:
            raise ValueError('Frozen runtime changed: ' + name)
    return c.sha(path)


class Runtime:
    def __init__(self, args):
        self.args = args
        self.p = f.verify()
        self.runtime_sha = verify_runtime()
        self.train_p = c.read_json(f.ROOT / f.OLD / 'training_protocol.json')
        self.model, self.tokenizer, self.torch, self.device, self.env = engine.load(args.model, self.train_p)
        previous = c.read_json(args.formal / 'smoke/receipt.json')['environment']
        for key in ('model_manifest_sha256', 'packages', 'precision', 'attention', 'gated_delta',
                    'target_modules', 'trainable_parameters', 'original_parameter_count',
                    'adapter_parameter_dtypes', 'backbone_parameter_dtypes', 'engine_sha256', 'code_sha256'):
            if self.env[key] != previous[key]:
                raise ValueError('Original BF16 inference environment mismatch: ' + key)
        self.adapter = None
        self.adapter_sha = None
        self.weights = {}
        self.prompts = c.read_json(f.ROOT / f.EXP / 'prompts.json')

    def activate(self, name, folder=None):
        if name is None:
            self.adapter, self.adapter_sha = None, None
            return
        if name == self.adapter:
            return
        from safetensors.torch import load_file
        from peft import set_peft_model_state_dict
        if folder is None:
            if name.startswith('old_'):
                seed = name.rsplit('_', 1)[1]
                selection = self.p['old_adapters'][seed]
                if c.sha(self.args.formal / f'seed-{seed}/selection.json') != selection['selection_sha256']:
                    raise ValueError('Old adapter selection changed')
                folder = self.args.formal / f'seed-{seed}' / selection['checkpoint']
            else:
                _, source, seed = name.split('_')
                selection = c.read_json(self.args.output / 'training' / source / f'seed-{seed}/selection.json')['selected']
                folder = self.args.output / 'training' / source / f'seed-{seed}' / selection['checkpoint']
            if c.sha(folder / 'adapter_model.safetensors') != selection['adapter_sha256'] or c.sha(folder / 'adapter_config.json') != selection['adapter_config_sha256']:
                raise ValueError('Selected adapter changed')
        sha = c.sha(folder / 'adapter_model.safetensors')
        if sha not in self.weights:
            self.weights[sha] = load_file(str(folder / 'adapter_model.safetensors'))
        set_peft_model_state_dict(self.model, self.weights[sha])
        self.model.eval()
        self.adapter, self.adapter_sha = name, sha

    def call(self, row, prompt, relative, phase, dependencies=()):
        path = self.args.output / relative
        p = dict(self.train_p, prompt=prompt)
        prefix = engine.encode(row, self.tokenizer, p, require_target=False, enforce_limit=False)['prefix']
        identity = {'freeze': c.sha(f.ROOT / f.EXP / 'freeze.json'), 'runtime': self.runtime_sha,
                    'environment': c.digest(self.env), 'adapter_sha256': self.adapter_sha,
                    'phase': phase, 'input_sha256': c.digest(c.messages(row, prompt)),
                    'input_token_sha256': c.digest(prefix), 'generation': self.p['generation'],
                    'dependencies': list(dependencies)}
        if path.exists():
            value = f.check_record(c.read_json(path))
            if value['identity'] != identity:
                raise ValueError('Cached call identity mismatch: ' + str(relative))
            return value
        inflight = path.with_suffix('.inflight')
        if inflight.exists():
            raise ValueError('Unresolved interrupted call: ' + str(relative))
        f.immutable(inflight, {'identity': identity, 'key': c.record_key(row), 'started_utc': time.time()})
        started = time.perf_counter()
        failure = None
        try:
            with self.model.disable_adapter() if self.adapter is None else nullcontext():
                value = engine.generate(self.model, self.tokenizer, row, p, self.torch, self.device)
        except Exception as error:
            failure = error
            value = {'text': '', 'raw_text': '', 'prediction': 'INVALID', 'finished': False,
                     'status': 'request_failed', 'reason_present': False, 'input_tokens': len(prefix),
                     'output_tokens': 0, 'output_token_ids': [], 'seconds': time.perf_counter() - started,
                     'error_type': type(error).__name__}
        value.update(identity=identity, dataset=row['dataset'], id=row['id'],
                     physical_call=Path(relative).as_posix(), input_token_sha256=c.digest(prefix),
                     logical_calls=1, input_sha256=identity['input_sha256'])
        value = f.seal_record(value)
        f.immutable(path, value)
        inflight.unlink()
        print(json.dumps({'phase': phase, 'call': str(relative), 'seconds': value['seconds'], 'status': value['status']}), flush=True)
        if failure:
            raise failure
        return value

    def smoke(self, part, worker):
        rows = f.data(part)
        row = max(rows, key=lambda r: len(engine.encode(r, self.tokenizer, self.train_p, require_target=False, enforce_limit=False)['prefix']))
        self.activate(None)
        long_candidate = {'prediction': 'NOT ENOUGH INFO', 'text': 'analysis ' * 1024 + '\nVerdict: NOT ENOUGH INFO'}
        for name, prompt in [('nli', self.prompts['nli']), ('pj', self.prompts['pj']),
                             ('review_long', f.review_prompt(row, [long_candidate] * 3, part))]:
            self.call(row, prompt, Path('smoke') / part / f'worker-{worker}-{name}.json', 'smoke')
        f.immutable(self.args.output / 'smoke' / part / f'worker-{worker}-passed.json',
                    {'passed': True, 'environment': self.env, 'runtime': self.runtime_sha,
                     'max_input_case': c.record_key(row)})


def teachers(rt):
    rt.smoke('train', rt.args.worker)
    for index, row in enumerate(f.data('train')):
        if index % 2 != rt.args.worker:
            continue
        key = c.record_key(row)
        rt.activate(None)
        records = []
        # Rotate the first two independent calls; joint always follows both.
        first = ('nli', 'pj') if index % 4 < 2 else ('pj', 'nli')
        by_source = {}
        for source in first:
            by_source[source] = rt.call(row, rt.prompts[source], Path('teachers') / source / (key + '.json'), 'teacher')
        records = [by_source['nli'], by_source['pj']]
        rt.call(row, f.review_prompt(row, records, 'train'), Path('teachers/joint') / (key + '.json'),
                'teacher_joint', [v['record_sha256'] for v in records])


def require_recommendation(output):
    recommendation = c.read_json(output / 'recommendation.json')
    if recommendation['validation_results_sha256'] != c.sha(output / 'validation/results.json'):
        raise ValueError('Validation recommendation changed')
    if recommendation['freeze'] != c.sha(f.ROOT / f.EXP / 'freeze.json'):
        raise ValueError('Recommendation belongs to another experiment')
    audit = c.read_json(output / 'validation/audit.json')
    if not audit['passed'] or audit['results_sha256'] != recommendation['validation_results_sha256']:
        raise ValueError('Validation must pass independent audit before evaluation')
    for relative, digest in recommendation['selection_hashes'].items():
        if c.sha(output / relative) != digest:
            raise ValueError('Selected checkpoint changed after recommendation')


def direct(rt):
    part = rt.args.part
    if part == 'evaluation':
        require_recommendation(rt.args.output)
    arms = list(rt.p['direct']) if rt.args.arm == 'all' else [rt.args.arm]
    for index, row in enumerate(f.data(part)):
        if index % 2 != rt.args.worker:
            continue
        order = arms[index % len(arms):] + arms[:index % len(arms)]
        for arm in order:
            spec = rt.p['direct'][arm]
            rt.activate(spec['adapter'])
            key = c.record_key(row)
            relative = Path(part) / 'direct' / arm / (key + '.json')
            # Selected A0 checkpoint-validation answers are the exact same physical calls.
            if part == 'validation' and arm.startswith('distill_'):
                _, source, seed = arm.split('_')
                selection = c.read_json(rt.args.output / 'training' / source / f'seed-{seed}/selection.json')['selected']
                original = Path('checkpoint_validation') / source / f'seed-{seed}' / f"epoch-{selection['epoch']}" / (key + '.json')
                value = f.check_record(c.read_json(rt.args.output / original))
                if value['identity']['adapter_sha256'] != rt.adapter_sha or value['input_sha256'] != c.digest(c.messages(row, rt.prompts['a0'])):
                    raise ValueError('Checkpoint cache is not the selected A0 input')
                if value['identity']['runtime'] != rt.runtime_sha or value['identity']['environment'] != c.digest(rt.env):
                    raise ValueError('Checkpoint cache environment changed')
                f.immutable(rt.args.output / relative, value)
            else:
                rt.call(row, rt.prompts[spec['prompt']], relative, part)


def fusion(rt):
    part = rt.args.part
    if part == 'evaluation':
        require_recommendation(rt.args.output)
    rt.activate(None)
    for index, row in enumerate(f.data(part)):
        if index % 2 != rt.args.worker:
            continue
        key = c.record_key(row)
        for name, spec in rt.p['fusion'].items():
            refs = [Path(part) / 'direct' / arm / (key + '.json') for arm in spec['components']]
            candidates = [f.check_record(c.read_json(rt.args.output / r)) for r in refs]
            label = f.consensus(candidates)
            reviewer = None
            if label is None:
                review_ref = Path(part) / 'review_calls' / name / (key + '.json')
                reviewer = rt.call(row, f.review_prompt(row, candidates, part), review_ref, part + '_review',
                                   [r['record_sha256'] for r in candidates])
                refs.append(review_ref)
            answer = reviewer or candidates[0]
            calls = [*candidates, *([reviewer] if reviewer else [])]
            value = {k: answer[k] for k in ('text', 'prediction', 'finished', 'status', 'reason_present')}
            value.update(raw_text=answer.get('raw_text', answer['text']), thinking_generated=answer.get('thinking_generated', False))
            value.update(dataset=row['dataset'], id=row['id'], method=name,
                         freeze=c.sha(f.ROOT / f.EXP / 'freeze.json'), route='review' if reviewer else 'consensus',
                         call_refs=[q.as_posix() for q in refs], call_hashes=[r['record_sha256'] for r in calls],
                         logical_calls=len(calls), input_tokens=sum(v['input_tokens'] for v in calls),
                         output_tokens=sum(v['output_tokens'] for v in calls), seconds=sum(v['seconds'] for v in calls))
            f.immutable(rt.args.output / part / 'fusion' / name / (key + '.json'), f.seal_record(value))


def select(rt):
    from .fusion_v18_training import identity
    source, seed = rt.args.source, rt.args.seed
    p = f.training_protocol(source)
    folder = rt.args.output / 'training' / source / f'seed-{seed}'
    done = c.read_json(folder / 'training_complete.json')
    if done['epochs'] != 3 or done['identity'] != identity(p, rt.env, seed):
        raise ValueError('Training completion identity mismatch')
    rows = f.data('validation')
    baseline = {c.record_key(r): f.check_record(c.read_json(rt.args.output / 'validation/direct/base_a0' / (c.record_key(r) + '.json'))) for r in rows}
    candidates = []
    for epoch in (1, 2, 3):
        entry = c.read_json(folder / f'epoch-{epoch}.json')
        ckpt = folder / entry['checkpoint']
        receipt = entry['receipt']
        if receipt['identity'] != done['identity'] or c.sha(ckpt / 'adapter_model.safetensors') != receipt['adapter_sha256'] or c.sha(ckpt / 'adapter_config.json') != receipt['adapter_config_sha256']:
            raise ValueError('Checkpoint receipt mismatch')
        rt.activate(f'{source}_{seed}_{epoch}', ckpt)
        predictions = {c.record_key(r): rt.call(r, rt.prompts['a0'],
            Path('checkpoint_validation') / source / f'seed-{seed}' / f'epoch-{epoch}' / (c.record_key(r) + '.json'),
            'checkpoint_validation') for r in rows}
        candidates.append({'epoch': epoch, 'checkpoint': ckpt.name, 'adapter_sha256': receipt['adapter_sha256'],
                           'adapter_config_sha256': receipt['adapter_config_sha256'],
                           'metrics': c.paired_metrics(rows, baseline, predictions, p)})
    f.immutable(folder / 'selection.json', {'source': source, 'seed': seed, 'identity': done['identity'],
        'selected': max(candidates, key=c.selection_key), 'candidates': candidates, 'holdout_used_for_selection': False})


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['teachers', 'direct', 'fusion', 'train', 'smoke-train', 'select'])
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--model', type=Path, default=Path('/root/ab_finetune27b_20261030/models/Qwen3.8-27B'))
    p.add_argument('--formal', type=Path, default=Path('/root/ab_finetune27b_20261030/revision_2_runs/formal'))
    p.add_argument('--worker', type=int, choices=(0, 1), default=0)
    p.add_argument('--source', choices=f.SOURCES)
    p.add_argument('--seed', type=int, choices=f.SEEDS, default=42)
    p.add_argument('--part', choices=['validation', 'evaluation'], default='validation')
    p.add_argument('--arm', default='all')
    a = p.parse_args()
    f.verify(); verify_runtime()
    import fcntl
    lockpath = a.output / 'locks' / f'{a.action}-{a.part}-{a.source}-{a.seed}-{a.worker}.lock'
    lockpath.parent.mkdir(parents=True, exist_ok=True)
    with lockpath.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if a.action in ('train', 'smoke-train'):
            from . import fusion_v18_training as training
            completed = c.read_json(f.ROOT / f.EXP / 'supervision/completion.json')
            for source, digest in completed['sources'].items():
                if c.sha(f.ROOT / f.EXP / 'supervision' / source / 'freeze.json') != digest:
                    raise ValueError('All-source review completion changed')
            cfg = f.training_protocol(a.source)
            # Token audit every reviewed row before either smoke or training.
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(a.model, local_files_only=True, trust_remote_code=False)
            lengths = [len(t['prefix']) + len(t['answer']) for r in c.rows(f.ROOT / cfg['v18_training_rows'])
                       if (t := engine.encode(r, tokenizer, cfg))]
            a.output = a.output / 'training' / a.source
            f.immutable(a.output / 'token_audit.json', {'n': len(lengths), 'max_tokens': max(lengths), 'truncated': 0,
                        'supervision_sha256': c.sha(f.ROOT / cfg['v18_training_freeze'])})
            (training.train if a.action == 'train' else training.full_smoke)(a, cfg)
        else:
            rt = Runtime(a)
            {'teachers': teachers, 'direct': direct, 'fusion': fusion, 'select': select}[a.action](rt)


if __name__ == '__main__':
    main()
