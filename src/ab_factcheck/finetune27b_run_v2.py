"""Execution entry points for the reviewed, development-only revision."""
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import random
import time

from . import finetune27b_v2 as core
from . import finetune27b_engine as engine


def emit(**value):
    print(json.dumps(value), flush=True)


def immutable(path, value):
    if path.exists():
        if core.read_json(path) != value:
            raise ValueError('Run identity changed: ' + str(path))
    else:
        core.save(path, value)


def infer_rows(model, tokenizer, data, p, torch, device, destination, identity, arm='baseline', limit=None, require_existing=False):
    destination.mkdir(parents=True, exist_ok=True)
    immutable(destination / 'identity.json', identity)
    predictions = {}
    for i, row in enumerate(data):
        key = core.record_key(row)
        path = destination / (key + '.json')
        if path.exists():
            result = core.read_json(path)
            if result['identity'] != core.digest(identity) or result['input_sha256'] != core.digest(core.messages(row, p['prompt'])):
                raise ValueError('Received result has wrong identity')
            expected = 'INVALID' if result.get('thinking_generated') else core.parse(result['text'], result['finished'])
            if result['prediction'] != expected:
                raise ValueError('Received result disagrees with strict parsing')
        else:
            if require_existing:
                raise ValueError('Complete cached baseline validation is required before selecting any seed')
            begun = time.perf_counter()
            try:
                with model.disable_adapter() if arm == 'baseline' else nullcontext():
                    result = engine.generate(model, tokenizer, row, p, torch, device)
            except Exception as error:
                # Preserve the failed unit before stopping; resume never retries its answer.
                result = {'text': '', 'prediction': 'INVALID', 'finished': False,
                          'status': 'request_failed', 'reason_present': False,
                          'input_sha256': core.digest(core.messages(row, p['prompt'])),
                          'seconds': time.perf_counter()-begun, 'error': type(error).__name__ + ': ' + str(error),
                          'identity': core.digest(identity), 'dataset': row['dataset'], 'id': row['id']}
                try:
                    prefix = engine.encode(row, tokenizer, p, require_target=False, enforce_limit=False)['prefix']
                    result.update(input_tokens=len(prefix), input_token_sha256=core.digest(prefix))
                except Exception:
                    pass  # A tokenizer failure has no valid token sequence to report.
                core.save(path, result)
                raise
            result.update(identity=core.digest(identity), dataset=row['dataset'], id=row['id'])
            core.save(path, result)
        predictions[key] = result
        emit(phase='generation', arm=arm, completed=i+1, total=len(data), seconds=result['seconds'])
        if limit and i+1 >= limit:
            break
    return predictions


def token_audit(args, p):
    from transformers import AutoTokenizer
    data, excluded = core.validate_reviews(core.rows(args.reviews), args.drafts)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, trust_remote_code=False)
    lengths = [len(t['prefix']) + len(t['answer']) for r in data
               if (t := engine.encode(r, tokenizer, p, enforce_limit=False))]
    audit = {'max_tokens': max(lengths), 'truncated': 0, 'world_size': args.world_size,
             'data_freeze_sha256': core.sha(core.ROOT / core.EXP / 'data_freeze.json'),
             'reviews_sha256': core.sha(args.reviews), 'rows': len(data), 'excluded_groups': excluded,
             'model_identity': engine.model_identity(args.model, p)}
    core.save(args.output / 'token_audit.json', audit)
    emit(phase='token_audit', **audit)


def full_smoke(args, p):
    if p['training']['world_size'] != 1 or int(os.environ.get('WORLD_SIZE', '1')) != 1:
        raise ValueError('Single-device smoke cannot certify a FULL_SHARD execution; run its distributed acceptance before training')
    from peft import get_peft_model_state_dict, set_peft_model_state_dict
    from safetensors.torch import load_file
    model, tokenizer, torch, device, env = engine.load(args.model, p)
    data = [engine.encode(r, tokenizer, p) for r in core.rows(core.ROOT / core.EXP / 'reviewed_train.jsonl')]
    chosen = {max(range(len(data)), key=lambda i: len(data[i]['prefix']) + len(data[i]['answer']))}
    for label in core.LABELS:
        chosen.add(next(i for i, t in enumerate(data) if t['row']['label'] == label))
    destination = args.output / 'smoke'
    destination.mkdir(parents=True, exist_ok=True)
    initial = {k: v.detach().cpu().clone() for k, v in get_peft_model_state_dict(model).items()}
    sample = data[min(chosen)]
    ids = torch.tensor([sample['prefix']], device=device, dtype=torch.long)
    def logits(disabled):
        model.eval()
        with torch.no_grad(), model.disable_adapter() if disabled else nullcontext():
            return model(input_ids=ids, attention_mask=torch.ones_like(ids), logits_to_keep=1,
                         use_cache=False).logits.float().cpu()
    before = logits(True)
    torch.testing.assert_close(before, logits(False), atol=0, rtol=0)
    with model.disable_adapter():
        baseline = engine.generate(model, tokenizer, sample['row'], p, torch, device)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.enable_input_require_grads()
    optimizer = torch.optim.AdamW([v for v in model.parameters() if v.requires_grad],
                                 lr=p['training']['learning_rate'], weight_decay=0.)
    losses = []
    for i in sorted(chosen):
        optimizer.zero_grad(set_to_none=True)
        model.train()
        value = engine.loss(model, data[i], torch, device)
        value.backward()
        nonzero = sum(int(v.grad is not None and v.grad.abs().sum().item() > 0)
                      for v in model.parameters() if v.requires_grad)
        if not torch.isfinite(value).item() or not nonzero:
            raise RuntimeError('Smoke gradient failure')
        torch.nn.utils.clip_grad_norm_([v for v in model.parameters() if v.requires_grad], 1.)
        optimizer.step()
        losses.append(value.item())
        emit(phase='smoke_backward', id=data[i]['row']['id'], loss=value.item())
    torch.testing.assert_close(before, logits(True), atol=0, rtol=0)
    updated = get_peft_model_state_dict(model)
    if not any(not torch.equal(initial[k], v.detach().cpu()) for k, v in updated.items()):
        raise RuntimeError('No adapter parameters changed')
    trained_logits = logits(False)
    model.save_pretrained(destination / 'adapter', safe_serialization=True)
    set_peft_model_state_dict(model, initial)
    set_peft_model_state_dict(model, load_file(str(destination / 'adapter/adapter_model.safetensors')))
    torch.testing.assert_close(trained_logits, logits(False), atol=0, rtol=0)
    # Exercise an interrupted optimizer update, including dropout RNG, on the actual 27B.
    state_path = destination / 'optimizer_rng.pt'
    torch.save({'optimizer': optimizer.state_dict(), 'cpu_rng': torch.get_rng_state(),
                'npu_rng': torch.npu.get_rng_state(0), 'python_rng': random.getstate()}, state_path)
    def extra_step():
        model.train()
        optimizer.zero_grad(set_to_none=True)
        v = engine.loss(model, sample, torch, device)
        v.backward()
        torch.nn.utils.clip_grad_norm_([x for x in model.parameters() if x.requires_grad], 1.)
        optimizer.step()
    extra_step()
    uninterrupted = {k: v.detach().cpu().clone() for k, v in get_peft_model_state_dict(model).items()}
    set_peft_model_state_dict(model, load_file(str(destination/'adapter/adapter_model.safetensors')))
    restored_state = torch.load(state_path, map_location='cpu', weights_only=False)
    optimizer.load_state_dict(restored_state['optimizer'])
    torch.set_rng_state(restored_state['cpu_rng']); torch.npu.set_rng_state(restored_state['npu_rng'], device=0)
    random.setstate(restored_state['python_rng'])
    extra_step()
    for key, value in get_peft_model_state_dict(model).items():
        torch.testing.assert_close(uninterrupted[key], value.detach().cpu(), atol=1e-6, rtol=1e-5)
    model.gradient_checkpointing_disable()
    model.eval()
    with model.disable_adapter():
        restored = engine.generate(model, tokenizer, sample['row'], p, torch, device)
    if baseline['text'] != restored['text']:
        raise RuntimeError('Disabling adapter changed baseline generation')
    from .finetune27b_training_v2 import identity
    receipt = {'passed': True, 'full_27b': True, 'environment': env, 'code_identity': identity(p, env, 42),
               'training_freeze_sha256': core.sha(core.ROOT / core.EXP / 'training_freeze.json'),
               'ids': [data[i]['row']['id'] for i in sorted(chosen)], 'losses': losses,
               'peak_gib': torch.npu.max_memory_allocated()/1024**3,
               'max_sequence_tested': max(len(data[i]['prefix'])+len(data[i]['answer']) for i in chosen),
               'zero_adapter_equals_baseline': True, 'disabled_adapter_restores_baseline': True,
               'adapter_save_reload_equal': True, 'backbone_trainable_parameters': 0,
               'optimizer_rng_resume_equal': True,
               'formal_training': False}
    core.save(destination / 'receipt.json', receipt)
    emit(phase='full_smoke_passed', peak_gib=receipt['peak_gib'])


def validate_baseline(args, p):
    model, tokenizer, torch, device, env = engine.load(args.model, p)
    data = core.rows(core.ROOT / core.EXP / 'validation.jsonl')
    common = {'training_freeze_sha256': core.sha(core.ROOT / core.EXP / 'training_freeze.json'),
              'environment': env, 'generation': p['generation'], 'phase': 'validation'}
    infer_rows(model, tokenizer, data, p, torch, device, args.output/'validation/baseline', common)


def select(args, p):
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file
    from .finetune27b_training_v2 import identity
    output = args.output / f'seed-{args.seed}'
    completed = core.read_json(output / 'training_complete.json')
    if completed['epochs'] != 3:
        raise ValueError('Incomplete training')
    model, tokenizer, torch, device, env = engine.load(args.model, p, seed=args.seed)
    if completed['identity'] != identity(p, env, args.seed):
        raise ValueError('Training/inference provenance differs')
    data = core.rows(core.ROOT / core.EXP / 'validation.jsonl')
    common = {'training_freeze_sha256': core.sha(core.ROOT / core.EXP / 'training_freeze.json'),
              'environment': env, 'generation': p['generation'], 'phase': 'validation'}
    base = infer_rows(model, tokenizer, data, p, torch, device, args.output / 'validation/baseline', common,
                      require_existing=True)
    candidates = []
    for epoch in (1, 2, 3):
        entry = core.read_json(output / f'epoch-{epoch}.json')
        folder = output / entry['checkpoint']
        if entry['receipt']['identity'] != completed['identity'] or core.sha(folder / 'adapter_model.safetensors') != entry['receipt']['adapter_sha256']:
            raise ValueError('Epoch checkpoint changed')
        if core.sha(folder/'adapter_config.json') != entry['receipt']['adapter_config_sha256']:
            raise ValueError('Epoch adapter configuration changed')
        set_peft_model_state_dict(model, load_file(str(folder / 'adapter_model.safetensors')))
        model.eval()
        receipt = {**common, 'seed': args.seed, 'epoch': epoch, 'adapter_sha256': entry['receipt']['adapter_sha256']}
        pred = infer_rows(model, tokenizer, data, p, torch, device,
                         args.output / f'validation/seed-{args.seed}/epoch-{epoch}', receipt, arm='adapter')
        for key in pred:
            if pred[key].get('input_token_sha256') and base[key].get('input_token_sha256') and pred[key]['input_token_sha256'] != base[key]['input_token_sha256']:
                raise ValueError('Paired token inputs differ')
        candidates.append({'epoch': epoch, 'checkpoint': entry['checkpoint'],
                           'adapter_sha256': entry['receipt']['adapter_sha256'],
                           'adapter_config_sha256': entry['receipt']['adapter_config_sha256'],
                           'metrics': core.paired_metrics(data, base, pred, p)})
    selected = max(candidates, key=core.selection_key)
    value = {'identity': completed['identity'], 'seed': args.seed, 'selected': selected,
             'candidates': candidates, 'holdout_used_for_selection': False}
    immutable(output / 'selection.json', value)
    emit(phase='selection_complete', seed=args.seed, epoch=selected['epoch'],
         guardrails_pass=selected['metrics']['guardrails_pass'])


def evaluate(args, p):
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file
    from .finetune27b_training_v2 import identity
    selections = {s: core.read_json(args.output / f'seed-{s}/selection.json') for s in core.SEEDS}
    model, tokenizer, torch, device, env = engine.load(args.model, p)
    adapters = {}
    for seed, selection in selections.items():
        if selection['identity'] != identity(p, env, seed) or selection['holdout_used_for_selection']:
            raise ValueError('Selection identity mismatch')
        folder = args.output / f'seed-{seed}' / selection['selected']['checkpoint']
        if core.sha(folder / 'adapter_model.safetensors') != selection['selected']['adapter_sha256']:
            raise ValueError('Selected adapter changed')
        if core.sha(folder/'adapter_config.json') != selection['selected']['adapter_config_sha256']:
            raise ValueError('Selected adapter configuration changed')
        adapters[str(seed)] = load_file(str(folder / 'adapter_model.safetensors'))
    # No holdout input is read before ALL three selections have passed the checks above.
    if core.verify_training() != p:
        raise ValueError('Frozen protocol changed during evaluation preflight')
    data = core.rows(core.ROOT / core.EXP / 'holdout.jsonl')
    data.sort(key=lambda r: core.digest([42, r['dataset'], r['id']]))
    ident = {'environment': env, 'generation': p['generation'], 'phase': 'development_holdout',
             'training_freeze_sha256': core.sha(core.ROOT / core.EXP / 'training_freeze.json'),
             'selections': {str(s): core.sha(args.output / f'seed-{s}/selection.json') for s in core.SEEDS}}
    folder = args.output / 'holdout'
    immutable(folder / 'identity.json', ident)
    arms = ['baseline', *map(str, core.SEEDS)]
    predictions = {arm: {} for arm in arms}
    for i, row in enumerate(data):
        order = arms[i % 4:] + arms[:i % 4]
        for arm in order:
            if arm != 'baseline':
                set_peft_model_state_dict(model, adapters[arm])
            model.eval()
            result = infer_rows(model, tokenizer, [row], p, torch, device, folder / arm,
                {**ident, 'arm': arm}, arm='baseline' if arm == 'baseline' else 'adapter')
            predictions[arm].update(result)
        values = [predictions[a][core.record_key(row)].get('input_token_sha256') for a in arms]
        if len(set(v for v in values if v is not None)) > 1:
            raise ValueError('Holdout input token mismatch')
        emit(phase='holdout', completed=i+1, total=len(data))
    result = core.final_report(data, predictions['baseline'], {s: predictions[s] for s in map(str, core.SEEDS)}, p)
    result['identity'] = ident
    core.save(args.output / 'results.json', result)
    emit(phase='evaluation_complete', primary_pass=result['primary_pass'])


def draft(args, p):
    data = core.rows(core.ROOT / core.EXP / 'train.jsonl')
    if not 0 <= args.shard_index < args.shard_count:
        raise ValueError('Invalid draft shard')
    data = [r for i, r in enumerate(data) if i % args.shard_count == args.shard_index]
    model, tokenizer, torch, device, env = engine.load(args.model, p)
    identity = {'data_freeze_sha256': core.sha(core.ROOT / core.EXP / 'data_freeze.json'),
                'environment': env, 'generation': p['generation'], 'phase': 'training_rationale_drafts'}
    core.save(args.output / f'environment-{args.shard_index}.json', env)
    infer_rows(model, tokenizer, data, p, torch, device, args.output / 'drafts', identity, limit=args.limit)


def probe(args, p):
    """True 27B inference and backward diagnostic, never a formal training run."""
    data = core.rows(core.ROOT / core.EXP / 'train.jsonl')
    model, tokenizer, torch, device, env = engine.load(args.model, p)
    args.output.mkdir(parents=True, exist_ok=True)
    core.save(args.output / 'environment.json', env)
    emit(phase='full_27b_loaded', allocated_gib=torch.npu.memory_allocated()/1024**3)
    # A real baseline continuation is required before any disposable diagnostic update.
    first = data[0]
    with model.disable_adapter():
        result = engine.generate(model, tokenizer, first, p, torch, device)
    core.save(args.output / 'baseline_generation.json', result)
    if result['prediction'] == 'INVALID':
        raise RuntimeError('Full 27B baseline generation is invalid')
    rationale = result['text'].rsplit('Verdict:', 1)[0].strip()
    if not rationale:
        raise RuntimeError('Baseline supplied no diagnostic rationale')
    diagnostic = dict(first, rationale=rationale, label=result['prediction'])
    item = engine.encode(diagnostic, tokenizer, p)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.enable_input_require_grads()
    model.train()
    optimizer = torch.optim.AdamW([v for v in model.parameters() if v.requires_grad], lr=1e-4)
    value = engine.loss(model, item, torch, device)
    value.backward()
    grads = sum(int(v.grad is not None and v.grad.abs().sum().item() > 0) for v in model.parameters() if v.requires_grad)
    if not torch.isfinite(value).item() or not grads:
        raise RuntimeError('Nonfinite loss or missing adapter gradient')
    optimizer.step()
    core.save(args.output / 'probe.json', {'full_27b_backward_pass': True, 'loss': value.item(),
        'nonzero_gradients': grads, 'peak_gib': torch.npu.max_memory_allocated()/1024**3,
        'disposable_update': True, 'not_formal_training': True})
    emit(phase='full_27b_probe_passed', peak_gib=torch.npu.max_memory_allocated()/1024**3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['draft', 'probe', 'audit-tokens', 'smoke', 'train', 'validate-baseline', 'select', 'evaluate'])
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--seed', type=int, choices=core.SEEDS, default=42)
    parser.add_argument('--reviews', type=Path)
    parser.add_argument('--drafts', type=Path)
    parser.add_argument('--world-size', type=int, choices=[1, 2], default=1)
    parser.add_argument('--shard-count', type=int, default=1)
    parser.add_argument('--shard-index', type=int, default=0)
    args = parser.parse_args()
    if args.action == 'evaluate':
        # Full partition auditing itself reads holdout records, so defer it to evaluate's gate.
        p = core.read_json(core.ROOT / core.EXP / 'training_protocol.json')
    else:
        p = core.verify_data() if args.action in ('draft', 'probe', 'audit-tokens') else core.verify_training()
    if args.action == 'train':
        from .finetune27b_training_v2 import train, identity
        smoke = core.read_json(args.output / 'smoke/receipt.json')
        if (not smoke['passed']
                or smoke['code_identity'] != identity(p, smoke['environment'], 42)
                or smoke['training_freeze_sha256'] != core.sha(core.ROOT / core.EXP / 'training_freeze.json')):
            raise ValueError('Matching full-model smoke required')
        train(args, p)
    else:
        functions = {'draft': draft, 'probe': probe, 'audit-tokens': token_audit,
                     'smoke': full_smoke, 'validate-baseline': validate_baseline, 'select': select, 'evaluate': evaluate}
        functions[args.action](args, p)


if __name__ == '__main__':
    main()
