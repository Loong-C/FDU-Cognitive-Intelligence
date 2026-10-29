"""Independent CSV, raw-payload, complete-group and primary-test audit for V11."""
from collections import Counter, defaultdict
import csv
from datetime import datetime
import itertools
import json
import math
from pathlib import Path

import jsonschema

from ab_factcheck.common import ROOT, LABELS, atomic_bytes, atomic_json, file_hash, now
from ab_factcheck.intranet_client import key_value
from ab_factcheck.server_search_v11 import EXP, OUT, ARMS, CHOICES, checked, verify


def independent_parse(arm, r):
    if r['finish_reason']!='stop' or r['provider_validation_issues']:return 'INVALID',None
    if arm in CHOICES:
        letter=r['raw_response'].strip();index=int(arm[-1]);order=LABELS[index:]+LABELS[:index]
        if letter not in 'ABC' or len(letter)!=1:return 'INVALID',None
        nodes=r['response_json']['choices'][0].get('logprobs',{}).get('content',[])
        if not nodes or nodes[0]['token']!=letter:return 'INVALID',None
        logs={x['token']:x['logprob'] for x in nodes[0]['top_logprobs']}
        if not all(c in logs and math.isfinite(logs[c]) and logs[c]>-1000 for c in 'ABC'):return 'INVALID',None
        weights=[math.exp(logs[c]) for c in 'ABC'];total=sum(weights)
        return order['ABC'.index(letter)],dict(zip(order,(w/total for w in weights)))
    try:
        obj=json.loads(r['raw_response'])
        jsonschema.validate(obj,r['request_payload']['response_format']['json_schema']['schema'])
    except (ValueError,TypeError,jsonschema.ValidationError):return 'INVALID',None
    return (obj['verdict'] if arm=='baseline' else {'ENTAILMENT':'SUPPORTS','CONTRADICTION':'REFUTES','NEUTRAL':'NOT ENOUGH INFO'}[obj['relation']]),None


def independent_method(method, p):
    flip={'SUPPORTS':'REFUTES','REFUTES':'SUPPORTS','NOT ENOUGH INFO':'NOT ENOUGH INFO','INVALID':'INVALID'}
    if method in ARMS:return p[method][0]
    if method=='signed_gate':
        n=p['nli'][0]
        return n if n in LABELS and n==flip[p['negative'][0]] else p['baseline'][0]
    if method=='majority':
        votes=[p['nli'][0],p['contrast'][0],independent_method('pos_pool',p),independent_method('neg_pool',p)]
        counts=Counter(x for x in votes if x in LABELS)
        if not counts:return 'INVALID'
        tied=[label for label in LABELS if counts[label]==max(counts.values())]
        return p['nli'][0] if p['nli'][0] in tied else tied[0]
    keys=([f'pos{i}' for i in range(3)] if method=='pos_pool' else [f'neg{i}' for i in range(3)] if method=='neg_pool' else list(CHOICES))
    if any(p[k][1] is None for k in keys):return 'INVALID'
    scores={l:sum(p[k][1][flip[l] if k.startswith('neg') else l] for k in keys)/len(keys) for l in LABELS}
    return max(LABELS,key=lambda l:scores[l])


def main():
    plan,f=verify();directory=ROOT/EXP
    assessment=json.loads((directory/'assessment.json').read_text(encoding='utf-8'))
    winner=assessment['winner'];source={};members=defaultdict(set)
    for d in ('basic','challenge'):
        for line in (ROOT/f'data/splits/v1/{d}/dev.jsonl').read_text(encoding='utf-8').splitlines():
            r=json.loads(line);source[d,r['id']]=r;members[d,r['group']].add(r['id'])
    lookup={};selected=defaultdict(set)
    for stage in ('screen','expand','confirm'):
        for r in plan[stage]:
            key=r['dataset'],r['id'];lookup[key]=r
            assert set(r)=={'dataset','id','group','mechanism','claim','evidence'}
            assert all(v==source[key][k] for k,v in r.items() if k!='dataset')
            if stage=='confirm':selected[r['dataset'],r['group']].add(r['id'])
    assert all(ids==members[g] for g,ids in selected.items())
    assert len(selected)==28 and not set(selected)&{tuple(k) for k in plan['excluded_groups']}
    assert not set(selected)&{(r['dataset'],r['group']) for r in plan['screen']+plan['expand']}
    raw={};hashes={};tokens=Counter();counts=Counter();invalid=Counter()
    conf={(r['dataset'],r['id']) for r in plan['confirm']};exp={(r['dataset'],r['id']) for r in plan['expand']}
    for path in (ROOT/OUT/'records').glob('*/*/*.json'):
        if path.stem not in ARMS:continue
        key=path.parent.parent.name,path.parent.name;arm=path.stem;r=checked(path,arm,lookup[key],f)
        assert r['response_json']['choices'][0]['message']['content']==r['raw_response']
        assert datetime.fromisoformat(r['requested_at'])>=datetime.fromisoformat(plan['frozen_at'])
        if key in conf:assert datetime.fromisoformat(r['requested_at']).timestamp()>=(directory/'winner.json').stat().st_mtime
        elif key in exp:assert datetime.fromisoformat(r['requested_at']).timestamp()>=(directory/'shortlist.json').stat().st_mtime
        raw[key,arm]=independent_parse(arm,r);counts[arm]+=1;tokens[arm]+=r['usage']['total_tokens'];invalid[arm]+=int(raw[key,arm][0]=='INVALID')
        hashes[path.relative_to(ROOT).as_posix()]=file_hash(path)
    all_rows={};reports={}
    for stage in ('screen','expand','confirm'):
        m=json.loads((directory/stage/'metrics.json').read_text(encoding='utf-8'));reports[stage]=m
        with (directory/stage/'predictions.csv').open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
        all_rows[stage]=rows
        assert len(rows)==len(plan[stage])==m['n'] and {(r['dataset'],r['id']) for r in rows}=={(r['dataset'],r['id']) for r in plan[stage]}
        for row in rows:
            key=row['dataset'],row['id'];assert row['gold']==source[key]['label'] and row['group']==source[key]['group']
            p={a:r for (k,a),r in raw.items() if k==key}
            for method in m['methods']:assert row[method]==independent_method(method,p)
        for method,e in m['methods'].items():
            for d in ('basic','challenge'):
                sample=[r for r in rows if r['dataset']==d];metric=e['metrics'][d]
                correct=sum(r[method]==r['gold'] for r in sample)
                assert metric['correct']==correct and metric['accuracy']==correct/len(sample)
                f1=[]
                for l in LABELS:
                    n=sum(r['gold']==l for r in sample);np=sum(r[method]==l for r in sample);tp=sum(r[method]==l and r['gold']==l for r in sample)
                    assert metric['classes'][l]['support']==n and metric['classes'][l]['recall']==(tp/n if n else None)
                    if n:f1.append(2*tp/(n+np))
                assert abs(metric['macro_f1']-sum(f1)/len(f1))<1e-12
                assert e['paired'][d]['improved']==sum(r[method]==r['gold'] and r['baseline']!=r['gold'] for r in sample)
                assert e['paired'][d]['harmed']==sum(r[method]!=r['gold'] and r['baseline']==r['gold'] for r in sample)
    # Enumerate group sign flips without using the experiment's statistics implementation.
    for d in ('basic','challenge'):
        differences=defaultdict(int)
        subset=[r for r in all_rows['confirm'] if r['dataset']==d]
        for r in subset:differences[r['group']]+=int(r[winner]==r['gold'])-int(r['baseline']==r['gold'])
        v=list(differences.values());observed=sum(v)
        distribution=[sum(value if bit else -value for value,bit in zip(v,mask)) for mask in itertools.product((0,1),repeat=len(v))]
        p=sum(x>=observed for x in distribution)/len(distribution)
        assert assessment['statistics'][d]['one_sided_group_permutation_p']==p
        assert assessment['statistics'][d]['accuracy_delta']==observed/len(subset)
    guards=True;e=reports['confirm']['methods'][winner]
    for d in ('basic','challenge'):
        a,b=e['metrics'][d],e['baseline_metrics'][d]
        guards &= a['macro_f1']-b['macro_f1']>=(-.02 if d=='basic' else 0)-1e-12
        if d=='basic':guards &= a['accuracy']-b['accuracy']>=-.02-1e-12
        guards &= all(a['classes'][l]['recall']-b['classes'][l]['recall']>=-.05-1e-12 for l in LABELS)
    success=guards and assessment['statistics']['challenge']['accuracy_delta']>=.05 and assessment['statistics']['challenge']['one_sided_group_permutation_p']<=.025
    assert bool(success)==assessment['primary_and_guardrails_passed']
    secret=key_value()
    paths=[Path(__file__),ROOT/'src/ab_factcheck/intranet_client.py',ROOT/'src/ab_factcheck/server_search_v11.py']
    paths += [p for folder in (ROOT/EXP,ROOT/OUT) for p in folder.rglob('*') if p.is_file()]
    assert all(secret.encode() not in p.read_bytes() for p in paths)
    assert not list((ROOT/OUT/'records').glob('*/*/*.inflight'))
    audit={'passed':True,'at':now(),'winner':winner,'success':bool(success),'raw_responses':sum(counts.values()),'tokens':sum(tokens.values()),'tokens_by_arm':dict(tokens),'counts_by_arm':dict(counts),'invalid_by_arm':dict(invalid),
        'exact_payloads_and_nonthinking_verified':True,'complete_group_membership':True,'confirmation_groups':28,'prior_group_overlap':0,
        'independent_decisions_metrics_and_primary_test':True,'test_files_read':False,'secret_scan_passed':True,'raw_sha256':hashes,'script_sha256':file_hash(Path(__file__))}
    atomic_json(directory/'audit.json',audit)
    lines=['# V11 服务器实验结果','',f"候选：`{winner}`；冻结的统计成功标准：{'通过' if success else '未通过'}。",'',
        f"新增 {sum(counts.values())} 个正式响应，{sum(tokens.values()):,} tokens（不含能力探针）；均来自内网 Qwen-27B 非思考模式。原始响应与指标独立审计通过。",'']
    for stage in ('screen','expand','confirm'):
        lines += ['## '+stage,'','| 方法 | Basic | Challenge |','|---|---:|---:|']
        for method,entry in reports[stage]['methods'].items():
            a,b=(entry['metrics'][d] for d in ('basic','challenge'))
            lines.append(f"| {method} | {a['correct']}/{a['n']} | {b['correct']}/{b['n']} |")
        lines.append('')
    lines += ['## 冻结候选的独立确认','', '| 数据集 | 准确率差 | 修正/损害 | 单侧组置换 p |','|---|---:|---:|---:|']
    for d in ('basic','challenge'):
        s=assessment['statistics'][d];paired=e['paired'][d]
        lines.append(f"| {d} | {s['accuracy_delta']*100:+.2f} pp | {paired['improved']}/{paired['harmed']} | {s['one_sided_group_permutation_p']:.6f} |")
    lines += ['',f"主检验 alpha=0.025；挑战集最低增益=5 pp；其他指标幅度限制通过：{bool(guards)}。详细类别召回、混淆矩阵及组 bootstrap 区间在 confirm/metrics.json、assessment.json。",'',
        '确认集为事前固定的 28 个完整新开发组，基础集 120 题、挑战集 83 题。结果只支持此独立开发确认；测试集未读取，不能声称测试集提升或总体统计非劣。', '',
        'A/B/C 选项概率是受约束 token 概率，不是事实正确率。后端与旧 Groq 不同，因此所有正式对照均在本服务器重跑，旧结果只作历史参考。','']
    atomic_bytes(directory/'RESULTS.md','\n'.join(lines).encode('utf-8'))
    print(json.dumps({k:v for k,v in audit.items() if k!='raw_sha256'},ensure_ascii=False))


if __name__=='__main__':main()
