"""Single-device BF16 LoRA runner. Imported ML packages are isolated from stdlib tests."""
import argparse
from contextlib import nullcontext
import importlib.metadata
import json
import math
from pathlib import Path
import random
import time

from .finetune27b import (EXPERIMENT, ROOT, LABELS, digest, file_hash, messages,
                          parse_verdict, read_rows, report, save_json, target_text, verify)


def tokenized(row, tokenizer, protocol):
    prefix = tokenizer.apply_chat_template(messages(row, protocol['prompt']), tokenize=True,
                                          add_generation_prompt=True, enable_thinking=False)
    if not isinstance(prefix, list):
        raise TypeError('Expected list of prompt token IDs')
    answer = tokenizer.encode(target_text(row), add_special_tokens=False) + [tokenizer.eos_token_id]
    if len(prefix) + len(answer) > protocol['training']['max_sequence_length']:
        raise ValueError('No truncation allowed: ' + row['id'])
    return {'prefix': prefix, 'answer': answer, 'row': row}


def configure_ml():
    import torch
    import torch_npu  # noqa: F401; registers the NPU backend
    from transformers.models.qwen3_5 import modeling_qwen3_5 as module
    # The CPU/reference tensor formulas support autograd on NPU. Never reuse serving-only kernels.
    for name in ('causal_conv1d_fn', 'causal_conv1d_update', 'chunk_gated_delta_rule',
                 'fused_recurrent_gated_delta_rule', 'FusedRMSNormGated'):
        setattr(module, name, None)
    module.is_fast_path_available = False
    torch.set_num_threads(8)
    if not torch.npu.is_available() or torch.npu.device_count() != 1:
        raise RuntimeError('Expose exactly one allocated NPU via ASCEND_RT_VISIBLE_DEVICES')
    torch.npu.set_device(0)
    return torch, module


def load_model(model_dir, protocol, *, train):
    torch, module = configure_ml()
    from transformers import AutoTokenizer
    from peft import LoraConfig, get_peft_model
    receipt = json.loads((model_dir / 'verified_download.json').read_text())
    expected = json.loads((ROOT / EXPERIMENT / 'model_source.json').read_text())
    if receipt['model_id'] != protocol['model_id'] or receipt['files'] != expected['files'] or not receipt['all_verified']:
        raise ValueError('Unverified/wrong original model')
    for entry in expected['files']:
        if (model_dir / entry['Path']).stat().st_size != entry['Size']:
            raise ValueError('Model size changed')
    torch.manual_seed(protocol['training']['seed'])
    torch.npu.manual_seed_all(protocol['training']['seed'])
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False)
    free, total = torch.npu.mem_get_info()
    if free < 57 * 1024**3:
        raise RuntimeError(f'Insufficient free NPU memory before load: {free / 1024**3:.2f} GiB; require 57')
    print(json.dumps({'phase': 'loading_original_27b', 'free_gib': free / 1024**3}), flush=True)
    base = module.Qwen3_5ForConditionalGeneration.from_pretrained(
        model_dir, dtype=torch.bfloat16, device_map={'': 'npu:0'},
        attn_implementation='eager', local_files_only=True, trust_remote_code=False)
    config = protocol['training']
    selected = [name for name, child in base.named_modules()
                if isinstance(child, torch.nn.Linear) and '.language_model.layers.' in name
                and name.rsplit('.', 1)[-1] in config['target_modules']]
    if not selected:
        raise ValueError('No target language-model projection modules found')
    model = get_peft_model(base, LoraConfig(r=config['lora_rank'], lora_alpha=config['lora_alpha'],
                          lora_dropout=config['lora_dropout'], target_modules=selected,
                          bias='none', task_type='CAUSAL_LM'))
    if not all('lora_' in name for name, p in model.named_parameters() if p.requires_grad):
        raise ValueError('Unexpected trainable backbone parameters')
    if train:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
        model.enable_input_require_grads()
    return model, tokenizer, torch, selected


def loss_for(model, item, torch):
    prefix, answer = item['prefix'], item['answer']
    # Retain only logits that predict answer tokens. The long prompt and 248K-vocab logits
    # would otherwise unnecessarily occupy hundreds of MB; no answer token is masked away.
    ids = torch.tensor([prefix + answer[:-1]], device='npu:0', dtype=torch.long)
    output = model(input_ids=ids, attention_mask=torch.ones_like(ids), use_cache=False,
                   logits_to_keep=len(answer))
    targets = torch.tensor(answer, device='npu:0', dtype=torch.long)
    return torch.nn.functional.cross_entropy(output.logits[0].float(), targets)


def validate(model, items, torch):
    model.eval()
    sums = {'basic': 0., 'challenge': 0.}
    counts = {'basic': 0, 'challenge': 0}
    with torch.no_grad():
        for i, item in enumerate(items):
            loss = float(loss_for(model, item, torch).item())
            if not math.isfinite(loss):
                raise RuntimeError('Nonfinite validation loss')
            dataset = item['row']['dataset']
            sums[dataset] += loss
            counts[dataset] += 1
            if (i + 1) % 25 == 0:
                print(json.dumps({'phase': 'validation', 'completed': i + 1, 'total': len(items)}), flush=True)
    means = {d: sums[d] / counts[d] for d in sums if counts[d]}
    if len(means) != 2:
        raise ValueError('Both validation datasets are required')
    return {'by_dataset': means, 'selection_nll': sum(means.values()) / 2}


def model_environment(torch, model_dir, modules):
    return {'packages': {p: importlib.metadata.version(p) for p in ('torch', 'torch-npu', 'transformers', 'peft', 'accelerate')},
            'model_manifest_sha256': file_hash(ROOT / EXPERIMENT / 'model_source.json'),
            'download_receipt_sha256': file_hash(model_dir / 'verified_download.json'),
            'target_modules': modules, 'npu': torch.npu.get_device_name(0),
            'protocol_sha256': file_hash(ROOT / EXPERIMENT / 'protocol.json')}


def implementation_hashes():
    return {name: file_hash(ROOT / name) for name in (
        'src/ab_factcheck/finetune27b.py', 'src/ab_factcheck/finetune27b_runtime.py',
        'src/ab_factcheck/metrics.py', 'src/ab_factcheck/common.py', 'src/ab_factcheck/splitting.py')}


def train(args, protocol):
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file
    args.output.mkdir(parents=True, exist_ok=True)
    identity = {'protocol_sha256': file_hash(ROOT / EXPERIMENT / 'protocol.json'),
                'implementation': implementation_hashes(), 'smoke': args.action == 'smoke'}
    identity_path = args.output / 'run_identity.json'
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise ValueError('Run identity changed; use a new output directory')
    save_json(identity_path, identity)
    model, tokenizer, torch, modules = load_model(args.model, protocol, train=True)
    training = [tokenized(r, tokenizer, protocol) for r in read_rows(ROOT / EXPERIMENT / 'train.jsonl')]
    validation = [tokenized(r, tokenizer, protocol) for r in read_rows(ROOT / EXPERIMENT / 'validation.jsonl')]
    save_json(args.output / 'environment.json', model_environment(torch, args.model, modules))
    save_json(args.output / 'token_audit.json', {'max_train': max(len(x['prefix']) + len(x['answer']) for x in training),
              'max_validation': max(len(x['prefix']) + len(x['answer']) for x in validation), 'truncated': 0})
    cfg = protocol['training']
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                                  lr=cfg['learning_rate'], weight_decay=cfg['weight_decay'])
    epochs = 1 if args.action == 'smoke' else cfg['epochs']
    accum = 1 if args.action == 'smoke' else cfg['gradient_accumulation_steps']
    if args.action == 'smoke':
        # Include the longest sequence; never touch validation/test gold for smoke updates.
        training = sorted(training, key=lambda x: len(x['prefix']), reverse=True)[:2]
        validation = [next(x for x in validation if x['row']['dataset'] == d) for d in ('basic', 'challenge')]
    completed = sorted(args.output.glob('epoch-*/receipt.json'))
    start = 1
    receipts = []
    if completed:
        receipts = [json.loads(p.read_text()) for p in completed]
        latest = max(receipts, key=lambda x: x['epoch'])
        checkpoint = args.output / f"epoch-{latest['epoch']}"
        if latest['identity'] != identity or file_hash(checkpoint / 'adapter_model.safetensors') != latest['adapter_sha256']:
            raise ValueError('Checkpoint provenance mismatch')
        set_peft_model_state_dict(model, load_file(str(checkpoint / 'adapter_model.safetensors')))
        state = torch.load(checkpoint / 'optimizer_rng.pt', map_location='cpu', weights_only=False)
        optimizer.load_state_dict(state['optimizer'])
        torch.set_rng_state(state['cpu_rng'])
        torch.npu.set_rng_state(state['npu_rng'], device=0)
        start = latest['epoch'] + 1
    for epoch in range(start, epochs + 1):
        model.train()
        order = list(range(len(training)))
        random.Random(cfg['seed'] + epoch).shuffle(order)
        began = time.perf_counter()
        for step, offset in enumerate(range(0, len(order), accum), 1):
            indices = order[offset:offset + accum]
            optimizer.zero_grad(set_to_none=True)
            total_loss = 0.
            for index in indices:
                loss = loss_for(model, training[index], torch)
                if not torch.isfinite(loss).item():
                    raise RuntimeError('Nonfinite training loss')
                total_loss += float(loss.item())
                (loss / len(indices)).backward()
            norm = torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], cfg['max_grad_norm'])
            if not torch.isfinite(norm).item():
                raise RuntimeError('Nonfinite gradient')
            optimizer.step()
            event = {'epoch': epoch, 'step': step, 'examples': min(offset + accum, len(order)),
                     'loss': total_loss / len(indices), 'grad_norm': float(norm.item()),
                     'seconds': round(time.perf_counter() - began, 2),
                     'peak_gib': torch.npu.max_memory_allocated() / 1024**3}
            with (args.output / 'training.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps(event) + '\n')
            print(json.dumps(event), flush=True)
        values = validate(model, validation, torch)
        temporary = args.output / f'epoch-{epoch}.incomplete'
        temporary.mkdir(exist_ok=True)
        model.save_pretrained(temporary, safe_serialization=True)
        tokenizer.save_pretrained(temporary)
        torch.save({'optimizer': optimizer.state_dict(), 'cpu_rng': torch.get_rng_state(),
                    'npu_rng': torch.npu.get_rng_state(0)}, temporary / 'optimizer_rng.pt')
        receipt = {'epoch': epoch, 'identity': identity, **values,
                   'adapter_sha256': file_hash(temporary / 'adapter_model.safetensors')}
        save_json(temporary / 'receipt.json', receipt)
        temporary.rename(args.output / f'epoch-{epoch}')
        receipts.append(receipt)
        print(json.dumps({'phase': 'epoch_complete', **receipt}), flush=True)
    selected = min(receipts, key=lambda x: (x['selection_nll'], x['epoch']))
    path = args.output / f"epoch-{selected['epoch']}"
    set_peft_model_state_dict(model, load_file(str(path / 'adapter_model.safetensors')))
    selection = {'checkpoint': str(path.resolve()), 'receipt': selected, 'identity': identity,
                 'completed_epochs': epochs, 'test_content_read': False}
    save_json(args.output / ('smoke_selection.json' if args.action == 'smoke' else 'selection.json'), selection)
    if args.action == 'smoke':
        # Exercise real generation/cache under both arms after save/reload; these are training inputs.
        model.gradient_checkpointing_disable()
        model.eval()
        results = {}
        for arm in ('baseline', 'adapter'):
            with model.disable_adapter() if arm == 'baseline' else nullcontext():
                results[arm] = generate(model, tokenizer, training[0]['row'], protocol, torch, limit=32)
        save_json(args.output / 'smoke_generation.json', results)
    print(json.dumps({'phase': 'smoke_complete' if args.action == 'smoke' else 'training_complete',
                      'selected_epoch': selected['epoch']}), flush=True)


def generate(model, tokenizer, row, protocol, torch, limit=None):
    ids = tokenizer.apply_chat_template(messages(row, protocol['prompt']), tokenize=True,
                                        add_generation_prompt=True, enable_thinking=False)
    tensor = torch.tensor([ids], device='npu:0', dtype=torch.long)
    began = time.perf_counter()
    with torch.no_grad():
        result = model.generate(input_ids=tensor, attention_mask=torch.ones_like(tensor),
            do_sample=False, max_new_tokens=limit or protocol['generation']['max_new_tokens'],
            use_cache=True, pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
    new_ids = result[0, len(ids):].tolist()
    eos = model.generation_config.eos_token_id
    eos_ids = set(eos if isinstance(eos, list) else [eos])
    finished = bool(new_ids and new_ids[-1] in eos_ids)
    text = tokenizer.decode(new_ids, skip_special_tokens=True)
    return {'prediction': parse_verdict(text, finished), 'text': text, 'finished': finished,
            'seconds': time.perf_counter() - began, 'input_tokens': len(ids), 'output_tokens': len(new_ids)}


def evaluate(args, protocol):
    from safetensors.torch import load_file
    from peft import set_peft_model_state_dict
    selection = json.loads((args.output / 'selection.json').read_text())
    identity = {'protocol_sha256': file_hash(ROOT / EXPERIMENT / 'protocol.json'),
                'implementation': implementation_hashes(), 'smoke': False}
    if selection['identity'] != identity or selection['completed_epochs'] != protocol['training']['epochs']:
        raise ValueError('Final checkpoint not selected under this frozen implementation')
    checkpoint = Path(selection['checkpoint'])
    if file_hash(checkpoint / 'adapter_model.safetensors') != selection['receipt']['adapter_sha256']:
        raise ValueError('Selected adapter changed')
    # This is the sole test-content entry point, reached after successful selection checks.
    rows = []
    for dataset in ('basic', 'challenge'):
        source = ROOT / f'data/splits/v1/{dataset}/test.jsonl'
        rows += [dict(r, dataset=dataset) for r in read_rows(source)]
    train_groups = {(r['dataset'], r['group']) for p in ('train', 'validation')
                    for r in read_rows(ROOT / EXPERIMENT / (p + '.jsonl'))}
    if train_groups & {(r['dataset'], r['group']) for r in rows}:
        raise ValueError('Test group leakage')
    rows.sort(key=lambda r: digest([42, r['dataset'], r['id']]))
    eval_identity = {'run': identity, 'selection_sha256': file_hash(args.output / 'selection.json'),
                     'test_rows_sha256': digest(rows), 'n': len(rows)}
    path = args.output / 'evaluation_identity.json'
    if path.exists() and json.loads(path.read_text()) != eval_identity:
        raise ValueError('Evaluation identity changed')
    save_json(path, eval_identity)
    record_dir = args.output / 'paired'
    record_dir.mkdir(exist_ok=True)
    model, tokenizer, torch, _ = load_model(args.model, protocol, train=False)
    set_peft_model_state_dict(model, load_file(str(checkpoint / 'adapter_model.safetensors')))
    model.eval()
    for i, row in enumerate(rows):
        target = record_dir / f"{row['dataset']}_{row['id']}.json"
        record = json.loads(target.read_text()) if target.exists() else {
            **row, 'input_sha256': digest(messages(row, protocol['prompt'])), 'identity': digest(eval_identity)}
        if record['identity'] != digest(eval_identity) or record['input_sha256'] != digest(messages(row, protocol['prompt'])):
            raise ValueError('Existing paired record mismatch')
        for arm in (('baseline', 'adapter') if i % 2 == 0 else ('adapter', 'baseline')):
            if arm in record:
                continue
            # Persist each received result; do not regenerate invalid answers.
            with model.disable_adapter() if arm == 'baseline' else nullcontext():
                record[arm] = generate(model, tokenizer, row, protocol, torch)
            save_json(target, record)
        print(json.dumps({'phase': 'paired_evaluation', 'completed': i + 1, 'total': len(rows)}), flush=True)
    records = [json.loads((record_dir / f"{r['dataset']}_{r['id']}.json").read_text()) for r in rows]
    results = report(records, protocol)
    results['identity'] = eval_identity
    save_json(args.output / 'results.json', results)
    print(json.dumps({'phase': 'evaluation_complete', 'primary_pass': results['primary_pass']}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['smoke', 'train', 'evaluate'])
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    protocol = verify()
    if args.action == 'evaluate':
        evaluate(args, protocol)
    else:
        train(args, protocol)


if __name__ == '__main__':
    main()
