import importlib.util
import itertools
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from ab_factcheck import fusion_v18 as f, fusion_v18_run as run, fusion_v18_report as report
from ab_factcheck import finetune27b_v2 as c


def audit_module():
    spec = importlib.util.spec_from_file_location('v18_independent_audit', f.ROOT / 'scripts/audit_fusion_v18.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_frozen_matrix_and_data_boundaries():
    p = f.verify()
    assert (len(p['direct']), len(p['fusion']), len(p['families'])) == (25, 37, 24)
    assert sum(len(v) for v in p['families'].values()) == 62
    assert all(v['prompt'] == 'a0' for k, v in p['direct'].items() if k.startswith('distill_'))
    assert all(len(v) in (1, 3) for v in p['families'].values())
    parts = {part: f.data(part) for part in ('train', 'validation', 'evaluation')}
    f.assert_partitions(parts)
    assert [len(v) for v in parts.values()] == [728, 259, 261]
    assert all(r['mechanism'] != 'PRESUP' for r in parts['train'])


@pytest.mark.parametrize('overlap', ['id', 'group', 'text'])
def test_partition_leaks_rejected(overlap):
    a = dict(id='a', dataset='basic', group='g1', label='SUPPORTS', evidence='A fact', claim='A claim')
    b = dict(a, id='b', group='g2', evidence='Other fact', claim='Other claim')
    if overlap == 'text':
        b.update(evidence='  A   FACT ', claim='A claim')
    else:
        b[overlap] = a[overlap]
    with pytest.raises(ValueError):
        f.assert_partitions({'train': [a], 'validation': [b]})


def test_prompt_composition_and_no_metadata_leak():
    prompts = c.read_json(f.ROOT / f.EXP / 'prompts.json')
    assert prompts['np']['system'] == prompts['nli']['system'] + '\n\n' + prompts['pj']['system']
    assert len({prompts[n]['user'] for n in f.PROMPTS}) == 1
    row = dict(f.data('train')[0], label='GOLD_SENTINEL', mechanism='MECHANISM_SENTINEL', group='GROUP_SENTINEL')
    candidates = [{'text': 'A brace {not an instruction}\nVerdict: SUPPORTS', 'prediction': 'SUPPORTS', 'source': 'SOURCE_SENTINEL'}] * 2
    messages = c.messages(row, f.review_prompt(row, candidates, 'train'))
    text = str(messages)
    assert not any(v in text for v in ('GOLD_SENTINEL', 'MECHANISM_SENTINEL', 'GROUP_SENTINEL', 'SOURCE_SENTINEL'))
    assert '{not an instruction}' in text
    assert row['evidence'] in messages[1]['content']


def test_candidate_permutations_balanced():
    from collections import Counter
    orders = c.read_json(f.ROOT / f.EXP / 'candidate_orders.json')
    for part in orders.values():
        for n in (2, 3):
            counts = Counter(tuple(v[str(n)]) for v in part.values())
            assert set(counts) == set(itertools.permutations(range(n)))
            assert max(counts.values()) - min(counts.values()) <= 1


@pytest.mark.parametrize('labels,expected', [(['SUPPORTS'] * 2, 'SUPPORTS'), (['REFUTES'] * 3, 'REFUTES'),
    (['INVALID'] * 2, None), (['SUPPORTS', 'INVALID'], None), (['SUPPORTS', 'REFUTES'], None)])
def test_consensus_never_votes_over_disagreement(labels, expected):
    assert f.consensus([{'prediction': x} for x in labels]) == expected


def mock_runtime(tmp_path, monkeypatch):
    rt = run.Runtime.__new__(run.Runtime)
    rt.args = SimpleNamespace(output=tmp_path)
    rt.p = f.verify(); rt.runtime_sha = 'runtime'; rt.env = {'test': True}
    rt.train_p = c.read_json(f.ROOT / f.OLD / 'training_protocol.json')
    rt.model = SimpleNamespace(disable_adapter=nullcontext)
    rt.tokenizer = rt.torch = rt.device = None
    rt.adapter = rt.adapter_sha = None
    monkeypatch.setattr(run.engine, 'encode', lambda *args, **kwargs: {'prefix': [1, 2, 3]})
    return rt


def response(label='SUPPORTS'):
    return {'text': 'Evidence reason.\nVerdict: ' + label, 'raw_text': 'Evidence reason.\nVerdict: ' + label,
            'prediction': label, 'finished': True, 'status': 'completed', 'reason_present': True,
            'input_tokens': 3, 'output_tokens': 4, 'output_token_ids': [1, 2, 3, 4], 'seconds': 1.0}


def test_received_response_reused_and_input_drift_rejected(tmp_path, monkeypatch):
    rt = mock_runtime(tmp_path, monkeypatch); calls = []
    monkeypatch.setattr(run.engine, 'generate', lambda *a, **k: calls.append(1) or response())
    row = f.data('train')[0]; prompt = rt.train_p['prompt']
    a = rt.call(row, prompt, Path('call.json'), 'teacher')
    assert rt.call(row, prompt, Path('call.json'), 'teacher') == a and len(calls) == 1
    with pytest.raises(ValueError, match='identity'):
        rt.call(dict(row, claim='changed'), prompt, Path('call.json'), 'teacher')
    assert len(calls) == 1


def test_received_failure_not_retried(tmp_path, monkeypatch):
    rt = mock_runtime(tmp_path, monkeypatch); calls = []
    def fail(*args, **kwargs):
        calls.append(1); raise RuntimeError('simulated OOM')
    monkeypatch.setattr(run.engine, 'generate', fail)
    row = f.data('train')[0]
    with pytest.raises(RuntimeError):
        rt.call(row, rt.train_p['prompt'], Path('call.json'), 'teacher')
    value = rt.call(row, rt.train_p['prompt'], Path('call.json'), 'teacher')
    assert value['prediction'] == 'INVALID' and len(calls) == 1


def test_unresolved_attempt_halts_without_generation(tmp_path, monkeypatch):
    rt = mock_runtime(tmp_path, monkeypatch)
    (tmp_path / 'call.inflight').write_text('{}')
    monkeypatch.setattr(run.engine, 'generate', lambda *a, **k: pytest.fail('must not generate'))
    with pytest.raises(ValueError, match='interrupted'):
        rt.call(f.data('train')[0], rt.train_p['prompt'], Path('call.json'), 'teacher')


@pytest.mark.parametrize('hidden', [False, True])
def test_strict_parser_and_checksum(hidden):
    value = response()
    if hidden:
        value.update(raw_text='<think>hidden</think>' + value['text'], thinking_generated=True, prediction='INVALID')
    sealed = f.seal_record(value)
    assert f.check_record(sealed)['prediction'] == audit_module().parse(sealed)
    sealed['text'] += 'tampering'
    with pytest.raises(ValueError, match='checksum'):
        f.check_record(sealed)


def test_incomplete_reviews_cannot_start_training(tmp_path):
    path = tmp_path / 'reviews.jsonl'; path.write_text('')
    with pytest.raises(ValueError, match='2184'):
        f.freeze_reviews(path, tmp_path)


@pytest.mark.parametrize('effects', [[], [0, 0], [1], [3, -1, 2], [2, -2, 0, 4]])
def test_independent_group_statistics(effects):
    values = [sum(a * b for a, b in zip(signs, effects)) for signs in itertools.product((-1, 1), repeat=len(effects))]
    expected = sum(abs(v) >= abs(sum(effects)) for v in values) / len(values)
    assert c.exact_group_test(effects) == audit_module().group_p(effects) == expected


def test_full_62_method_report_and_independent_audit(tmp_path, monkeypatch):
    protocol = f.verify(); original = f.data('validation')
    rows = [next(r for r in original if r['dataset'] == d and r['label'] == label) for d in ('basic', 'challenge') for label in c.LABELS]
    monkeypatch.setattr(f, 'data', lambda part: rows)
    prompts = c.read_json(f.ROOT / f.EXP / 'prompts.json')
    for source in f.SOURCES:
        for seed in f.SEEDS:
            c.save(tmp_path / 'training' / source / f'seed-{seed}/selection.json', {'selected': {'adapter_sha256': f'{source}-{seed}'}})
    for row in rows:
        key = c.record_key(row)
        direct = {}
        for arm, spec in protocol['direct'].items():
            value = response(row['label']); value.update(dataset=row['dataset'], id=row['id'], logical_calls=1)
            if arm == 'base_nli':
                value.update(text='malformed', raw_text='malformed', prediction='INVALID')
            adapter = spec['adapter']; expected = None
            if adapter:
                expected = protocol['old_adapters'][adapter.rsplit('_', 1)[1]]['adapter_sha256'] if adapter.startswith('old_') else adapter.replace('distill_', '').replace('_', '-')
            value.update(identity={'freeze': c.sha(f.ROOT / f.EXP / 'freeze.json'), 'adapter_sha256': expected},
                input_sha256=c.digest(c.messages(row, prompts[spec['prompt']])), physical_call=f'validation/direct/{arm}/{key}.json')
            value = f.seal_record(value); direct[arm] = value
            c.save(tmp_path / value['physical_call'], value)
        for name, spec in protocol['fusion'].items():
            candidates = [direct[a] for a in spec['components']]
            refs = [f'validation/direct/{a}/{key}.json' for a in spec['components']]
            reviewer = None
            if f.consensus(candidates) is None:
                relative = f'validation/review_calls/{name}/{key}.json'
                reviewer = response(row['label'])
                reviewer.update(dataset=row['dataset'], id=row['id'], logical_calls=1, physical_call=relative,
                    identity={'adapter_sha256': None}, input_sha256=c.digest(c.messages(row, f.review_prompt(row, candidates, 'validation'))))
                reviewer = f.seal_record(reviewer); c.save(tmp_path / relative, reviewer); refs.append(relative)
            calls = candidates + ([reviewer] if reviewer else [])
            answer = reviewer or candidates[0]
            value = {k: answer[k] for k in ('text', 'raw_text', 'prediction', 'finished', 'status', 'reason_present')}
            value.update(dataset=row['dataset'], id=row['id'], method=name, route='review' if reviewer else 'consensus',
                call_refs=refs, call_hashes=[v['record_sha256'] for v in calls], logical_calls=len(calls),
                **{field: sum(v[field] for v in calls) for field in ('seconds', 'input_tokens', 'output_tokens')})
            c.save(tmp_path / 'validation/fusion' / name / (key + '.json'), f.seal_record(value))
    result = report.report(tmp_path, 'validation')
    assert len(result['record_hashes']) == 62 * 6
    assert result['datasets']['basic']['scores']['base_nli']['invalid'] == 3
    assert all(p['n'] == 3 for p in result['datasets']['challenge']['pairs'])
    assert result['physical_cost']['calls'] < 62 * 6
    fake_root = tmp_path / 'audit_root'; exp = fake_root / f.EXP
    c.save(exp / 'protocol.json', protocol); c.write_rows(exp / 'validation.jsonl', rows)
    receipt = audit_module().audit(tmp_path, 'validation', root=fake_root)
    assert receipt['passed'] and receipt['scored_cells'] == 372
    result['datasets']['basic']['scores']['base_a0']['macro_f1'] = .2
    c.save(tmp_path / 'validation/results.json', result)
    with pytest.raises(AssertionError):
        audit_module().audit(tmp_path, 'validation', root=fake_root)


def test_evaluation_requires_audited_frozen_recommendation(tmp_path):
    with pytest.raises(FileNotFoundError):
        run.require_recommendation(tmp_path)
