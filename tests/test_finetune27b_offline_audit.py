"""Synthetic receipts only; never model evaluation or production annotations."""
import importlib.util
from pathlib import Path

import pytest
from ab_factcheck import finetune27b_v2 as c

spec = importlib.util.spec_from_file_location('offline_audit',c.ROOT/'scripts/audit_finetune27b_v2.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def fixture_run(tmp_path, monkeypatch):
    root, run = tmp_path/'fixture_workspace', tmp_path/'fixture_run'
    monkeypatch.setattr(audit,'root',root)
    p={'prompt':{'system':'FIXTURE','user':'{evidence} {claim}'},'scope':'SYNTHETIC TEST FIXTURE',
       'guardrails':{'basic_accuracy_delta_min':-.02,'each_class_recall_delta_min':-.05}}
    monkeypatch.setattr(c,'verify_training',lambda:p)
    data=[dict(dataset=ds,id=f'{ds}-{i}',group=f'{ds}-g{i//3}',mechanism='fixture',label=label,
               evidence=f'Fixture evidence {ds}{i}',claim=f'Fixture claim {ds}{i}')
          for ds in ('basic','challenge') for i,label in enumerate(c.LABELS*2)]
    c.write_rows(root/c.EXP/'holdout.jsonl',data)
    selections={}
    for seed in c.SEEDS:
        path=run/f'seed-{seed}/selection.json'
        c.save(path,{'selected':{'epoch':1,'metrics':{'guardrails_pass':True}}})
        selections[str(seed)]=c.sha(path)
    identity={'fixture':True,'selections':selections}
    c.save(run/'holdout/identity.json',identity)
    predictions={}
    for arm in ('baseline','42','43','44'):
        arm_id={**identity,'arm':arm}
        c.save(run/f'holdout/{arm}/identity.json',arm_id)
        predictions[arm]={}
        for i,row in enumerate(data):
            label='REFUTES' if arm == 'baseline' and i == 0 else row['label']
            receipt={'identity':c.digest(arm_id),'text':'Fixture reason.\nVerdict: '+label,
                     'raw_text':'Fixture reason.\nVerdict: '+label,'prediction':label,'finished':True,
                     'thinking_generated':False,'status':'completed','reason_present':True,
                     'input_sha256':c.digest(c.messages(row,p['prompt'])),
                     'input_token_sha256':c.digest([1,2]),'input_tokens':2,'output_tokens':3,
                     'output_token_ids':[3,4,5],'seconds':1.}
            key=c.record_key(row)
            c.save(run/f'holdout/{arm}/{key}.json',receipt)
            predictions[arm][key]=receipt
    report=c.final_report(data,predictions['baseline'],{s:predictions[s] for s in ('42','43','44')},p)
    c.save(run/'results.json',{**report,'identity':identity})
    return run,data


def test_audit_recomputes_metrics_group_test_and_writes_report(tmp_path,monkeypatch):
    run,data=fixture_run(tmp_path,monkeypatch)
    result=audit.audit(run)
    assert result['passed']
    assert result['independent_counts_and_group_test']['basic']['correct']['baseline'] == 5
    assert (run/'predictions.csv').read_text().count('Fixture reason.') == 48
    assert 'Macro-F1' in (run/'RESULTS.md').read_text(encoding='utf-8')
    assert not list(tmp_path.rglob('test.jsonl'))


def test_audit_rejects_prediction_that_disagrees_with_received_text(tmp_path,monkeypatch):
    run,data=fixture_run(tmp_path,monkeypatch)
    path=run/f"holdout/42/{c.record_key(data[0])}.json"
    value=c.read_json(path);value['prediction']='REFUTES';c.save(path,value)
    with pytest.raises(AssertionError):
        audit.audit(run)


def test_local_recompute_preserves_received_bytes(tmp_path,monkeypatch):
    run,_=fixture_run(tmp_path,monkeypatch)
    audit.audit(run)
    before={p.relative_to(run):p.read_bytes() for p in run.rglob('*') if p.is_file()}
    spec=importlib.util.spec_from_file_location('local_recompute',c.ROOT/'scripts/recompute_finetune27b_v2.py')
    helper=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    destination=tmp_path/'independent_audit'
    result=helper.recompute(run,destination,audit.audit)
    assert result['passed'] and result['received_input_bytes_unchanged']
    assert before == {p.relative_to(run):p.read_bytes() for p in run.rglob('*') if p.is_file()}
    assert (destination/'audit.json').is_file()
    with pytest.raises(ValueError,match='overlap'):
        helper.recompute(run,run/'nested_audit',audit.audit)


def test_report_discloses_engineering_data_access_deviation(tmp_path,monkeypatch):
    run,_=fixture_run(tmp_path,monkeypatch)
    disclosure={'engineering_checks_read_original_benchmark':True,
                'model_training_selection_evaluation_use_original_test':False,
                'original_test_sealing_requirement_passed':False}
    c.save(audit.root/c.EXP/'data_access_audit.json',disclosure)
    result=audit.audit(run)
    assert result['passed'] and result['data_access_disclosure'] == disclosure
    assert result['data_access_disclosure_sha256'] == c.sha(audit.root/c.EXP/'data_access_audit.json')
    report=(run/'RESULTS.md').read_text(encoding='utf-8')
    assert '封存工程要求未完全通过' in report
    assert '原测试集未读取' not in report
