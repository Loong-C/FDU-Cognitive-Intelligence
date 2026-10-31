"""Shared BF16 inference/training math for both controlled experimental arms."""
import importlib.metadata
import os
import platform
from pathlib import Path
import time

from .finetune27b_v2 import (ROOT, EXP, digest, messages, parse, has_reason,
                            read_json, sha, target)


def configure():
    import torch
    import torch_npu  # noqa: F401
    from transformers.models.qwen3_5 import modeling_qwen3_5 as module
    for name in ('causal_conv1d_fn', 'causal_conv1d_update', 'chunk_gated_delta_rule',
                 'fused_recurrent_gated_delta_rule', 'FusedRMSNormGated'):
        setattr(module, name, None)
    module.is_fast_path_available = False
    torch.set_num_threads(8)
    rank = int(os.environ.get('LOCAL_RANK', '0'))
    if not torch.npu.is_available():
        raise RuntimeError('Ascend NPU unavailable')
    torch.npu.set_device(rank)
    return torch, module, f'npu:{rank}'


def model_identity(model_dir, p, root=ROOT):
    expected = read_json(root / p['model_manifest'])
    receipt = read_json(model_dir / 'verified_download.json')
    if receipt['model_id'] != p['model_id'] or receipt['files'] != expected['files'] or not receipt['all_verified']:
        raise ValueError('Wrong or incomplete original model')
    for entry in expected['files']:
        if (model_dir / entry['Path']).stat().st_size != entry['Size']:
            raise ValueError('Checkpoint size mismatch')
    return {'model_manifest_sha256': sha(root / p['model_manifest']),
            'download_receipt_sha256': sha(model_dir / 'verified_download.json'),
            'packages': {n: importlib.metadata.version(n) for n in ('torch', 'torch-npu', 'transformers', 'peft', 'accelerate',
                'numpy', 'safetensors', 'tokenizers', 'huggingface-hub')},
            'python': platform.python_version(), 'platform': platform.platform(),
            'compute_environment': {key:os.environ.get(key) for key in (
                'ASCEND_LAUNCH_BLOCKING', 'NPU_ASD_ENABLE', 'PYTORCH_NPU_ALLOC_CONF',
                'HCCL_DETERMINISTIC', 'ASCEND_GLOBAL_LOG_LEVEL')},
            'engine_sha256': sha(Path(__file__)),
            'code_sha256': {name: sha(Path(__file__).parent/name) for name in (
                'finetune27b_v2.py', 'finetune27b_engine.py', 'finetune27b_run_v2.py',
                'finetune27b_training_v2.py', 'metrics.py', 'common.py')},
            'prompt_sha256': digest(p['prompt']), 'precision': 'bfloat16',
            'attention': 'eager', 'gated_delta': 'torch reference'}


def load(model_dir, p, seed=42, cpu=False):
    torch, module, device = configure()
    from transformers import AutoTokenizer
    from peft import LoraConfig, get_peft_model
    identity = model_identity(model_dir, p)
    torch.manual_seed(seed)
    torch.npu.manual_seed_all(seed)
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False)
    base = module.Qwen3_5ForConditionalGeneration.from_pretrained(
        model_dir, dtype=torch.bfloat16, device_map={'': 'cpu' if cpu else device},
        attn_implementation='eager', local_files_only=True, trust_remote_code=False)
    cfg = p['training']
    original_parameter_count = sum(v.numel() for v in base.parameters())
    selected = [name for name, child in base.named_modules() if isinstance(child, torch.nn.Linear)
                and '.language_model.layers.' in name and name.rsplit('.', 1)[-1] in cfg['target_modules']]
    if not selected or set(n.rsplit('.', 1)[-1] for n in selected) != set(cfg['target_modules']):
        raise ValueError('Missing expected language projection modules')
    model = get_peft_model(base, LoraConfig(r=cfg['lora_rank'], lora_alpha=cfg['lora_alpha'],
        lora_dropout=cfg['lora_dropout'], target_modules=selected, bias='none', task_type='CAUSAL_LM'))
    if not all('lora_' in n for n, v in model.named_parameters() if v.requires_grad):
        raise ValueError('Backbone is trainable')
    model.eval()
    identity.update(target_modules=selected, trainable_parameters=sum(v.numel() for v in model.parameters() if v.requires_grad),
                    original_parameter_count=original_parameter_count, device_name=torch.npu.get_device_name(),
                    adapter_parameter_dtypes=sorted({str(v.dtype) for v in model.parameters() if v.requires_grad}),
                    backbone_parameter_dtypes=sorted({str(v.dtype) for v in model.parameters() if not v.requires_grad}),
                    cann_version=__import__('torch_npu').npu.utils.get_cann_version())
    return model, tokenizer, torch, device, identity


def encode(row, tokenizer, p, require_target=True, enforce_limit=True):
    prefix = tokenizer.apply_chat_template(messages(row, p['prompt']), tokenize=True,
        add_generation_prompt=True, enable_thinking=False, return_dict=False)
    if not isinstance(prefix, list):
        raise TypeError('Expected flat token IDs')
    answer = tokenizer.encode(target(row), add_special_tokens=False) + [tokenizer.eos_token_id] if require_target else []
    if enforce_limit and len(prefix) + len(answer) > p['training']['max_sequence_length']:
        raise ValueError('No truncation permitted: ' + row['id'])
    return {'prefix': prefix, 'answer': answer, 'row': row}


def loss(model, item, torch, device):
    prefix, answer = item['prefix'], item['answer']
    if not answer:
        raise ValueError('Empty training target')
    ids = torch.tensor([prefix + answer[:-1]], dtype=torch.long, device=device)
    out = model(input_ids=ids, attention_mask=torch.ones_like(ids), use_cache=False,
                logits_to_keep=len(answer))
    labels = torch.tensor(answer, device=device, dtype=torch.long)
    return torch.nn.functional.cross_entropy(out.logits[0].float(), labels)


def generate(model, tokenizer, row, p, torch, device, limit=None):
    prefix = encode(row, tokenizer, p, require_target=False, enforce_limit=False)['prefix']
    ids = torch.tensor([prefix], dtype=torch.long, device=device)
    torch.npu.synchronize()
    started = time.perf_counter()
    with torch.inference_mode():
        result = model.generate(input_ids=ids, attention_mask=torch.ones_like(ids), do_sample=False,
            max_new_tokens=limit or p['generation']['max_new_tokens'], use_cache=True,
            pad_token_id=tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id)
    torch.npu.synchronize()
    new = result[0, len(prefix):].tolist()
    eos = model.generation_config.eos_token_id
    finished = bool(new and new[-1] in (eos if isinstance(eos, list) else [eos]))
    text = tokenizer.decode(new, skip_special_tokens=True)
    # Special-token stripping can otherwise conceal emitted <think> tokens.
    raw_text = tokenizer.decode(new, skip_special_tokens=False)
    thinking = '<think' in raw_text.lower() or '</think' in raw_text.lower()
    return {'text': text, 'raw_text': raw_text, 'output_token_ids': new,
            'thinking_generated': thinking, 'finished': finished,
            'prediction': 'INVALID' if thinking else parse(text, finished),
            'reason_present': has_reason(text), 'input_sha256': digest(messages(row, p['prompt'])),
            'input_token_sha256': digest(prefix), 'input_tokens': len(prefix), 'output_tokens': len(new),
            'seconds': time.perf_counter() - started, 'status': 'completed' if finished else 'truncated'}
