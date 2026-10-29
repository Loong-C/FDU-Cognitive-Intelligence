"""离线独立复算v3全量结果与历史版本逐条变化；不改标签或原始响应。"""
from pathlib import Path
import collections
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import prompt_v3_full as run
from api_client import load_key
from benchmark import messages_for, parse_response, read_sources, sha, write_json

OUT=run.OUT
LABELS=('SUPPORTS','REFUTES','NOT ENOUGH INFO')


def metrics(rows,records):
    columns=LABELS+('PARSE_ERROR','REQUEST_ERROR','PENDING')
    matrix={gold:{pred:0 for pred in columns} for gold in LABELS}
    for row in rows:
        r=records.get(row['id'])
        p=r.get('prediction') if r else None
        if p not in LABELS:p={'parse_error':'PARSE_ERROR','request_error':'REQUEST_ERROR','pending':'PENDING'}[r['status'] if r else 'pending']
        matrix[row['label']][p]+=1
    per={}
    for label in LABELS:
        tp=matrix[label][label];support=sum(matrix[label].values());predicted=sum(matrix[g][label] for g in LABELS)
        per[label]={'precision':tp/predicted if predicted else 0,'recall':tp/support,'f1':2*tp/(support+predicted)}
    correct=sum(matrix[g][g] for g in LABELS)
    return {'count':len(rows),'correct':correct,'accuracy':correct/len(rows),
            'macro_f1':sum(p['f1'] for p in per.values())/3,'per_class':per,'matrix':matrix}


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    datasets,_,audit=read_sources();rows=datasets['challenge']
    m=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
    s=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
    v3=run.read_unique(OUT/'challenge.jsonl')
    old={name:run.read_unique(path) for name,path in run.COMPARATORS.items()}
    assert len(rows)==885 and len(v3)==885 and set(v3)=={r['id'] for r in rows} and s['complete']
    assert m['settings']['data_audit']==audit
    assert m['settings']['selected_ids']==[r['id'] for r in rows]
    assert (OUT/'prompt-v3.txt').read_bytes()==(run.DRAFT/'prompt-v3.txt').read_bytes()
    assert sha((run.DRAFT/'prompt-v3.txt').read_bytes())==m['settings']['draft_prompt_file_sha256']
    assert sha((run.DRAFT/'draft-manifest.json').read_bytes())==m['settings']['draft_manifest_sha256']
    assert sha(m['settings']['prompt_template'].encode())==m['settings']['prompt_sha256']
    assert all(sha(path.read_bytes())==m['settings']['comparator_records_sha256'][name] for name,path in run.COMPARATORS.items())
    assert all(sha((ROOT/name).read_bytes())==value for name,value in m['settings']['code_hashes'].items())
    for row in rows:
        r=v3[row['id']]
        assert r['gold']==row['label'] and r['timestamp']>=m['created_at'] and r['evaluation_attempt']==1
        assert r['prompt_version']=='prompt-v3-frozen'
        if r['status']!='request_error':
            prediction,error,text=parse_response(r['raw_response'])
            assert (prediction,error,text)==(r['prediction'],r['parse_error'],r['raw_text'])
        with_sentinels={k:(value if k in ('evidence','claim') else 'LEAK_SENTINEL') for k,value in row.items()}
        assert messages_for(row,m['settings']['prompt_template'])==messages_for(with_sentinels,m['settings']['prompt_template'])
        assert all(records[row['id']]['gold']==row['label'] for records in old.values())
    independently={name:metrics(rows,records) for name,records in {**old,'prompt_v3':v3}.items()}
    for name,actual in independently.items():
        saved=s['scores'][name]
        for field in ('count','correct','accuracy','macro_f1'):assert abs(actual[field]-saved[field])<1e-12
        for label in LABELS:
            assert actual['matrix'][label]==saved['confusion_matrix'][label]
            for field in ('precision','recall','f1'):assert abs(actual['per_class'][label][field]-saved['per_class'][label][field])<1e-12
    transfers={}
    for name,previous in old.items():
        corrected=[r for r in rows if previous[r['id']]['prediction']!=r['label'] and v3[r['id']]['prediction']==r['label']]
        lost=[r for r in rows if previous[r['id']]['prediction']==r['label'] and v3[r['id']]['prediction']!=r['label']]
        t=s['comparisons'][name]['transitions']
        assert len(corrected)==t['wrong_to_correct'] and len(lost)==t['correct_to_wrong']
        assert len(corrected)-len(lost)==s['comparisons'][name]['correct_delta']
        transfers[name]={'corrected':len(corrected),'regressed':len(lost),'net':len(corrected)-len(lost)}
    key=load_key()
    key_found=bool(key) and any(key in path.read_text(encoding='utf-8-sig') for path in OUT.iterdir() if path.is_file())
    assert not key_found
    status=json.loads((OUT/'run_status.json').read_text(encoding='utf-8'))
    assert status['completed']==885 and status['stage']=='completed'
    residual=[r for r in rows if r['label']=='NOT ENOUGH INFO' and v3[r['id']]['prediction']=='REFUTES']
    report={'passed':True,'complete':True,'samples':885,'unique_ids':885,'all_fresh_evaluation_attempt_1':True,
            'prompt_matches_draft':True,'source_data_and_labels_unchanged':True,'historical_comparator_hashes_match':True,
            'frozen_code_hashes_match':True,'input_metadata_isolated':True,'raw_metrics_recomputed':True,
            'transitions':transfers,'residual_nei_to_refutes':len(residual),
            'residual_by_mechanism':dict(collections.Counter(r['mechanism'] for r in residual)),
            'key_found_in_outputs':key_found,'run_status':status}
    write_json(ROOT/'work'/'prompt_v3_full_verification.json',report)
    lines=['# Prompt-v3相对v2的变化与残留样本','',
           '原始标签保持不变，以下按金标准和预测变化选取，优先展示不同机制。引用v1与v3原始回答，供人工核验。','']
    previous=old['prompt_v2']
    pools=[('纠正样本',[r for r in rows if previous[r['id']]['prediction']!=r['label'] and v3[r['id']]['prediction']==r['label']]),
           ('退步样本',[r for r in rows if previous[r['id']]['prediction']==r['label'] and v3[r['id']]['prediction']!=r['label']]),
           ('残余NEI误反',residual)]
    for title,pool in pools:
        lines+=['## '+title,'',f'总数：{len(pool)}条。','']
        selected=[];seen=set()
        for row in sorted(pool,key=lambda r:(r['mechanism'],r['id'])):
            if row['mechanism'] not in seen and len(selected)<4:selected.append(row);seen.add(row['mechanism'])
        for row in sorted(pool,key=lambda r:r['id']):
            if len(selected)>=4:break
            if row not in selected:selected.append(row)
        for row in selected:
            i=row['id'];a,b=previous[i],v3[i]
            lines+=['### '+i,'',f"机制：{row['mechanism']}；金标准：{row['label']}；v1：{a['prediction']}；v3：{b['prediction']}。",'',
                    '**证据**','',row['evidence'],'','**陈述**','',row['claim'],'','**v1原始回答**','',a.get('raw_text','无原始文本'),'',
                    '**v3原始回答**','',b.get('raw_text','无原始文本'), '']
    (OUT/'变化与残留样本.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
