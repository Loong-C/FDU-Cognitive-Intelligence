"""Small random Qwen3.5-architecture autograd check; NOT a 27B model experiment."""
import json
import time
from ab_factcheck.finetune27b_runtime import configure_ml

torch, module = configure_ml()
from transformers import Qwen3_5TextConfig
from peft import LoraConfig, get_peft_model

config = Qwen3_5TextConfig(vocab_size=128, hidden_size=128, intermediate_size=256,
    num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2, head_dim=32,
    layer_types=['linear_attention', 'full_attention'], linear_key_head_dim=16,
    linear_value_head_dim=16, linear_num_key_heads=4, linear_num_value_heads=4,
    rope_parameters={'rope_type': 'default', 'rope_theta': 10000.,
                     'partial_rotary_factor': 1., 'mrope_section': [4, 6, 6], 'mrope_interleaved': True})
model = module.Qwen3_5ForCausalLM(config).to(device='npu:0', dtype=torch.bfloat16)
model = get_peft_model(model, LoraConfig(r=2, lora_alpha=4, target_modules=['q_proj','v_proj','in_proj_qkv','out_proj'], task_type='CAUSAL_LM'))
model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
model.enable_input_require_grads()
optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=1e-3)
ids = torch.randint(0, 128, (1, 64), device='npu:0')
began = time.perf_counter()
out = model(input_ids=ids, attention_mask=torch.ones_like(ids), logits_to_keep=3, use_cache=False)
loss = torch.nn.functional.cross_entropy(out.logits[0].float(), torch.tensor([20,21,22],device='npu:0'))
loss.backward()
nonzero = sum(int(p.grad is not None and p.grad.abs().sum().item() > 0) for p in model.parameters() if p.requires_grad)
optimizer.step()
assert nonzero > 0 and torch.isfinite(loss).item()
print(json.dumps({'tiny_architecture_autograd_pass':True,'loss':loss.item(),'parameters_with_nonzero_grad':nonzero,
                  'seconds':time.perf_counter()-began,'not_a_27b_result':True}),flush=True)
