import json
from pathlib import Path

import pytest

from ab_factcheck import finetune27b_v2 as c
from ab_factcheck.finetune27b_run_v2 import infer_rows
from ab_factcheck.finetune27b_training_v2 import recover_latest


def test_received_incorrect_answer_is_never_retried(tmp_path, monkeypatch):
    from ab_factcheck import finetune27b_engine as e
    data = [dict(dataset='basic', id='i', evidence='E', claim='C', label='SUPPORTS')]
    p = {'prompt': {'system': 'S', 'user': '{evidence} {claim}'}}
    ident = {'run': 'test'}
    c.save(tmp_path/'identity.json', ident)
    result = {'identity': c.digest(ident), 'input_sha256': c.digest(c.messages(data[0], p['prompt'])),
              'prediction': 'REFUTES', 'seconds': 1., 'text':'Reason.\nVerdict: REFUTES', 'finished':True}
    c.save(tmp_path/'basic_i.json', result)
    def fail(*args, **kwargs):
        pytest.fail('A received answer was regenerated')
    monkeypatch.setattr(e, 'generate', fail)
    assert infer_rows(None, None, data, p, None, None, tmp_path, ident)['basic_i'] == result


def test_failed_request_is_persisted_and_not_retried(tmp_path, monkeypatch):
    from ab_factcheck import finetune27b_engine as e
    from contextlib import nullcontext
    class Model:
        disable_adapter = staticmethod(nullcontext)
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise RuntimeError('injected backend failure')
    monkeypatch.setattr(e, 'generate', fail)
    data = [dict(dataset='basic', id='i', evidence='E', claim='C', label='SUPPORTS')]
    p = {'prompt': {'system': 'S', 'user': '{evidence} {claim}'}}
    with pytest.raises(RuntimeError):
        infer_rows(Model(), None, data, p, None, None, tmp_path, {})
    result = infer_rows(Model(), None, data, p, None, None, tmp_path, {})
    assert result['basic_i']['prediction'] == 'INVALID' and len(calls) == 1


def test_checkpoint_recovers_after_rename_before_pointer_update(tmp_path):
    provenance = {'run':'fixture'}
    folder = tmp_path/'checkpoint-e01-c00128'
    folder.mkdir()
    (folder/'adapter_model.safetensors').write_bytes(b'fixture adapter')
    (folder/'optimizer_rng.pt').write_bytes(b'fixture optimizer')
    (folder/'adapter_config.json').write_text('{"test_fixture":true}')
    receipt = {'identity': provenance, 'epoch':1, 'cursor':128,
               'adapter_sha256':c.sha(folder/'adapter_model.safetensors'),
               'adapter_config_sha256':c.sha(folder/'adapter_config.json'),
               'optimizer_sha256':c.sha(folder/'optimizer_rng.pt')}
    c.save(folder/'receipt.json', receipt)
    (tmp_path/'checkpoint-e01-c00256.incomplete').mkdir()
    assert recover_latest(tmp_path, provenance) == {'checkpoint':folder.name,'receipt':receipt}
    original_config=(folder/'adapter_config.json').read_bytes()
    (folder/'adapter_config.json').write_text('{"test_fixture":"changed"}')
    with pytest.raises(ValueError, match='provenance'):
        recover_latest(tmp_path, provenance)
    (folder/'adapter_config.json').write_bytes(original_config)
    (folder/'adapter_model.safetensors').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='provenance'):
        recover_latest(tmp_path, provenance)


def test_loss_is_answer_only_including_eos():
    torch = pytest.importorskip('torch')
    from types import SimpleNamespace
    from ab_factcheck.finetune27b_engine import loss
    table = torch.zeros(1, 5, 8, requires_grad=True)
    def model(**kwargs):
        assert kwargs['input_ids'].tolist() == [[1,2,3,4,5]]
        assert kwargs['logits_to_keep'] == 3
        return SimpleNamespace(logits=table[:, -3:, :])
    value = loss(model, {'prefix':[1,2,3], 'answer':[4,5,7]}, torch, 'cpu')
    value.backward()
    assert torch.equal(table.grad[:, :2], torch.zeros_like(table.grad[:, :2]))
    assert all(table.grad[0, pos, token] < 0 for pos, token in ((2,4),(3,5),(4,7)))
