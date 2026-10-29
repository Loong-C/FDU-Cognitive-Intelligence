"""Independent raw-output, selection, metric, and exact group-test audit."""
from bisect import bisect_left
from collections import Counter, defaultdict
import csv
from datetime import datetime
import itertools
import json
import math
from pathlib import Path

from ab_factcheck.common import ROOT, LABELS, atomic_bytes, atomic_json, file_hash, now
from ab_factcheck.intranet_client import key_value
from ab_factcheck.binary_bilingual_v13 import EXP, OUT, checked, verify
from ab_factcheck.server_search_v11 import checked as checked_old, verify as verify_old
from audit_server_v11 import independent_parse


def independent_binary(r):
    if r['finish_reason']!='stop' or r['provider_validation_issues']:return None
    chosen=r['raw_response'].strip()
    tokens=r['response_json']['choices'][0].get('logprobs',{}).get('content',[])
    if chosen not in ('A','B') or not tokens or tokens[0]['token']!=chosen:return None
    logs={v['token']:v['logprob'] for v in tokens[0]['top_logprobs']}
    if any(k not in logs or not math.isfinite(logs[k]) or logs[k]<=-1000 for k in ('A','B')):return None
    # Logistic form independently checks the runner's normalized exponentials.
    delta=logs['B']-logs['A']
    if delta>=0:
        value=math.exp(-delta);return value/(1+value)
    return 1/(1+math.exp(delta))


def independent_prediction(method, answers):
    if method in ('baseline','nli','zh_nli'):return answers[method]
    if method=='agree_zh':
        if answers['nli']==answers['zh_nli'] and answers['nli'] in LABELS:return answers['nli']
        return answers['baseline']
    a,b=answers['binary_pos'],answers['binary_neg'];t=int(method.removeprefix('binary_'))/100
    if a is None or b is None:return answers['nli']
    states={(True,False):'SUPPORTS',(False,True):'REFUTES',(False,False):'NOT ENOUGH INFO',(True,True):answers['nli']}
    return states[a>=t,b>=t]


def independent_p(values):
    """Meet-in-the-middle enumeration, not the runner's integer convolution."""
    values=[v for v in values if v];mid=len(values)//2
    sums=[]
    for part in (values[:mid],values[mid:]):
        sums.append([sum(v*s for v,s in zip(part,signs)) for signs in itertools.product((-1,1),repeat=len(part))])
    left,right=sums;right.sort();observed=sum(values)
    return sum(len(right)-bisect_left(right,observed-v) for v in left)/(2**len(values))


def validate_metrics(rows,method,metric):
    correct=sum(r[method]==r['gold'] for r in rows)
    assert metric['n']==len(rows) and metric['correct']==correct and metric['accuracy']==correct/len(rows)
    assert metric['invalid']==sum(r[method] not in LABELS for r in rows)
    f1=[]
    for label in LABELS:
        ng=sum(r['gold']==label for r in rows);np=sum(r[method]==label for r in rows)
        tp=sum(r['gold']==label and r[method]==label for r in rows)
        assert metric['classes'][label]['support']==ng and metric['classes'][label]['recall']==(tp/ng if ng else None)
        if ng:f1.append(2*tp/(ng+np))
        for pred in (*LABELS,'INVALID'):
            assert metric['confusion_matrix'][label][pred]==sum(r['gold']==label and r[method]==pred for r in rows)
    assert abs(metric['macro_f1']-sum(f1)/len(f1))<1e-12


def independent_rank(e):
    a,b,old=e['metrics'],e['baseline_metrics'],e['nli_metrics']
    eligible=a['basic']['accuracy']>=b['basic']['accuracy']-.02-1e-12 and a['basic']['macro_f1']>=b['basic']['macro_f1']-.02-1e-12
    eligible=eligible and a['basic']['correct']>=old['basic']['correct']-1
    eligible=eligible and all(a[d]['classes'][l]['recall']>=b[d]['classes'][l]['recall']-.05-1e-12 for d in ('basic','challenge') for l in LABELS)
    calls=3 if e['method']=='agree_zh' or e['method'].startswith('binary_') else 1
    return (not eligible,-a['challenge']['accuracy'],-a['basic']['accuracy'],-a['challenge']['macro_f1'],e['method']!='nli',calls,e['method'])


def main():
    p,f=verify();_,old_f=verify_old();directory=ROOT/EXP
    assessment=json.loads((directory/'assessment.json').read_text(encoding='utf-8'));winner=assessment['winner']
    reserved=json.loads((directory/'reserved_confirmation.json').read_text(encoding='utf-8'))
    assert p['confirm']==reserved['rows'] and p['alpha']==.00625 and p['cumulative_alpha']==.04375
    source={};members=defaultdict(set)
    for d in ('basic','challenge'):
        for line in (ROOT/f'data/splits/v1/{d}/dev.jsonl').read_text(encoding='utf-8').splitlines():
            r=json.loads(line);source[d,r['id']]=r;members[d,r['group']].add(r['id'])
    selected=defaultdict(set)
    for stage in ('screen','expand','confirm'):
        for item in p[stage]:
            src=source[item['dataset'],item['id']]
            assert set(item)=={'dataset','id','group','mechanism','claim','evidence'}
            assert all(src[k]==item[k] for k in item if k!='dataset')
            if stage=='confirm':selected[item['dataset'],item['group']].add(item['id'])
    excluded={tuple(g) for g in p['excluded_groups']}
    assert set(selected)==set(members)-excluded and len(selected)==52
    assert all(ids==members[g] for g,ids in selected.items())
    assert not set(selected)&{(r['dataset'],r['group']) for r in p['screen']+p['expand']}
    mechanisms=Counter(r['mechanism'] for r in p['confirm'] if r['dataset']=='challenge')
    assert len(mechanisms)==6 and mechanisms['SETCLOSE']==0
    raw_hashes={};cost=Counter();counts=Counter();invalid=Counter();reports={};all_rows={}
    for stage in ('screen','expand','confirm'):
        report=json.loads((directory/stage/'metrics.json').read_text(encoding='utf-8'));reports[stage]=report
        with (directory/stage/'predictions.csv').open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
        all_rows[stage]=rows;lookup={(r['dataset'],r['id']):r for r in rows}
        assert len(rows)==len(lookup)==len(p[stage])==report['n']
        hashes={};new_tokens=Counter();cached=Counter()
        for item in p[stage]:
            key=item['dataset'],item['id'];saved=lookup[key]
            assert saved['gold']==source[key]['label'] and saved['group']==item['group']
            answers={}
            prefix=f"/records/{item['dataset']}/{item['id']}/"
            paths=[path for path in report['raw_sha256'] if prefix in path]
            for path_string in paths:
                path=ROOT/path_string;arm=path.stem;reuse=stage!='confirm' and arm in ('baseline','nli')
                r=checked_old(path,arm,item,old_f) if reuse else checked(path,arm,item,f)
                assert r['raw_response']==r['response_json']['choices'][0]['message']['content']
                if not reuse:
                    stamp=datetime.fromisoformat(r['requested_at']).timestamp()
                    assert stamp>=datetime.fromisoformat(p['frozen_at']).timestamp()
                    if stage=='expand':assert stamp>=(directory/'shortlist.json').stat().st_mtime
                    if stage=='confirm':assert stamp>=(directory/'winner.json').stat().st_mtime
                answer=independent_binary(r) if arm.startswith('binary_') else independent_parse('baseline' if arm=='baseline' else 'nli',r)[0]
                answers[arm]=answer;hashes[path_string]=file_hash(path)
                if reuse:cached[arm]+=1
                else:
                    new_tokens[arm]+=r['usage']['total_tokens']
                    if path_string not in raw_hashes:
                        raw_hashes[path_string]=hashes[path_string];cost[arm]+=r['usage']['total_tokens'];counts[arm]+=1;invalid[arm]+=int(answer is None or answer=='INVALID')
            for method in report['methods']:assert saved[method]==independent_prediction(method,answers)
        assert hashes==report['raw_sha256'] and dict(new_tokens)==report['new_tokens'] and dict(cached)==report['cached_controls']
        for method,e in report['methods'].items():
            for d in ('basic','challenge'):
                sample=[r for r in rows if r['dataset']==d]
                validate_metrics(sample,method,e['metrics'][d]);validate_metrics(sample,'baseline',e['baseline_metrics'][d]);validate_metrics(sample,'nli',e['nli_metrics'][d])
                for control in ('baseline','nli'):
                    pair=e['paired'][control][d]
                    assert pair['improved']==sum(r[method]==r['gold'] and r[control]!=r['gold'] for r in sample)
                    assert pair['harmed']==sum(r[method]!=r['gold'] and r[control]==r['gold'] for r in sample)
    shortlist=json.loads((directory/'shortlist.json').read_text(encoding='utf-8'))
    final=json.loads((directory/'winner.json').read_text(encoding='utf-8'))
    assert shortlist['screen_metrics_sha256']==file_hash(directory/'screen/metrics.json')
    assert final['expand_metrics_sha256']==file_hash(directory/'expand/metrics.json')
    chosen=min(p['screen_methods'],key=lambda m:independent_rank(reports['screen']['methods'][m]))
    assert shortlist['method']==chosen and final['method']==winner==min(('nli',chosen),key=lambda m:independent_rank(reports['expand']['methods'][m]))
    guards=True;e=reports['confirm']['methods'][winner]
    for d in ('basic','challenge'):
        sample=[r for r in all_rows['confirm'] if r['dataset']==d];groups=defaultdict(int)
        for r in sample:groups[r['group']]+=int(r[winner]==r['gold'])-int(r['baseline']==r['gold'])
        stats=assessment['statistics'][d]
        assert stats['group_net_correct']==dict(groups) and stats['one_sided_group_permutation_p']==independent_p(list(groups.values()))
        assert stats['accuracy_delta']==sum(groups.values())/len(sample)
        a,b=e['metrics'][d],e['baseline_metrics'][d]
        guards &= a['macro_f1']>=b['macro_f1']-(.02 if d=='basic' else 0)-1e-12
        if d=='basic':guards &= a['accuracy']>=b['accuracy']-.02-1e-12
        guards &= all(a['classes'][l]['recall']>=b['classes'][l]['recall']-.05-1e-12 for l in LABELS)
    stats=assessment['statistics']['challenge'];passed=guards and stats['accuracy_delta']>=.05 and stats['one_sided_group_permutation_p']<=p['alpha']
    assert bool(passed)==assessment['primary_and_guardrails_passed'] and bool(guards)==assessment['guardrails_passed']
    assert assessment['full_seven_mechanism_confirmation'] is False and assessment['test_access'] is False
    secret=key_value();files=[Path(__file__),ROOT/'src/ab_factcheck/binary_bilingual_v13.py']
    files += [q for folder in (ROOT/EXP,ROOT/OUT) for q in folder.rglob('*') if q.is_file()]
    assert all(secret.encode() not in q.read_bytes() for q in files)
    assert not list((ROOT/OUT/'records').glob('*/*/*.inflight'))
    assert set(raw_hashes)=={q.relative_to(ROOT).as_posix() for q in (ROOT/OUT/'records').glob('*/*/*.json') if not q.name.endswith('.error.json')}
    audit={'passed':True,'at':now(),'winner':winner,'primary_success':bool(passed),'new_responses':sum(counts.values()),'new_tokens':sum(cost.values()),
        'tokens_by_arm':dict(cost),'counts_by_arm':dict(counts),'invalid_by_arm':dict(invalid),'new_complete_groups':52,'challenge_mechanisms':dict(mechanisms),
        'independent_selection_labels_metrics_exact_test_verified':True,'exact_requests_and_nonthinking_verified':True,'prior_group_overlap':0,'test_files_read':False,
        'secret_scan_passed':True,'raw_sha256':raw_hashes,'script_sha256':file_hash(Path(__file__)),'assessment_sha256':file_hash(directory/'assessment.json')}
    atomic_json(directory/'audit.json',audit)
    lines=['# V13 双蕴含阈值与双语指令结果','',f"冻结候选 `{winner}`；预先设定的主标准：{'通过' if passed else '未通过'}。新增 {sum(counts.values())} 次正式响应、{sum(cost.values()):,} tokens，已逐条核对请求、非思考设置、决策、指标及独立组检验。",'']
    for stage,report in reports.items():
        lines+=['## '+stage,'','| 方法 | Basic | Challenge |','|---|---:|---:|']
        for m,entry in report['methods'].items():
            a,b=(entry['metrics'][d] for d in ('basic','challenge'));lines.append(f"| {m} | {a['correct']}/{a['n']} | {b['correct']}/{b['n']} |")
        lines.append('')
    lines+=['## 独立确认','', '| 数据集 | A27 | 方法 | 增益 | 修正/损害 | 单侧组置换 p |','|---|---:|---:|---:|---:|---:|']
    for d in ('basic','challenge'):
        a,b=e['metrics'][d],e['baseline_metrics'][d];s=assessment['statistics'][d];pair=e['paired']['baseline'][d]
        lines.append(f"| {d} | {b['accuracy']:.2%} | {a['accuracy']:.2%} | {s['accuracy_delta']*100:+.2f} pp | {pair['improved']}/{pair['harmed']} | {s['one_sided_group_permutation_p']:.8f} |")
    lines+=['',f"本轮 alpha=0.00625，累计分配 0.04375。其他指标幅度限制通过：{bool(guards)}。",'',
        '基础集 120 题/14 组；挑战集 236 题/38 组。保留挑战集覆盖六种机制，SETCLOSE 无剩余未使用组；本轮不是全部七机制的独立确认。先前轮次结果单独保留，不进行事后拼接主检验。测试集未读取，幅度限制不等于证明总体非劣。','',
        '## 各类召回率','','| 数据集 | 类别 | A27 | 方法 |','|---|---|---:|---:|']
    for d in ('basic','challenge'):
        for label in LABELS:
            a,b=e['metrics'][d]['classes'][label]['recall'],e['baseline_metrics'][d]['classes'][label]['recall']
            lines.append(f'| {d} | {label} | {b:.2%} | {a:.2%} |')
    atomic_bytes(directory/'RESULTS.md','\n'.join(lines+['']).encode('utf-8'))
    print(json.dumps({k:v for k,v in audit.items() if k!='raw_sha256'},ensure_ascii=False))


if __name__=='__main__':main()
