import itertools
import json
from pathlib import Path
import shutil

import pytest

from ab_factcheck import finetune27b_v2 as c
from ab_factcheck.finetune27b_engine import encode


@pytest.fixture(scope='module')
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp('ft_v2_no_original_test')
    for name in ('prompts/v1/A0_system.txt', 'prompts/v1/A0_user.txt',
                 'data/splits/v1/basic/dev.jsonl', 'data/splits/v1/challenge/dev.jsonl',
                 'experiments/016_finetune_27b/model_source.json'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(c.ROOT / name, path)
    c.prepare(root)
    return root


def test_frozen_counts_and_candidates(prepared):
    p = c.verify_data(prepared)
    assert p['split_candidates'] == {'basic': 3, 'challenge': 278}
    assert [[p['summary'][part][d]['rows'] for d in ('basic', 'challenge')] for part in c.PARTS] == [
        [480, 422], [120, 139], [120, 141]]
    assert not list(prepared.rglob('test.jsonl'))


def test_order_invariance_and_group_partition(prepared):
    data = [dict(r, dataset='challenge') for r in c.rows(prepared/'data/splits/v1/challenge/dev.jsonl')]
    left, candidate = c.split(data, 'challenge')
    right, _ = c.split(data[::-1], 'challenge')
    assert candidate == 278 and left == right
    for a, b in itertools.combinations(c.PARTS, 2):
        assert {r['group'] for r in left[a]}.isdisjoint(r['group'] for r in left[b])
    with pytest.raises(ValueError, match='Duplicate'):
        c.split(data + data[:1], 'challenge')


def test_input_never_contains_management_or_gold(prepared):
    row = dict(evidence='literal {claim}', claim='A claim', label='PRIVATE_GOLD',
               rationale='PRIVATE_REASON', group='PRIVATE_GROUP', mechanism='PRIVATE_MECHANISM')
    result = c.messages(row, c.prompt(prepared))
    assert 'PRIVATE' not in str(result)
    assert 'literal {claim}' in result[1]['content']
    assert result[0]['content'] == (prepared/'prompts/v1/A0_system.txt').read_text().strip()


@pytest.mark.parametrize('text,finished,expected', [
    ('Evidence supports this.\nVerdict: SUPPORTS', True, 'SUPPORTS'),
    ('Verdict: NOT ENOUGH INFO\n', True, 'NOT ENOUGH INFO'),
    ('Verdict: REFUTES', False, 'INVALID'),
    ('Verdict: SUPPORTS\nextra', True, 'INVALID'),
    ('<THINK>x</THINK>\nVerdict: SUPPORTS', True, 'INVALID'),
    ('SUPPORTS', True, 'INVALID'),
])
def test_parser(text, finished, expected):
    assert c.parse(text, finished) == expected


def test_complete_answer_target_and_no_truncation():
    class Tokenizer:
        eos_token_id = 99
        def apply_chat_template(self, value, **kwargs):
            assert kwargs['return_dict'] is False and kwargs['enable_thinking'] is False
            return [1, 2, 3]
        def encode(self, value, **kwargs):
            assert value == 'The evidence denies the event.\nVerdict: REFUTES'
            assert kwargs == {'add_special_tokens': False}
            return [5, 6, 7]
    p = {'prompt': {'system': 'task', 'user': '{evidence} {claim}'}, 'training': {'max_sequence_length': 7}}
    row = dict(id='i', evidence='e', claim='c', label='REFUTES', rationale='The evidence denies the event.')
    item = encode(row, Tokenizer(), p)
    assert item['prefix'] == [1, 2, 3] and item['answer'] == [5, 6, 7, 99]
    p['training']['max_sequence_length'] = 6
    with pytest.raises(ValueError, match='No truncation'):
        encode(row, Tokenizer(), p)


def test_hash_tampering_detected(prepared, tmp_path):
    shutil.copytree(prepared, tmp_path/'copy')
    root = tmp_path/'copy'
    with (root/c.EXP/'train.jsonl').open('a') as f:
        f.write('\n')
    with pytest.raises(ValueError, match='Frozen file changed'):
        c.verify_data(root)


def make_reviews(root, directory):
    p = c.verify_data(root)
    source=root/c.EXP/'draft_source/finetune27b_engine.py'
    source.parent.mkdir(parents=True,exist_ok=True)
    source.write_text('# Synthetic test fixture, never a model engine.\n')
    identity = {'phase': 'training_rationale_drafts', 'data_freeze_sha256': c.sha(root/c.EXP/'data_freeze.json'),
                'generation': p['generation'], 'environment': {'precision': 'bfloat16',
                'prompt_sha256': c.digest(p['prompt']), 'model_manifest_sha256': c.sha(root/p['model_manifest']),
                'engine_sha256':c.sha(source)}}
    c.save(directory/'identity.json', identity)
    data = c.rows(root/c.EXP/'train.jsonl')
    reviews = []
    for r in data:
        path = directory/(c.record_key(r)+'.json')
        c.save(path, {'input_sha256': c.digest(c.messages(r, c.prompt(root))), 'identity': c.digest(identity)})
        reviews.append({'id': r['id'], 'label': r['label'], 'rationale': 'Fixture evidence explanation.',
                        'draft_sha256': c.sha(path), 'status': 'approved', 'reviewer': 'agent',
                        'review_note': 'TEST FIXTURE, not a production annotation.'})
    return data, reviews


def test_review_coverage_hashes_and_whole_group_exclusion(prepared, tmp_path):
    data, reviews = make_reviews(prepared, tmp_path/'drafts')
    with pytest.raises(ValueError, match='Every training row'):
        c.validate_reviews(reviews[:-1], tmp_path/'drafts', prepared)
    bad = [dict(r) for r in reviews]
    bad[0]['draft_sha256'] = 'bad'
    with pytest.raises(ValueError, match='source mismatch'):
        c.validate_reviews(bad, tmp_path/'drafts', prepared)
    reviews[0]['status'] = 'exclude_group'
    accepted, excluded = c.validate_reviews(reviews, tmp_path/'drafts', prepared)
    assert excluded == [(data[0]['dataset'], data[0]['group'])]
    assert not any((r['dataset'], r['group']) == excluded[0] for r in accepted)
    assert len(accepted) < len(data)-1


def test_training_freeze_is_complete_immutable_and_raises_length(prepared, tmp_path):
    root = tmp_path/'isolated'
    shutil.copytree(prepared, root)
    drafts = tmp_path/'drafts'
    data, reviews = make_reviews(root, drafts)
    review_file = tmp_path/'reviews.jsonl'
    c.write_rows(review_file, reviews)
    history_file=tmp_path/'reviews_history.jsonl'
    c.write_rows(history_file,[{'operation':'test_fixture','decision':r} for r in reviews])
    audit_file = tmp_path/'audit.json'
    c.save(audit_file, {'truncated':0,'max_tokens':1537,'world_size':1,'rows':len(data),
        'excluded_groups':[], 'reviews_sha256':c.sha(review_file),
        'data_freeze_sha256':c.sha(root/c.EXP/'data_freeze.json')})
    p = c.freeze_training(review_file, drafts, audit_file, root)
    assert p['training']['max_sequence_length'] == 1792
    assert p['training']['gradient_accumulation_steps'] == 16
    assert len(c.rows(root/c.EXP/'rationale_drafts.jsonl')) == 902
    assert c.freeze_training(review_file, drafts, audit_file, root) == p
    history=c.rows(history_file)
    c.write_rows(history_file,history+[{'operation':'changed_fixture'}])
    with pytest.raises(ValueError, match='review history'):
        c.freeze_training(review_file, drafts, audit_file, root)
    c.write_rows(history_file,history)
    reviews[0]['review_note'] = 'Changed test fixture annotation.'
    c.write_rows(review_file, reviews)
    with pytest.raises(ValueError, match='replacing'):
        c.freeze_training(review_file, drafts, audit_file, root)


def predictions(data, invalid_first=False):
    return {c.record_key(r): {'prediction': 'INVALID' if invalid_first and i == 0 else r['label'],
                             'seconds': 1., 'reason_present': True, 'input_tokens': 12, 'output_tokens': 8}
            for i, r in enumerate(data)}


def sample_rows():
    return [dict(dataset=d, id=f'{d}{i}', group=f'{d}g{i//3}', mechanism='m', label=label)
            for d in ('basic', 'challenge') for i, label in enumerate(c.LABELS * 3)]


def test_failures_remain_in_denominator_and_three_seed_group_unit(prepared):
    data = sample_rows()
    p = c.verify_data(prepared)
    baseline = predictions(data, True)
    adapters = {str(s): predictions(data) for s in c.SEEDS}
    result = c.final_report(data, baseline, adapters, p)
    m = result['by_seed']['42']['datasets']['basic']['baseline']
    assert m['n'] == 9 and m['accuracy'] == 8/9
    assert result['datasets']['basic']['group_integer_deltas'] == {'basicg0': 3, 'basicg1': 0, 'basicg2': 0}
    assert result['datasets']['basic']['two_sided_group_p'] == 1.0
    with pytest.raises(ValueError, match='All three'):
        c.final_report(data, baseline, {'42': adapters['42']}, p)
    missing = dict(baseline); missing.pop(next(iter(missing)))
    with pytest.raises(ValueError, match='coverage'):
        c.final_report(data, missing, adapters, p)


@pytest.mark.parametrize('deltas', [[3, -1, 2, 0], [0, 0], [6]*7, [-3, -6, 9]])
def test_exact_group_distribution_against_enumeration(deltas):
    observed = abs(sum(deltas))
    brute = sum(abs(sum(a*b for a, b in zip(signs, deltas))) >= observed
                for signs in itertools.product((-1, 1), repeat=len(deltas)))/2**len(deltas)
    assert c.exact_group_test(deltas) == brute


def test_guardrail_first_then_challenge_then_earliest_selection():
    def entry(epoch, guard, challenge, basic=1., f1=.8):
        return {'epoch': epoch, 'metrics': {'guardrails_pass': guard, 'datasets': {
            'basic': {'adapter': {'accuracy': basic}},
            'challenge': {'adapter': {'accuracy': challenge, 'macro_f1': f1}}}}}
    a, b = entry(1, False, 1.), entry(2, True, .8)
    assert max([a, b], key=c.selection_key) is b
    assert max([entry(3, True, .8), entry(1, True, .8)], key=c.selection_key)['epoch'] == 1


def test_active_package_and_runner_exclude_original_test():
    package = (c.ROOT/'scripts/package_finetune27b_v2.py').read_text()
    assert "for d in ('basic', 'challenge')" in package and '/dev.jsonl' in package
    run = (c.ROOT/'src/ab_factcheck/finetune27b_run_v2.py').read_text()
    assert '/test.jsonl' not in run
