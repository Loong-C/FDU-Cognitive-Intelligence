"""Resumable rationale SFT, with optional two-device FULL_SHARD."""
from contextlib import nullcontext
import json
import math
import os
from pathlib import Path
import random
import re
import time

from . import finetune27b_v2 as core
from . import finetune27b_engine as engine


def identity(p, environment, seed):
    directory = Path(__file__).parent
    return {'seed': seed, 'training_freeze_sha256': core.sha(core.ROOT / core.EXP / 'training_freeze.json'),
            'environment': environment, 'code': {n: core.sha(directory / n) for n in
                ('finetune27b_v2.py', 'finetune27b_engine.py', 'finetune27b_training_v2.py', 'finetune27b_run_v2.py')},
            'protocol_sha256': core.digest(p)}


def wrap_fsdp(model, torch, device):
    from torch.distributed.fsdp import FullyShardedDataParallel as FSDP, ShardingStrategy, MixedPrecision
    from torch.distributed.fsdp.wrap import transformer_auto_wrap_policy, lambda_auto_wrap_policy, _or_policy
    from functools import partial
    from transformers.models.qwen3_5.modeling_qwen3_5 import Qwen3_5DecoderLayer
    # LoRA master parameters are FP32, frozen backbone parameters BF16. Wrapping
    # trainable leaves separately avoids placing mixed dtypes in one flat buffer.
    leaf = partial(lambda_auto_wrap_policy, lambda_fn=lambda m:
        not list(m.children()) and getattr(m, 'weight', None) is not None and m.weight.requires_grad)
    layer = partial(transformer_auto_wrap_policy, transformer_layer_cls={Qwen3_5DecoderLayer})
    return FSDP(model, sharding_strategy=ShardingStrategy.FULL_SHARD,
        auto_wrap_policy=partial(_or_policy, policies=[leaf, layer]),
        use_orig_params=True, device_id=torch.device(device),
        mixed_precision=MixedPrecision(param_dtype=torch.bfloat16, reduce_dtype=torch.float32, buffer_dtype=torch.bfloat16),
        limit_all_gathers=True, sync_module_states=True)


def recover_latest(directory, provenance):
    """Adopt a durable checkpoint if interruption preceded latest.json publication."""
    candidates = []
    for folder in directory.glob('checkpoint-e*-c*'):
        if not folder.is_dir() or not re.fullmatch(r'checkpoint-e\d+-c\d+', folder.name):
            continue
        receipt = core.read_json(folder/'receipt.json')
        if (receipt['identity'] != provenance
                or core.sha(folder/'adapter_model.safetensors') != receipt['adapter_sha256']
                or core.sha(folder/'adapter_config.json') != receipt['adapter_config_sha256']
                or core.sha(folder/'optimizer_rng.pt') != receipt['optimizer_sha256']):
            raise ValueError('Completed checkpoint provenance mismatch')
        candidates.append((receipt['epoch'], receipt['cursor'], folder, receipt))
    if not candidates:
        if (directory/'latest.json').exists():
            raise ValueError('Latest checkpoint is missing')
        return None
    _, _, folder, receipt = max(candidates, key=lambda v: v[:2])
    return {'checkpoint': folder.name, 'receipt': receipt}


def checkpoint(model, raw, optimizer, torch, directory, provenance, epoch, cursor, world, rank):
    from peft import get_peft_model_state_dict
    from safetensors.torch import save_file
    rng = {'cpu': torch.get_rng_state(), 'npu': torch.npu.get_rng_state(rank), 'python': random.getstate()}
    if world > 1:
        from torch.distributed.fsdp import FullyShardedDataParallel as FSDP, StateDictType, FullStateDictConfig, FullOptimStateDictConfig
        rngs = [None] * world
        torch.distributed.all_gather_object(rngs, rng)
        with FSDP.state_dict_type(model, StateDictType.FULL_STATE_DICT,
                FullStateDictConfig(offload_to_cpu=True, rank0_only=True),
                FullOptimStateDictConfig(offload_to_cpu=True, rank0_only=True)):
            full = model.state_dict()
            optim = FSDP.optim_state_dict(model, optimizer)
        state = get_peft_model_state_dict(raw, state_dict=full) if rank == 0 else None
    else:
        rngs, optim = [rng], optimizer.state_dict()
        state = get_peft_model_state_dict(raw)
    if rank == 0:
        if directory.exists():
            raise ValueError('Refuse overwriting a completed checkpoint')
        temp = directory.with_name(directory.name + '.incomplete')
        temp.mkdir(parents=True, exist_ok=True)
        save_file({k: v.detach().cpu().contiguous().clone() for k, v in state.items()}, str(temp / 'adapter_model.safetensors'))
        raw.peft_config['default'].save_pretrained(temp)
        torch.save({'optimizer': optim, 'rngs': rngs, 'epoch': epoch, 'cursor': cursor}, temp / 'optimizer_rng.pt')
        receipt = {'identity': provenance, 'epoch': epoch, 'cursor': cursor,
                   'adapter_sha256': core.sha(temp / 'adapter_model.safetensors'),
                   'adapter_config_sha256': core.sha(temp / 'adapter_config.json'),
                   'optimizer_sha256': core.sha(temp / 'optimizer_rng.pt')}
        core.save(temp / 'receipt.json', receipt)
        temp.rename(directory)
        core.save(directory.parent / 'latest.json', {'checkpoint': directory.name, 'receipt': receipt})
    if world > 1:
        torch.distributed.barrier()


def train(args, p):
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file
    if args.seed not in core.SEEDS:
        raise ValueError('Only the three frozen seeds are permitted')
    world = int(os.environ.get('WORLD_SIZE', '1'))
    rank = int(os.environ.get('RANK', '0'))
    if world != p['training']['world_size']:
        raise ValueError('Training device count differs from freeze')
    torch, _, device = engine.configure()
    if world > 1:
        torch.distributed.init_process_group('hccl')
    model, tokenizer, torch, device, env = engine.load(args.model, p, seed=args.seed, cpu=world > 1)
    if env != core.read_json(args.output/'smoke/receipt.json')['environment']:
        raise ValueError('Full-model smoke environment differs from training')
    provenance = identity(p, env, args.seed)
    output = args.output / f'seed-{args.seed}'
    output.mkdir(parents=True, exist_ok=True)
    ipath = output / 'identity.json'
    if ipath.exists() and core.read_json(ipath) != provenance:
        raise ValueError('Training implementation/environment changed')
    if rank == 0:
        core.save(ipath, provenance)
    raw = model
    data = [engine.encode(r, tokenizer, p) for r in core.rows(core.ROOT / core.EXP / 'reviewed_train.jsonl')]
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.enable_input_require_grads()
    resumed = None
    receipt = recover_latest(output, provenance)
    if receipt:
        if rank == 0:
            core.save(output/'latest.json', receipt)
        folder = output / receipt['checkpoint']
        r = receipt['receipt']
        if r['identity'] != provenance or core.sha(folder / 'adapter_model.safetensors') != r['adapter_sha256'] or core.sha(folder / 'optimizer_rng.pt') != r['optimizer_sha256']:
            raise ValueError('Checkpoint provenance mismatch')
        set_peft_model_state_dict(raw, load_file(str(folder / 'adapter_model.safetensors')))
        resumed = torch.load(folder / 'optimizer_rng.pt', map_location='cpu', weights_only=False)
        if (resumed['epoch'], resumed['cursor']) != (r['epoch'], r['cursor']):
            raise ValueError('Checkpoint data cursor mismatch')
    if world > 1:
        model = wrap_fsdp(model, torch, device)
    cfg = p['training']
    optimizer = torch.optim.AdamW([v for v in model.parameters() if v.requires_grad],
                                 lr=cfg['learning_rate'], weight_decay=cfg['weight_decay'])
    start_epoch, start_cursor = 1, 0
    if resumed:
        optim = resumed['optimizer']
        if world > 1:
            from torch.distributed.fsdp import FullyShardedDataParallel as FSDP
            optim = FSDP.optim_state_dict_to_load(model, optimizer, optim)
        optimizer.load_state_dict(optim)
        rng = resumed['rngs'][rank]
        torch.set_rng_state(rng['cpu']); torch.npu.set_rng_state(rng['npu'], device=rank)
        random.setstate(rng['python'])
        start_epoch, start_cursor = resumed['epoch'], resumed['cursor']
        if start_cursor >= len(data):
            if rank == 0 and not (output / f'epoch-{start_epoch}.json').exists():
                core.save(output / f'epoch-{start_epoch}.json', {'checkpoint': folder.name,
                    'epoch': start_epoch, 'receipt': r})
            start_epoch, start_cursor = start_epoch + 1, 0
    for epoch in range(start_epoch, cfg['epochs'] + 1):
        model.train()
        order = list(range(len(data)))
        random.Random(args.seed + epoch).shuffle(order)
        cursor = start_cursor if epoch == start_epoch else 0
        for offset in range(cursor, len(data), 16):
            indices = order[offset:offset+16]
            optimizer.zero_grad(set_to_none=True)
            loss_sum = 0.
            begun = time.perf_counter()
            for j in range(math.ceil(len(indices)/world)):
                position = j*world + rank
                valid = position < len(indices)
                item = data[indices[position if valid else 0]]
                loss = engine.loss(model, item, torch, device)
                if not torch.isfinite(loss).item():
                    raise RuntimeError('Nonfinite training loss')
                (loss * (world/len(indices) if valid else 0.)).backward()
                loss_sum += loss.item() if valid else 0.
            norm = model.clip_grad_norm_(cfg['max_grad_norm']) if world > 1 else torch.nn.utils.clip_grad_norm_(
                [v for v in model.parameters() if v.requires_grad], cfg['max_grad_norm'])
            if not torch.isfinite(norm).item():
                raise RuntimeError('Nonfinite gradient')
            optimizer.step()
            if world > 1:
                total = torch.tensor(loss_sum, device=device)
                torch.distributed.all_reduce(total)
                loss_sum = total.item()
            next_cursor = offset + len(indices)
            if rank == 0:
                event = {'epoch': epoch, 'cursor': next_cursor, 'loss': loss_sum/len(indices),
                         'grad_norm': norm.item(), 'seconds': time.perf_counter()-begun,
                         'peak_gib': torch.npu.max_memory_allocated()/1024**3}
                core.save(output / 'steps' / f'e{epoch:02d}-c{next_cursor:05d}.json', event)
                print(json.dumps(event), flush=True)
            # At most seven completed updates are replayed after an interrupted process.
            if (offset//16+1) % 8 == 0 or next_cursor == len(data):
                folder = output / f'checkpoint-e{epoch:02d}-c{next_cursor:05d}'
                checkpoint(model, raw, optimizer, torch, folder, provenance, epoch, next_cursor, world, rank)
                if next_cursor == len(data) and rank == 0:
                    core.save(output / f'epoch-{epoch}.json', {'checkpoint': folder.name, 'epoch': epoch,
                        'receipt': core.read_json(folder / 'receipt.json')})
    if rank == 0:
        core.save(output / 'training_complete.json', {'identity': provenance, 'epochs': cfg['epochs']})
    if world > 1:
        torch.distributed.destroy_process_group()
