"""Execution entry points for the reviewed, development-only revision."""
import argparse
from contextlib import nullcontext
import json
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


def infer_rows(model, tokenizer, data, p, torch, device, destination, identity, arm='baseline', limit=None):
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
        else:
            with model.disable_adapter() if arm == 'baseline' else nullcontext():
                result = engine.generate(model, tokenizer, row, p, torch, device)
            result.update(identity=core.digest(identity), dataset=row['dataset'], id=row['id'])
            core.save(path, result)
        predictions[key] = result
        emit(phase='generation', arm=arm, completed=i+1, total=len(data), seconds=result['seconds'])
        if limit and i+1 >= limit:
            break
    return predictions


def draft(args, p):
    data = core.rows(core.ROOT / core.EXP / 'train.jsonl')
    model, tokenizer, torch, device, env = engine.load(args.model, p)
    identity = {'data_freeze_sha256': core.sha(core.ROOT / core.EXP / 'data_freeze.json'),
                'environment': env, 'generation': p['generation'], 'phase': 'training_rationale_drafts'}
    core.save(args.output / 'environment.json', env)
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
    parser.add_argument('action', choices=['draft', 'probe'])
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    p = core.verify_data()
    (draft if args.action == 'draft' else probe)(args, p)


if __name__ == '__main__':
    main()
