"""Independently reconstruct V10 decisions/metrics from immutable responses."""
from collections import Counter
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import jsonschema

from ab_factcheck.common import ROOT, LABELS, atomic_json, file_hash, now
from ab_factcheck.macro_search_v10 import EXP, OUT, ARMS, checked, verify
from ab_factcheck.search_v9 import verify as verify_v9, historic, checked as checked_v9


def label(arm, r):
    if r['finish_reason'] != 'stop' or r['provider_validation_issues']:
        return 'INVALID'
    try:
        obj=json.loads(r['raw_response'])
        jsonschema.validate(obj,r['request_payload']['response_format']['json_schema']['schema'])
    except (ValueError,TypeError,jsonschema.ValidationError):
        return 'INVALID'
    if arm == 'baseline':return obj['verdict']
    if arm == 'compatibility':
        if obj['true_possible'] and obj['false_possible']:return 'NOT ENOUGH INFO'
        if obj['true_possible']:return 'SUPPORTS'
        if obj['false_possible']:return 'REFUTES'
        return 'INVALID'
    return {'ENTAILMENT':'SUPPORTS','CONTRADICTION':'REFUTES','NEUTRAL':'NOT ENOUGH INFO'}[obj['relation']]


def main():
    p,f=verify(); old,old_f=verify_v9();directory=ROOT/EXP
    complete=json.loads((directory/'completion.json').read_text(encoding='utf-8'))
    gold={};groups={}
    for d in ('basic','challenge'):
        for line in (ROOT/f'data/splits/v1/{d}/dev.jsonl').read_text(encoding='utf-8').splitlines():
            row=json.loads(line);gold[d,row['id']]=row
    lookup={}
    for stage in ('pilot','scout','confirm'):
        for row in p[stage]:
            key=row['dataset'],row['id'];lookup[key]=row
            assert set(row)=={'dataset','id','group','mechanism','claim','evidence'}
            assert all(v==gold[key][k] for k,v in row.items() if k!='dataset')
    for d in ('basic','challenge'):
        rows=[r for r in p['pilot'] if r['dataset']==d]
        counts=Counter(gold[d,r['id']]['label'] for r in rows)
        assert len(rows)==len({r['mechanism'] for r in rows})==7 and sorted(counts.values())==[2,2,3]
    confirm_groups={(r['dataset'],r['group']) for r in p['confirm']}
    excluded={tuple(k) for k in old['excluded_groups']} | {(r['dataset'],r['group']) for r in old['confirm']}
    assert len(confirm_groups)==14 and not confirm_groups & excluded
    raw={};tokens=0;hashes={};invalid=Counter()
    pilot_keys={(r['dataset'],r['id']) for r in p['pilot']}
    confirm_keys={(r['dataset'],r['id']) for r in p['confirm']}
    for path in (ROOT/OUT/'records').glob('*/*/*.json'):
        if path.stem not in (*ARMS,'baseline','incumbent'):continue
        key=path.parent.parent.name,path.parent.name;arm=path.stem
        r=checked(path,arm,lookup[key],f)
        assert r['raw_response']==r['response_json']['choices'][0]['message']['content']
        assert datetime.fromisoformat(r['requested_at']) >= datetime.fromisoformat(p['frozen_at'])
        if key in confirm_keys:
            assert datetime.fromisoformat(r['requested_at']).timestamp() >= (directory/'winner.json').stat().st_mtime
        elif key not in pilot_keys:
            assert datetime.fromisoformat(r['requested_at']).timestamp() >= (directory/'shortlist.json').stat().st_mtime
        raw[key,arm]=r;tokens+=r['usage']['total_tokens'];invalid[arm]+=int(label(arm,r)=='INVALID')
        hashes[path.relative_to(ROOT).as_posix()]=file_hash(path)
    assert len(raw)==complete['new_responses'] and tokens==complete['actual_tokens']
    assert hashes==complete['raw_sha256']
    if complete['status']=='futility_stop':
        assert not any(k in confirm_keys for k,a in raw)
    stages=[]
    for stage in ('pilot','scout','confirm'):
        metrics_path=directory/stage/'metrics.json'
        if not metrics_path.exists():continue
        stages.append(stage);m=json.loads(metrics_path.read_text(encoding='utf-8'))
        with (directory/stage/'predictions.csv').open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
        assert len(rows)==len(p[stage])==m['n']
        assert {(r['dataset'],r['id']) for r in rows}=={(r['dataset'],r['id']) for r in p[stage]}
        for row in rows:
            key=row['dataset'],row['id'];assert row['gold']==gold[key]['label']
            assert row['group']==gold[key]['group']
            predictions={a:label(a,r) for (k,a),r in raw.items() if k==key}
            if stage!='confirm':
                predictions['baseline']=historic(lookup[key])['baseline']
                path=ROOT/'outputs/search_v9/records'/key[0]/key[1]/'reason_first_nli.json'
                predictions['incumbent']=label('incumbent',checked_v9(path,'reason_first_nli',lookup[key],old_f))
            for method in m['methods']:
                if method.startswith('agree__'):
                    new=predictions[method[7:]]
                    expected=new if new in LABELS and new==predictions['incumbent'] else predictions['baseline']
                else:expected=predictions[method]
                assert row[method]==expected
        for method,e in m['methods'].items():
            for d in ('basic','challenge'):
                subset=[r for r in rows if r['dataset']==d];saved=e['metrics'][d]
                correct=sum(r[method]==r['gold'] for r in subset)
                assert saved['correct']==correct and saved['accuracy']==correct/len(subset)
                f1s=[]
                for target in LABELS:
                    n=sum(r['gold']==target for r in subset);np=sum(r[method]==target for r in subset)
                    tp=sum(r['gold']==target and r[method]==target for r in subset)
                    assert saved['classes'][target]['support']==n
                    assert saved['classes'][target]['recall']==(tp/n if n else None)
                    if n:f1s.append(2*tp/(n+np))
                assert abs(saved['macro_f1']-sum(f1s)/len(f1s))<1e-12
                for control in ('baseline','incumbent'):
                    pair=e['paired'][control][d]
                    assert pair['improved']==sum(r[method]==r['gold'] and r[control]!=r['gold'] for r in subset)
                    assert pair['harmed']==sum(r[method]!=r['gold'] and r[control]==r['gold'] for r in subset)
    secrets=[s.split('=',1)[1].strip().strip('\"\'') for s in (ROOT/'.env.local').read_text(encoding='utf-8-sig').splitlines() if s.startswith('GROQ_API_KEY=')]
    files=[Path(__file__),ROOT/'src/ab_factcheck/macro_search_v10.py',ROOT/'tests/test_macro_search_v10.py']
    files += [q for folder in (ROOT/EXP,ROOT/OUT) for q in folder.rglob('*') if q.is_file()]
    for path in files:
        contents=path.read_bytes()
        assert not any(s and s.encode() in contents for s in secrets)
        assert not re.search(rb'\bgsk_[A-Za-z0-9_-]{20,}',contents)
    report={'passed':True,'audited_at':now(),'completed_stages':stages,'new_responses':len(raw),'tokens':tokens,
        'invalid_by_arm':dict(invalid),'exact_payloads_verified':True,'nonthinking_observable_checks_passed':True,
        'independent_label_and_metric_reconstruction':True,'historical_group_overlap':0,'test_files_read':False,
        'script_sha256':file_hash(Path(__file__)),'completion_sha256':file_hash(directory/'completion.json')}
    atomic_json(directory/'audit.json',report);print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
