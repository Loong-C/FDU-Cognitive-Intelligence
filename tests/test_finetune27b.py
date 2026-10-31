import itertools
import json
from pathlib import Path
import shutil

import pytest

from ab_factcheck.finetune27b import (ROOT, EXPERIMENT, exact_group_test, messages,
    parse_verdict, prepare, prompts, read_rows, report, split_dev, target_text, verify)
from ab_factcheck.finetune27b_runtime import tokenized


def test_prompt_is_original_baseline_without_metadata():
    row = {'evidence': 'quoted {claim}', 'claim': 'A claim', 'label': 'SUPPORTS',
           'mechanism': 'DO_NOT_SEND', 'group': 'DO_NOT_SEND', 'id': 'DO_NOT_SEND'}
    result = messages(row, prompts())
    assert result[0]['content'] == (ROOT / 'prompts/v1/A0_system.txt').read_text().strip()
    assert result[1]['content'] == (ROOT / 'prompts/v1/A0_user.txt').read_text().strip().format(
        evidence=row['evidence'], claim=row['claim'])
    assert 'DO_NOT_SEND' not in str(result)
    assert 'quoted {claim}' in result[1]['content']


def test_group_partition_is_order_invariant_complete_and_disjoint():
    rows = read_rows(ROOT / 'data/splits/v1/challenge/dev.jsonl')
    parts = split_dev(rows)
    assert parts == split_dev(list(reversed(rows)))
    assert {r['group'] for r in parts['train']}.isdisjoint(r['group'] for r in parts['validation'])
    assert {r['id'] for p in parts.values() for r in p} == {r['id'] for r in rows}
    assert {r['mechanism'] for r in parts['validation']} == {r['mechanism'] for r in rows}
    with pytest.raises(ValueError, match='Duplicate'):
        split_dev(rows + rows[:1])


def test_prepare_needs_only_dev_and_catches_tampering(tmp_path):
    # Deliberately no test.jsonl files exist in this sandbox.
    for name in ['prompts/v1/A0_system.txt', 'prompts/v1/A0_user.txt',
                 'data/splits/v1/basic/dev.jsonl', 'data/splits/v1/challenge/dev.jsonl',
                 str(EXPERIMENT / 'model_source.json')]:
        dest = tmp_path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    p = prepare(tmp_path)
    assert sum(d['rows'] for part in p['summary'].values() for d in part.values()) == 1422
    assert verify(tmp_path) == p
    path = tmp_path / EXPERIMENT / 'train.jsonl'
    with path.open('a') as f:
        f.write('\n')
    with pytest.raises(ValueError, match='Frozen file changed'):
        verify(tmp_path)


@pytest.mark.parametrize('text,finished,expected', [
    ('A brief explanation.\nVerdict: SUPPORTS', True, 'SUPPORTS'),
    ('Verdict: NOT ENOUGH INFO\n', True, 'NOT ENOUGH INFO'),
    ('Verdict: REFUTES', False, 'INVALID'),
    ('Verdict: SUPPORTS\nExtra text', True, 'INVALID'),
    ('<think>Reasoning</think>\nVerdict: SUPPORTS', True, 'INVALID'),
    ('SUPPORTS', True, 'INVALID'),
])
def test_strict_parser(text, finished, expected):
    assert parse_verdict(text, finished) == expected


@pytest.mark.parametrize('deltas', [[1, 2, -1, 0], [0, 0], [2] * 6, [-1, -2, 3]])
def test_exact_group_dp_matches_bruteforce(deltas):
    observed = abs(sum(deltas))
    brute = sum(abs(sum(a * b for a, b in zip(signs, deltas))) >= observed
                for signs in itertools.product((-1, 1), repeat=len(deltas))) / 2**len(deltas)
    assert exact_group_test(deltas) == brute


def test_tokenization_preserves_full_prompt_only_supervises_verdict_and_refuses_truncation():
    class Tokenizer:
        eos_token_id = 999
        def apply_chat_template(self, msgs, **kwargs):
            assert kwargs == dict(tokenize=True, add_generation_prompt=True, enable_thinking=False)
            return [10, 11, 12]
        def encode(self, text, **kwargs):
            assert text == 'Verdict: REFUTES'
            assert kwargs == {'add_special_tokens': False}
            return [20, 21]
    row = dict(evidence='e', claim='c', label='REFUTES', id='i')
    protocol = {'prompt': prompts(), 'training': {'max_sequence_length': 6}}
    item = tokenized(row, Tokenizer(), protocol)
    assert item['prefix'] == [10, 11, 12]
    assert item['answer'] == [20, 21, 999]
    protocol['training']['max_sequence_length'] = 5
    with pytest.raises(ValueError, match='No truncation'):
        tokenized(row, Tokenizer(), protocol)


def test_report_keeps_invalid_predictions_and_paired_denominators():
    protocol = verify()
    rows = []
    for dataset in ('basic', 'challenge'):
        for i, label in enumerate(('SUPPORTS', 'REFUTES', 'NOT ENOUGH INFO')):
            rows.append(dict(dataset=dataset, id=str(i), group=str(i), label=label,
                baseline={'prediction': label}, adapter={'prediction': label if i else 'INVALID'}))
    result = report(rows, protocol)
    assert result['datasets']['basic']['metrics']['adapter']['n'] == 3
    assert result['datasets']['basic']['metrics']['adapter']['accuracy'] == 2 / 3
    assert not result['guardrails_pass']
    assert not result['primary_pass']
    with pytest.raises(ValueError, match='Duplicate'):
        report(rows + rows[:1], protocol)
