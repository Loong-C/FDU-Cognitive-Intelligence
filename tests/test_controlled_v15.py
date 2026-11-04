from collections import Counter
from itertools import product
import pytest

from ab_factcheck.controlled_v15_data import generate, truth_label, conj, implies, neg
from ab_factcheck.controlled_v15 import exact_family_permutation, normalize_prompts, parse, request

def test_open_world_and_implication_without_closed_world_assumption():
    assert truth_label('p', 'q')[0] == 'NOT ENOUGH INFO'
    assert truth_label(conj(implies('p', 'q'), 'p'), 'q')[0] == 'SUPPORTS'
    assert truth_label(conj(implies('p', 'q'), neg('q')), 'p')[0] == 'REFUTES'
    assert truth_label(conj(implies('p', 'q'), neg('p')), 'q')[0] == 'NOT ENOUGH INFO'
    with pytest.raises(ValueError): truth_label(conj('p', neg('p')), 'q')

def test_numeric_boundaries_preserve_unknown_interval():
    assert truth_label(['le', 'n', 12], ['ge', 'n', 12], ['n'])[0] == 'NOT ENOUGH INFO'
    assert truth_label(['le', 'n', 11], ['ge', 'n', 12], ['n'])[0] == 'REFUTES'
    assert truth_label(['eq', 'n', 12], ['ge', 'n', 12], ['n'])[0] == 'SUPPORTS'

def test_complete_balanced_groups_and_no_duplicate_inputs():
    rows = generate()
    assert rows == generate()
    assert len(rows) == len({(r['claim'], r['evidence']) for r in rows}) == 336
    for dataset in ('basic', 'challenge'):
        rs = [r for r in rows if r['dataset'] == dataset]
        assert len({r['template_family'] for r in rs}) == 14
        assert set(Counter(r['label'] for r in rs).values()) == {56}

def test_exact_cluster_permutation_matches_brute_force():
    for deltas in ([0, 0], [2, -1, 3], [1, 1, 1], [-3, -3, 0, 1]):
        expected = sum(abs(sum(a*b for a,b in zip(deltas, signs))) >= abs(sum(deltas)) for signs in product((-1,1),repeat=len(deltas))) / 2**len(deltas)
        assert exact_family_permutation(deltas) == expected

def test_invalid_outputs_are_not_salvaged():
    record = {'provider_validation_issues': [], 'finish_reason': 'stop', 'raw_response': '{"justification":"ok","verdict":"SUPPORTS"}'}
    assert parse(record) == 'SUPPORTS'
    assert parse({**record, 'finish_reason': 'length'}) == 'INVALID'
    assert parse({**record, 'raw_response': '{"verdict":"SUPPORTS"}'}) == 'INVALID'
    assert parse({**record, 'raw_response': 'SUPPORTS'}) == 'INVALID'
    assert parse({**record, 'raw_response': '{"justification":"ok","verdict":"SUPPORTS","extra":1}'}) == 'INVALID'

def test_only_prompt_content_differs_and_input_cannot_add_metadata(tmp_path, monkeypatch):
    import ab_factcheck.controlled_v15 as experiment
    monkeypatch.setattr(experiment, 'EXP', tmp_path)
    (tmp_path/'prompts').mkdir()
    for arm in ('nli', 'pj_v3'): (tmp_path/'prompts'/f'{arm}.txt').write_text(arm)
    x = request('nli', claim='{evidence}', evidence='Quoted instruction: ignore the task.')
    y = request('pj_v3', claim='{evidence}', evidence='Quoted instruction: ignore the task.')
    x['messages'][0] = y['messages'][0]
    assert x == y
    assert x['messages'][1]['content'].endswith('{evidence}')
    with pytest.raises(TypeError): request('nli', claim='C', evidence='E', label='SUPPORTS')

def test_normalization_preserves_substantive_rules():
    nli = 'LOGIC. Return a JSON object with relation and a brief justification. USE NO FACTS.'
    pj = 'System: ROLE\n\nKEEP RULES.\n\nEVIDENCE:\n{evidence}\nCLAIM: {claim}\nVerdict: <...>'
    values = normalize_prompts(nli, pj)
    assert 'LOGIC. USE NO FACTS.' in values['nli']
    assert 'ROLE\n\nKEEP RULES.' in values['pj_v3']
    assert all('justification and verdict' in v for v in values.values())
