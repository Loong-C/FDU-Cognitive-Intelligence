"""Isolated quick-scope tests; only synthetic rows and frozen development metadata."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from ab_factcheck import fusion_v18 as f, finetune27b_v2 as c
from ab_factcheck import fusion_v18_quick24 as q
from ab_factcheck import fusion_v18_training as training


def manager():
    spec = importlib.util.spec_from_file_location('quick_manager_test', f.ROOT / 'scripts/manage_fusion_v18_quick24.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def synthetic():
    return [dict(dataset=d, id=str(i), group=d + str(i), mechanism='synthetic', label=label,
                 evidence='Synthetic evidence.', claim='Synthetic claim.')
            for d in ('basic', 'challenge') for i, label in enumerate(c.LABELS)]


def response(row, pred=None):
    pred = pred or row['label']; text = 'Evidence reason.\nVerdict: ' + pred
    return f.seal_record(dict(dataset=row['dataset'], id=row['id'], text=text, raw_text=text,
        prediction=pred, finished=True, status='completed', reason_present=True,
        input_tokens=10, output_tokens=8, seconds=1., logical_calls=1))


def test_catalogue_preserves_seeds_full_rows_and_unchanged_recipes():
    m, p = q.verify()
    assert m['fixed_epoch'] == 3 and m['deadline_unix'] - m['stop_compute_unix'] >= 3600
    val, dev = q.catalog(p, 'validation'), q.catalog(p, 'evaluation')
    assert len(val['direct']) == 25 and len(val['fusion']) == 10
    assert len(dev['direct']) == 13 and not dev['fusion'] and len(dev['families']) == 5
    assert all(v['prompt'] == 'a0' for v in dev['direct'].values())
    for kind in ('direct', 'fusion'):
        for arm, spec in val[kind].items(): assert spec == p[kind][arm]
    assert len(f.data('validation')) == 259 and len(f.data('evaluation')) == 261
    with pytest.raises(ValueError): q.catalog(p, 'test')


def test_fixed_epoch_rejects_incomplete_wrong_epoch_and_weight_drift(tmp_path, monkeypatch):
    old, output = tmp_path / 'old', tmp_path / 'quick'
    folder = old / 'training/nli/seed-42'; checkpoint = folder / 'checkpoint-e03-c00728'
    checkpoint.mkdir(parents=True)
    (checkpoint / 'adapter_model.safetensors').write_bytes(b'weights')
    (checkpoint / 'adapter_config.json').write_bytes(b'{}')
    identity = {'expected': True}
    monkeypatch.setattr(training, 'identity', lambda *a: identity)
    c.save(old / 'training/nli/smoke/receipt.json', {'passed': True, 'environment': {}})
    receipt = {'epoch': 3, 'cursor': 728, 'identity': identity,
               'adapter_sha256': c.sha(checkpoint / 'adapter_model.safetensors'),
               'adapter_config_sha256': c.sha(checkpoint / 'adapter_config.json')}
    entry = {'epoch': 3, 'checkpoint': checkpoint.name, 'receipt': receipt}
    c.save(checkpoint / 'receipt.json', receipt); c.save(folder / 'epoch-3.json', entry)
    with pytest.raises(FileNotFoundError): q.snapshot_adapter(old, output, 'distill_nli_42')
    c.save(folder / 'training_complete.json', {'identity': identity, 'epochs': 3})
    c.save(folder / 'epoch-3.json', {**entry, 'epoch': 2})
    with pytest.raises(ValueError): q.snapshot_adapter(old, output, 'distill_nli_42')
    c.save(folder / 'epoch-3.json', entry)
    _, result = q.snapshot_adapter(old, output, 'distill_nli_42')
    assert result['policy'] == 'fixed_epoch_3_no_validation_selection'
    assert not list(tmp_path.rglob('selection.json'))
    assert q.snapshot_adapter(old, output, 'distill_nli_42')[1] == result
    (checkpoint / 'adapter_model.safetensors').write_bytes(b'changed')
    with pytest.raises(ValueError): q.snapshot_adapter(old, output, 'distill_nli_42')


def test_scheduler_fills_idle_card_with_validation_while_last_training_runs():
    m = manager()
    train = {a: True for a in q.NEW}; val = {a: False for a in q.NEW}
    train['distill_joint_42'] = train['distill_joint_43'] = train['distill_joint_44'] = False
    assert m.next_job(train, val, []) == 'train-distill_joint_42'
    assert m.next_job(train, val, ['train-distill_joint_42']) == 'train-distill_joint_43'
    train['distill_joint_42'] = True
    assert m.next_job(train, val, ['train-distill_joint_43']) == 'train-distill_joint_44'
    train['distill_joint_43'] = True
    assert m.next_job(train, val, ['train-distill_joint_44']) == 'validate-distill_nli_42'
    assert m.next_job(train, val, ['train-distill_joint_44', 'validate-distill_nli_42']) == 'validate-distill_nli_43'


def test_deadline_and_evaluation_gate_precede_model_load(tmp_path, monkeypatch):
    m, _ = q.verify()
    q.check_deadline(m['stop_compute_unix'] - .01)
    with pytest.raises(TimeoutError): q.check_deadline(m['stop_compute_unix'])
    monkeypatch.setattr(q, 'check_deadline', lambda *a: None)
    monkeypatch.setattr(q.run, 'Runtime', lambda *a: pytest.fail('Loaded before validation gate'))
    with pytest.raises(FileNotFoundError):
        q.worker(SimpleNamespace(output=tmp_path, part='evaluation'))


@pytest.mark.parametrize('part,smoke_count', [('validation', 0), ('evaluation', 0), ('validation', 3)])
def test_worker_uses_frozen_math_explicit_adapter_and_complete_shards(tmp_path, monkeypatch, part, smoke_count):
    rows = synthetic(); rows[-1]['evidence'] *= 10
    monkeypatch.setattr(f, 'data', lambda _: rows)
    monkeypatch.setattr(q, 'check_deadline', lambda: None)
    events = []; calls = []
    monkeypatch.setattr(q, 'recommendation_gate', lambda _: events.append('gate'))
    monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *a: None))
    def snapshot(old, output, arm):
        c.save(output / 'adapters' / (arm + '.json'), {'arm': arm, 'fixed_epoch': 3})
        return tmp_path / 'epoch3' / arm, {}
    monkeypatch.setattr(q, 'snapshot_adapter', snapshot)
    class Runtime:
        def __init__(self, args):
            events.append('load')
            self.p = f.verify(); self.env = {}; self.runtime_sha = 'runtime'
            self.train_p = {}; self.tokenizer = None; self.arm = None
            self.prompts = c.read_json(f.ROOT / f.EXP / 'prompts.json')
        def activate(self, arm, folder=None):
            self.arm = arm
            if arm in q.NEW: assert folder == tmp_path / 'epoch3' / arm
        def call(self, row, prompt, relative, phase, deps):
            assert prompt == self.prompts['a0'] and phase == 'quick24_' + part
            assert deps[0] == c.sha(f.ROOT / q.MANIFEST)
            calls.append((self.arm, c.record_key(row)))
            return response(row)
    monkeypatch.setattr(q.run, 'Runtime', Runtime)
    def encode(row, *a, **kwargs):
        assert kwargs == {'require_target': False, 'enforce_limit': False}
        return {'prefix': list(range(len(row['evidence'])))}
    monkeypatch.setattr(q.run.engine, 'encode', encode)
    args = SimpleNamespace(output=tmp_path, old_output=tmp_path/'old', part=part,
                           arm='distill_nli_42', worker=1, smoke_count=smoke_count)
    q.worker(args)
    if part == 'validation':
        assert len(calls) == (smoke_count or len(rows)) and events == ['load']
        assert calls[0][1] == c.record_key(rows[-1])
        if smoke_count:
            assert c.read_json(tmp_path / 'smoke_receipt.json')['calls_reused_in_validation'] == 3
    else:
        assert events == ['gate', 'load']
        assert len(calls) == 13 * 3
        assert {key for _, key in calls} == {c.record_key(r) for i, r in enumerate(rows) if i % 2 == 1}


def test_report_holm_23_independent_metrics_and_frozen_recommendation(tmp_path, monkeypatch):
    p = f.verify(); rows = synthetic()
    monkeypatch.setattr(f, 'data', lambda part: rows)
    for arm in q.NEW: c.save(tmp_path / 'adapters' / (arm + '.json'), {'arm': arm, 'fixed_epoch': 3})
    def load(output, part, protocol):
        selected = q.catalog(protocol, part); predictions = {}
        for arm in (*selected['direct'], *selected['fusion']):
            predictions[arm] = {}
            for row in rows:
                pred = row['label']
                if row['dataset'] == 'challenge' and row['label'] == 'NOT ENOUGH INFO':
                    if arm.startswith(('old_a0_', 'distill_pj_', 'distill_joint_')): pred = 'SUPPORTS'
                predictions[arm][c.record_key(row)] = response(row, pred)
        return rows, predictions, selected
    monkeypatch.setattr(q, 'load_records', load)
    result = q.report(tmp_path, 'validation')
    pairs = result['datasets']['challenge']['pairs']
    assert len(pairs) == 23 and sum(not x['evaluated'] for x in pairs) == 9
    assert all(x['p'] == 1 for x in pairs if not x['evaluated'])
    assert q.recommendation_gate(tmp_path)['method_family'] == 'distill_nli'
    before = (tmp_path / 'quick_recommendation.json').read_bytes()
    assert q.report(tmp_path, 'validation') == result
    evaluation = q.report(tmp_path, 'evaluation')
    assert len(evaluation['record_hashes']) == 13 * len(rows)
    assert sum(not x['evaluated'] for x in evaluation['datasets']['challenge']['pairs']) == 19
    assert (tmp_path / 'quick_recommendation.json').read_bytes() == before
    assert not (tmp_path / 'recommendation.json').exists()
    c.save(tmp_path / 'adapters/distill_nli_42.json', {'changed': True})
    with pytest.raises(ValueError): q.recommendation_gate(tmp_path)


def test_record_reader_rejects_phase_adapter_and_missing_rows(tmp_path, monkeypatch):
    p = f.verify(); rows = synthetic(); monkeypatch.setattr(f, 'data', lambda part: rows)
    c.save(tmp_path / 'inference_environment.json', {'environment_sha256': 'env', 'runtime_sha256': 'runtime'})
    for arm in q.NEW:
        c.save(tmp_path / 'adapters' / (arm + '.json'), {'policy': 'fixed_epoch_3_no_validation_selection',
               'epoch_receipt': {'epoch': 3, 'receipt': {'adapter_sha256': arm}}})
    prompt = c.read_json(f.ROOT / f.EXP / 'prompts.json')['a0']
    for arm in q.CORE:
        adapter = arm if arm in q.NEW else (p['old_adapters'][arm.rsplit('_', 1)[1]]['adapter_sha256'] if arm != 'base_a0' else None)
        for row in rows:
            rel = Path('evaluation/direct') / arm / (c.record_key(row) + '.json')
            record = response(row); record.pop('record_sha256')
            inp = c.digest(c.messages(row, prompt))
            record.update(input_sha256=inp, input_token_sha256='tokens', physical_call=rel.as_posix(),
                identity={'freeze': c.sha(f.ROOT / f.EXP / 'freeze.json'), 'runtime': 'runtime', 'environment': 'env',
                    'adapter_sha256': adapter, 'phase': 'quick24_evaluation', 'input_sha256': inp,
                    'input_token_sha256': 'tokens', 'generation': p['generation'], 'dependencies': q.dependencies(tmp_path, arm)})
            c.save(tmp_path / rel, f.seal_record(record))
    assert len(q.load_records(tmp_path, 'evaluation', p)[1]) == 13
    path = tmp_path / 'evaluation/direct/distill_nli_42/basic_0.json'
    original = c.read_json(path)
    for field, change in [('phase', 'evaluation'), ('adapter_sha256', 'wrong')]:
        value = {k: v for k, v in original.items() if k != 'record_sha256'}
        value['identity'] = {**value['identity'], field: change}
        c.save(path, f.seal_record(value))
        with pytest.raises(ValueError): q.load_records(tmp_path, 'evaluation', p)
    path.unlink()
    with pytest.raises(FileNotFoundError): q.load_records(tmp_path, 'evaluation', p)


def test_physical_cost_does_not_count_fusion_or_alias_twice(tmp_path):
    row = synthetic()[0]; record = response(row); record.pop('record_sha256')
    record.update(identity={'phase': 'validation'}, physical_call='validation/direct/base_a0/basic_0.json')
    sealed = f.seal_record(record)
    c.save(tmp_path / 'validation/direct/base_a0/basic_0.json', sealed)
    c.save(tmp_path / 'validation/direct/alias/basic_0.json', sealed)
    c.save(tmp_path / 'validation/fusion/method/basic_0.json', sealed)
    assert q.physical_cost(tmp_path)['calls'] == 1
    record['seconds'] = 2
    c.save(tmp_path / 'validation/direct/alias/basic_0.json', f.seal_record(record))
    with pytest.raises(ValueError): q.physical_cost(tmp_path)


def test_partial_deadline_never_scores_partial_method(tmp_path, monkeypatch):
    rows = synthetic(); monkeypatch.setattr(f, 'data', lambda part: rows)
    record = response(rows[0]); record.pop('record_sha256')
    record.update(identity={'phase': 'quick24_validation'}, physical_call='validation/direct/distill_nli_42/basic_0.json')
    c.save(tmp_path / record['physical_call'], f.seal_record(record))
    completed = q.finish(tmp_path, 'deadline_partial')
    assert not completed['quick_scope_complete'] and not completed['original_full_plan_complete']
    assert completed['coverage']['validation']['distill_nli_42']['received'] == 1
    partial = c.read_json(tmp_path / 'partial_results.json')
    assert not partial['validation']['complete_methods']
    assert not (tmp_path / 'quick_recommendation.json').exists()


def test_deadline_signals_only_matching_guard_and_invokes_recovery(tmp_path, monkeypatch):
    m = manager(); monkeypatch.setattr(m, 'OUT', tmp_path)
    directory = tmp_path / 'private'; directory.mkdir()
    c.save(tmp_path / 'controller.json', {'pid': 111, 'start_time': 'owned'})
    c.save(tmp_path / 'guard.json', {'directory': str(directory)})
    c.save(directory / 'snapshot.private.json', {'pid': 222})
    events = []
    state = {'alive': True}
    guard = SimpleNamespace(matching=lambda pointer: state['alive'],
        stop_command=lambda *a: events.append('stop_owned_session'),
        restore=lambda *a: events.append('restore_api'))
    monkeypatch.setattr(m, 'original', lambda: SimpleNamespace(guard_module=lambda: guard))
    monkeypatch.setattr(m, 'quick', lambda: SimpleNamespace(verify=lambda: ({'stop_compute_unix': 0, 'deadline_unix': 3600}, {})))
    monkeypatch.setattr(m.os, 'kill', lambda pid, sig: (events.append(('signal', pid)), state.update(alive=False)))
    monkeypatch.setattr(m, 'publish', lambda: events.append('publish_after_restore'))
    m.deadline()
    assert events == [('signal', 111), 'stop_owned_session', 'restore_api', 'publish_after_restore']
