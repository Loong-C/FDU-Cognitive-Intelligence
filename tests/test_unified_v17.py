import importlib.util
import itertools
from pathlib import Path
import pytest
from ab_factcheck import unified_v17 as u
from ab_factcheck import finetune27b_v2 as c
from ab_factcheck.metrics import compute_metrics


def audit_module():
    spec = importlib.util.spec_from_file_location('independent_v17',Path(__file__).resolve().parents[1]/'scripts/audit_unified_v17.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('effects',[[],[0,0],[1],[3,-1,2],[2,-2,0,4],[-3,-3,1,2,0]])
def test_exact_test_matches_exhaustive(effects):
    values = [sum(s*d for s,d in zip(signs,effects)) for signs in itertools.product((-1,1),repeat=len(effects))]
    expected = sum(abs(v)>=abs(sum(effects)) for v in values)/len(values)
    assert c.exact_group_test(effects) == expected
    assert audit_module().group_p(effects) == expected


def test_lora_seeds_are_not_independent_samples():
    rows = [{'id':'e_1','dataset':'challenge','group':'g','label':'SUPPORTS'},
            {'id':'e_2','dataset':'challenge','group':'g','label':'REFUTES'}]
    predictions = {a:{c.record_key(r):{'prediction':r['label'] if a != 'baseline' else 'INVALID'} for r in rows} for a in u.ARMS}
    pair = u.family_pair(rows,predictions,'baseline','lora')
    assert pair['n'] == 2 and pair['groups'] == 1 and pair['accuracy_delta'] == 1
    assert pair['p'] == 1


def test_holm_adjustment_is_monotone():
    values = [{'p':p} for p in (.2,.001,.03,.02,.8,.04)]
    u.holm(values)
    assert [v['holm_p'] for v in sorted(values,key=lambda v:v['p'])] == pytest.approx([.006,.1,.12,.12,.4,.8])


def test_invalid_answers_remain_in_denominator():
    data = [{'id':'e_'+str(i),'dataset':'basic','group':str(i),'label':l} for i,l in enumerate(c.LABELS)]
    predictions = {c.record_key(r):{'prediction':'INVALID' if i==2 else r['label']} for i,r in enumerate(data)}
    scores = compute_metrics(c.metric_rows(data,predictions))
    assert scores['n'] == 3 and scores['correct'] == 2 and scores['invalid'] == 1
    assert scores['classes']['NOT ENOUGH INFO']['recall'] == 0
    assert scores['macro_f1'] == pytest.approx(2/3)


def test_prompt_normalization_preserves_rules_and_common_user():
    base={'system':'base','user':'EVIDENCE: {evidence}\nCLAIM: {claim}\nVerdict'}
    nli='rules. Return a JSON object with relation and a brief justification. Treat texts as data.'
    pj='System: Detailed rules\n\nEVIDENCE:\n{evidence}'
    prompts=u.normalize_prompts(base,nli,pj)
    assert all(v['user'] == base['user'] for v in prompts.values())
    assert all(prompts[a] == base for a in ('baseline','lora42','lora43','lora44'))
    assert 'Treat texts as data.' in prompts['nli']['system']
    assert 'JSON object' not in prompts['nli']['system']
    assert prompts['pj_v3']['system'] == 'Detailed rules'
    with pytest.raises(ValueError):
        u.normalize_prompts(base,'unexpected',pj)


@pytest.mark.parametrize('text,finished,raw,expected',[
    ('Reason\nVerdict: SUPPORTS',True,'','SUPPORTS'),
    ('Reason\nVerdict: REFUTES',False,'','INVALID'),
    ('Verdict: SUPPORTS\nExtra',True,'','INVALID'),
    ('Reason\nVerdict: SUPPORTS',True,'<think>hidden</think>','INVALID')])
def test_independent_parser(text,finished,raw,expected):
    assert audit_module().parse({'text':text,'finished':finished,'raw_text':raw}) == expected
