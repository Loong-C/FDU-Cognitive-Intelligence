"""Separate raw/metric and brute-force primary-test audit for fixed V12 NLI."""
from collections import defaultdict
import csv
from datetime import datetime
import itertools
import json
from pathlib import Path

from ab_factcheck.common import ROOT, LABELS, atomic_bytes, atomic_json, file_hash, now
from ab_factcheck.intranet_client import key_value
from ab_factcheck.server_replication_v12 import EXP, OUT, verify
from ab_factcheck.server_search_v11 import checked
from audit_server_v11 import independent_parse


def main():
    p,f=verify();directory=ROOT/EXP
    result=json.loads((directory/'assessment.json').read_text(encoding='utf-8'))
    source={};members=defaultdict(set)
    for d in ('basic','challenge'):
        for line in (ROOT/f'data/splits/v1/{d}/dev.jsonl').read_text(encoding='utf-8').splitlines():
            r=json.loads(line);source[d,r['id']]=r;members[d,r['group']].add(r['id'])
    with (directory/'predictions.csv').open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
    lookup={(r['dataset'],r['id']):r for r in rows}
    assert len(lookup)==len(rows)==len(p['rows'])==306
    selected=defaultdict(set);cost=defaultdict(int);hashes={};invalid=defaultdict(int)
    for item in p['rows']:
        key=item['dataset'],item['id'];saved=lookup[key];src=source[key]
        assert set(item)=={'dataset','id','group','mechanism','claim','evidence'}
        assert all(item[k]==src[k] for k in item if k!='dataset')
        assert saved['gold']==src['label'] and saved['group']==src['group']
        selected[item['dataset'],item['group']].add(item['id'])
        for arm in ('baseline','nli'):
            path=ROOT/OUT/'records'/item['dataset']/item['id']/(arm+'.json')
            r=checked(path,arm,item,f)
            assert r['raw_response']==r['response_json']['choices'][0]['message']['content']
            assert datetime.fromisoformat(r['requested_at'])>=datetime.fromisoformat(p['frozen_at'])
            answer=independent_parse(arm,r)[0];assert saved[arm]==answer
            cost[arm]+=r['usage']['total_tokens'];invalid[arm]+=int(answer=='INVALID');hashes[path.relative_to(ROOT).as_posix()]=file_hash(path)
    assert len(selected)==41 and all(ids==members[g] for g,ids in selected.items())
    assert not set(selected)&{tuple(g) for g in p['excluded_groups']}
    assert hashes==result['raw_sha256'] and dict(cost)==result['tokens']
    guards=True
    for d in ('basic','challenge'):
        sample=[r for r in rows if r['dataset']==d]
        for arm in ('baseline','nli'):
            m=result['methods'][arm][d];correct=sum(r[arm]==r['gold'] for r in sample)
            assert m['correct']==correct and m['accuracy']==correct/len(sample)
            f1=[]
            for label in LABELS:
                ng=sum(r['gold']==label for r in sample);np=sum(r[arm]==label for r in sample);tp=sum(r['gold']==label and r[arm]==label for r in sample)
                assert m['classes'][label]['support']==ng and m['classes'][label]['recall']==(tp/ng if ng else None)
                if ng:f1.append(2*tp/(ng+np))
            assert abs(m['macro_f1']-sum(f1)/len(f1))<1e-12
        groups=defaultdict(int)
        for r in sample:groups[r['group']]+=int(r['nli']==r['gold'])-int(r['baseline']==r['gold'])
        values=[v for v in groups.values() if v];observed=sum(values)
        extremes=sum(sum(v*s for v,s in zip(values,signs))>=observed for signs in itertools.product((-1,1),repeat=len(values)))
        expected=extremes/(2**len(values));stats=result['statistics'][d]
        assert stats['one_sided_group_permutation_p']==expected and stats['accuracy_delta']==observed/len(sample)
        pair=result['paired'][d]
        assert pair['improved']==sum(r['nli']==r['gold'] and r['baseline']!=r['gold'] for r in sample)
        assert pair['harmed']==sum(r['nli']!=r['gold'] and r['baseline']==r['gold'] for r in sample)
        a,b=(result['methods'][arm][d] for arm in ('nli','baseline'))
        guards &= a['macro_f1']>=b['macro_f1']-(.02 if d=='basic' else 0)-1e-12
        if d=='basic':guards &= a['accuracy']>=b['accuracy']-.02-1e-12
        guards &= all(a['classes'][l]['recall']>=b['classes'][l]['recall']-.05-1e-12 for l in LABELS)
    s=result['statistics']['challenge'];passed=guards and s['accuracy_delta']>=.05 and s['one_sided_group_permutation_p']<=.0125
    assert bool(passed)==result['primary_and_guardrails_passed'] and result['alpha_spent']==.0125
    secret=key_value();paths=[Path(__file__),ROOT/'src/ab_factcheck/server_replication_v12.py']
    paths += [q for folder in (ROOT/EXP,ROOT/OUT) for q in folder.rglob('*') if q.is_file()]
    assert all(secret.encode() not in q.read_bytes() for q in paths)
    assert not list((ROOT/OUT/'records').glob('*/*/*.inflight'))
    audit={'passed':True,'at':now(),'primary_success':bool(passed),'raw_responses':len(hashes),'tokens':sum(cost.values()),'invalid_by_arm':dict(invalid),
        'independent_bruteforce_p_verified':True,'independent_labels_and_metrics_verified':True,'complete_new_groups':41,'test_files_read':False,
        'exact_requests_and_nonthinking_verified':True,'secret_scan_passed':True,'script_sha256':file_hash(Path(__file__)),'assessment_sha256':file_hash(directory/'assessment.json')}
    atomic_json(directory/'audit.json',audit)
    lines=['# V12 固定 NLI 独立复现结果','',f"预先冻结的成功标准：{'通过' if passed else '未通过'}。本轮 612 次响应、{sum(cost.values()):,} tokens；逐条请求、模型、非思考设置、完整新组、计分与主检验均已复算。",'',
        '| 数据集 | A27 | NLI | 准确率差 | 修正/损害 | 单侧组置换 p |','|---|---:|---:|---:|---:|---:|']
    for d in ('basic','challenge'):
        a,b=(result['methods'][arm][d] for arm in ('nli','baseline'));s=result['statistics'][d];pair=result['paired'][d]
        lines.append(f"| {d} | {b['correct']}/{b['n']} ({b['accuracy']:.2%}) | {a['correct']}/{a['n']} ({a['accuracy']:.2%}) | {s['accuracy_delta']*100:+.2f} pp | {pair['improved']}/{pair['harmed']} | {s['one_sided_group_permutation_p']:.6f} |")
    lines += ['',f"主检验 alpha=0.0125；挑战集最低增益=5 pp；其他指标幅度限制通过：{bool(guards)}。NLI 部署 token 为同期基线的 {cost['nli']/cost['baseline']:.2f} 倍。",'',
        '## 三类召回率','','| 数据集 | 类别 | A27 | NLI |','|---|---|---:|---:|']
    for d in ('basic','challenge'):
        for l in LABELS:
            b,a=(result['methods'][arm][d]['classes'][l]['recall'] for arm in ('baseline','nli'))
            lines.append(f'| {d} | {l} | {b:.2%} | {a:.2%} |')
    lines += ['', '方法和参数与 V11 完全相同，本轮没有选方法。V11 的 p=0.03125 未通过其 alpha=0.025，保留该结果；本轮单独检验，不拼接两轮数据来重新挑选显著结论。累计分配 alpha=0.0375。', '',
        '样本为 41 个完整新开发组，基础集 180 题，挑战集 126 题。不能把开发确认结果说成测试集结果或已证明总体非劣；测试集仍未读取。', '',
        '非思考 Qwen-27B，固定原始 claim/evidence 输入，无训练、无具体题型提示，所有产物保存在仓库内。','']
    atomic_bytes(directory/'RESULTS.md','\n'.join(lines).encode('utf-8'));print(json.dumps(audit,ensure_ascii=False))


if __name__=='__main__':main()
