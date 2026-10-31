"""Remote CPU tensor acceptance for the exact loss implementation used on NPU."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

base = Path('/root/ab_finetune27b_20261030')
sys.path.insert(0,str(base/'revision_2_workspace/src'))
os.environ['TORCH_DEVICE_BACKEND_AUTOLOAD'] = '0'  # CPU-only check, independent of CANN loader setup.
import torch
from ab_factcheck.finetune27b_engine import loss

table = torch.zeros(1,5,8,requires_grad=True)
def model(**kwargs):
    assert kwargs['input_ids'].tolist() == [[1,2,3,4,5]]
    assert kwargs['logits_to_keep'] == 3
    return SimpleNamespace(logits=table[:,-3:,:])
value = loss(model,{'prefix':[1,2,3],'answer':[4,5,7]},torch,'cpu')
value.backward()
assert torch.equal(table.grad[:,:2],torch.zeros_like(table.grad[:,:2]))
assert all(table.grad[0,pos,token] < 0 for pos,token in ((2,4),(3,5),(4,7)))
receipt = {'passed':True,'prompt_positions_without_loss':2,'answer_targets_including_eos':3,
           'execution':'real torch CPU gradient, same loss implementation', 'torch':torch.__version__}
(base/'revision_2_runs/loss_mask_check.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt))
