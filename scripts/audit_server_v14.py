"""Independent audit of old-development-only binary follow-up; no primary test."""
from collections import Counter
import csv
from datetime import datetime
import json
from pathlib import Path

import jsonschema

from ab_factcheck.common import ROOT, LABELS, atomic_bytes, atomic_json, file_hash, now
from ab_factcheck.intranet_client import key_value
from ab_factcheck.semantic_binary_v14 import EXP, OUT, checked, verify
from ab_factcheck.server_search_v11 import checked as checked11, verify as verify11
from ab_factcheck.binary_bilingual_v13 import checked as checked13, verify as verify13
from audit_server_v11 import independent_parse
from audit_server_v13 import independent_binary, validate_metrics


def independent_decision(method,p):
    if method in ('baseline','nli'):return p[method]
    if method.startswith('direct_'):
        t=int(method.split('_')[1])/100
        bits=[None if p[k] is None else p[k]>=t for k in ('binary_pos','direct_contrad')]
    else:bits=[p[k] for k in ('proof_entail','proof_contrad')]
    if None in bits:result=p['nli']
    else:result={(True,False):'SUPPORTS',(False,True):'REFUTES',(False,False):'NOT ENOUGH INFO',(True,True):p['nli']}[tuple(bits)]
    if method=='proof_gate':return p['nli'] if result==p['nli'] and result in LABELS else p['baseline']
    return result


def eligible(e,margin):
    a,b,old=e['metrics'],e['baseline_metrics'],e['nli_metrics']
    if a['challenge']['correct']-old['challenge']['correct']<margin or old['basic']['correct']-a['basic']['correct']>1:return False
    if a['basic']['accuracy']<b['basic']['accuracy']-.02-1e-12 or a['basic']['macro_f1']<b['basic']['macro_f1']-.02-1e-12:return False
    if a['challenge']['macro_f1']<b['challenge']['macro_f1']-1e-12:return False
    return all(a[d]['classes'][l]['recall']>=b[d]['classes'][l]['recall']-.05-1e-12 for d in ('basic','challenge') for l in LABELS)


def main():
    p,f=verify();_,f11=verify11();p13,f13=verify13();directory=ROOT/EXP
    result=json.loads((directory/'assessment.json').read_text(encoding='utf-8'))
    assert not result['independent_confirmation'] and not result['statistical_success_claimed'] and not result['test_access']
    assert p['screen']==p13['screen'] and p['expand']==p13['expand']
    assert not {(r['dataset'],r['group']) for r in p['screen']+p['expand']}&{(r['dataset'],r['group']) for r in p13['confirm']}
    source={}
    for d in ('basic','challenge'):
        for line in (ROOT/f'data/splits/v1/{d}/dev.jsonl').read_text(encoding='utf-8').splitlines():
            row=json.loads(line);source[d,row['id']]=row
    reports={};hashes={};cost=Counter();counts=Counter();invalid=Counter()
    for stage in ('screen','expand') if result['expanded'] else ('screen',):
        report=json.loads((directory/stage/'metrics.json').read_text(encoding='utf-8'));reports[stage]=report
        with (directory/stage/'predictions.csv').open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
        saved={(r['dataset'],r['id']):r for r in rows};assert len(rows)==len(saved)==len(p[stage])==report['n']
        stage_hashes={};stage_cost=Counter()
        for item in p[stage]:
            key=item['dataset'],item['id'];row=saved[key];src=source[key]
            assert set(item)=={'dataset','id','group','mechanism','claim','evidence'} and all(item[k]==src[k] for k in item if k!='dataset')
            assert row['gold']==src['label'] and row['group']==src['group']
            prefix=f"/records/{item['dataset']}/{item['id']}/";preds={}
            for name in [path for path in report['raw_sha256'] if prefix in path]:
                path=ROOT/name;arm=path.stem;old=arm in ('baseline','nli');binary_cache=stage=='screen' and arm=='binary_pos'
                r=checked11(path,arm,item,f11) if old else checked13(path,arm,item,f13) if binary_cache else checked(path,arm,item,f)
                assert r['raw_response']==r['response_json']['choices'][0]['message']['content']
                if arm in ('baseline','nli'):answer=independent_parse(arm,r)[0]
                elif arm in ('binary_pos','direct_contrad'):answer=independent_binary(r)
                else:
                    answer=None
                    if r['finish_reason']=='stop' and not r['provider_validation_issues']:
                        try:
                            obj=json.loads(r['raw_response']);jsonschema.validate(obj,r['request_payload']['response_format']['json_schema']['schema']);answer=obj['answer']=='YES'
                        except (ValueError,TypeError,jsonschema.ValidationError):pass
                preds[arm]=answer;stage_hashes[name]=file_hash(path)
                if not old and not binary_cache:
                    stamp=datetime.fromisoformat(r['requested_at']).timestamp();assert stamp>=datetime.fromisoformat(p['frozen_at']).timestamp()
                    if stage=='expand':assert stamp>=(directory/'selection.json').stat().st_mtime
                    stage_cost[arm]+=r['usage']['total_tokens']
                    if name not in hashes:
                        hashes[name]=stage_hashes[name];cost[arm]+=r['usage']['total_tokens'];counts[arm]+=1;invalid[arm]+=int(answer is None)
            for method in report['methods']:assert row[method]==independent_decision(method,preds)
        assert stage_hashes==report['raw_sha256'] and dict(stage_cost)==report['new_tokens']
        for method,entry in report['methods'].items():
            for d in ('basic','challenge'):
                subset=[r for r in rows if r['dataset']==d]
                for m,key in ((method,'metrics'),('baseline','baseline_metrics'),('nli','nli_metrics')):validate_metrics(subset,m,entry[key][d])
                for control in ('baseline','nli'):
                    pair=entry['paired'][control][d]
                    assert pair['improved']==sum(r[method]==r['gold'] and r[control]!=r['gold'] for r in subset)
                    assert pair['harmed']==sum(r[method]!=r['gold'] and r[control]==r['gold'] for r in subset)
    choices=[m for m in p['methods'] if eligible(reports['screen']['methods'][m],2)]
    winner=min(choices,key=lambda m:(-reports['screen']['methods'][m]['metrics']['challenge']['accuracy'],-reports['screen']['methods'][m]['metrics']['basic']['accuracy'],-reports['screen']['methods'][m]['metrics']['challenge']['macro_f1'],m)) if choices else None
    selection=json.loads((directory/'selection.json').read_text(encoding='utf-8'))
    assert selection['screen_sha256']==file_hash(directory/'screen/metrics.json') and selection['method']==result['selected']==winner
    assert result['expanded']==bool(winner) and result['exploratory_promising']==(bool(eligible(reports['expand']['methods'][winner],1)) if winner else False)
    secret=key_value();files=[Path(__file__),ROOT/'src/ab_factcheck/semantic_binary_v14.py']+[q for folder in (ROOT/EXP,ROOT/OUT) for q in folder.rglob('*') if q.is_file()]
    assert all(secret.encode() not in q.read_bytes() for q in files)
    assert not list((ROOT/OUT/'records').glob('*/*/*.inflight'))
    assert set(hashes)=={q.relative_to(ROOT).as_posix() for q in (ROOT/OUT/'records').glob('*/*/*.json') if not q.name.endswith('.error.json')}
    audit={'passed':True,'at':now(),'new_responses':sum(counts.values()),'new_tokens':sum(cost.values()),'counts_by_arm':dict(counts),'invalid_by_arm':dict(invalid),
        'independent_decisions_metrics_and_selection_verified':True,'exact_requests_and_nonthinking_verified':True,'only_old_development_groups':True,
        'independent_confirmation':False,'test_files_read':False,'secret_scan_passed':True,'raw_sha256':hashes,'script_sha256':file_hash(Path(__file__))}
    atomic_json(directory/'audit.json',audit)
    lines=['# V14 直接矛盾与简短依据二元分解结果','',f"新增 {sum(counts.values())} 次响应、{sum(cost.values()):,} tokens，独立复算通过。扩展候选：`{winner}`。全部是旧开发组探索，不作统计显著性或独立确认声明。",'']
    for stage,report in reports.items():
        lines+=['## '+stage,'','| 方法 | Basic | Challenge |','|---|---:|---:|']
        for method,entry in report['methods'].items():
            a,b=(entry['metrics'][d] for d in ('basic','challenge'));lines.append(f"| {method} | {a['correct']}/{a['n']} | {b['correct']}/{b['n']} |")
        lines.append('')
    lines += [f"按冻结规则是否值得继续独立验证：{result['exploratory_promising']}。若没有候选达到初筛的挑战 +2 题及其他指标限制，本轮按规则停止，保留全部失败结果。",'',
        'V13 的固定 NLI 确认没有因本轮探索更换方法或调参。所用正/反命题定义适用于所有输入，没有按机制或具体题目路由。模型为 Qwen-27B 非思考模式，无训练；测试集未读取。','']
    atomic_bytes(directory/'RESULTS.md','\n'.join(lines).encode('utf-8'))
    print(json.dumps({k:v for k,v in audit.items() if k!='raw_sha256'},ensure_ascii=False))


if __name__=='__main__':main()
