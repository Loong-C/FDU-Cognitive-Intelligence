"""A fixed-method independent replication; second alpha-spending allocation."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import itertools
import json

from .common import ROOT, LABELS, atomic_bytes, atomic_json, file_hash, frozen_json, now
from .groq_client import exclusive
from .intranet_client import Client
from .macro_v7.experiment import load_dev
from .macro_v7.inference import digest
from .macro_v7.report import metric_row, cluster_interval
from .metrics import compute_metrics, paired_comparison
from .server_search_v11 import request, parse, checked, verify as verify_v11

EXP='experiments/012_server_replication'
OUT='outputs/server_v12'
SEED=2026102912


def prepare():
    if (ROOT/EXP/'freeze.json').exists():verify();return
    old,old_f=verify_v11()
    previous=json.loads((ROOT/'experiments/011_server_search/assessment.json').read_text(encoding='utf-8'))
    assert previous['winner']=='nli' and previous['alpha_spent']==.025
    excluded={tuple(k) for k in old['excluded_groups']} | {(r['dataset'],r['group']) for r in old['confirm']}
    rows=[];availability={}
    for d in ('basic','challenge'):
        by=defaultdict(lambda:defaultdict(list))
        for r in load_dev(d):
            if (d,r['group']) not in excluded:by[r['mechanism']][r['group']].append(r)
        assert len(by)==7
        for mechanism,groups in sorted(by.items()):
            assert len(groups)>=1
            availability[d+'/'+mechanism]={'available':len(groups),'selected':min(3,len(groups))}
            for g in sorted(groups,key=lambda g:digest([SEED,d,mechanism,g]))[:min(3,len(groups))]:
                rows += [{k:r[k] for k in ('id','group','mechanism','claim','evidence')} | {'dataset':d} for r in sorted(groups[g],key=lambda r:r['id'])]
    plan={'frozen_at':now(),'seed':SEED,'rows':rows,'excluded_groups':sorted([list(g) for g in excluded]),'method':'nli','alpha':.0125,'group_availability':availability,
        'previous_alpha_spent':.025,'cumulative_alpha':.0375,'next_alpha_if_needed':.00625,
        'selection':'No model or parameter selection. Same V11 frozen NLI and A27 payloads; up to 3 input-hash-selected complete unseen groups per mechanism per dataset, capped by remaining availability. Counts fixed before any replication requests.',
        'primary':'Challenge accuracy delta >= .05 and one-sided exact group sign-flip permutation p <= .0125.',
        'guardrails':'Unchanged V11 point-estimate safeguards: basic accuracy/macro-F1 drop <=2pp, challenge macro-F1 nondecrease, each class recall drop <=5pp.',
        'interpretation':'Independent replication, not another method. No pooling with V11 for primary significance; preserve the failed V11 assessment. Test remains sealed.'}
    frozen_json(ROOT/EXP/'plan.json',plan)
    extra=['src/ab_factcheck/server_replication_v12.py','experiments/011_server_search/assessment.json','experiments/011_server_search/winner.json','experiments/011_server_search/plan.json']
    frozen_json(ROOT/EXP/'freeze.json',{'plan_sha256':file_hash(ROOT/EXP/'plan.json'),'sources':old_f['sources'] | {p:file_hash(ROOT/p) for p in extra}})
    print(json.dumps({'frozen':True,'counts':dict(Counter(r['dataset'] for r in rows)),'groups':len({(r['dataset'],r['group']) for r in rows}),'alpha':.0125}),flush=True)


def verify():
    f=json.loads((ROOT/EXP/'freeze.json').read_text(encoding='utf-8'))
    assert file_hash(ROOT/EXP/'plan.json')==f['plan_sha256']
    for p,h in f['sources'].items():assert file_hash(ROOT/p)==h,p
    return json.loads((ROOT/EXP/'plan.json').read_text(encoding='utf-8')),f


def exact_p(values):
    """Integer convolution of all group sign flips, including zero differences."""
    counts={0:1}
    for value in values:
        nxt=defaultdict(int)
        for total,n in counts.items():nxt[total+value]+=n;nxt[total-value]+=n
        counts=dict(nxt)
    return sum(n for total,n in counts.items() if total>=sum(values))/(2**len(values))


def evaluate():
    p,f=verify();gold={(d,r['id']):r['label'] for d in ('basic','challenge') for r in load_dev(d)}
    data={a:defaultdict(list) for a in ('baseline','nli')};flat=[];cost=Counter();hashes={}
    for row in p['rows']:
        saved={k:row[k] for k in ('dataset','id','group','mechanism')} | {'gold':gold[row['dataset'],row['id']]}
        for a in ('baseline','nli'):
            path=ROOT/OUT/'records'/row['dataset']/row['id']/(a+'.json');r=checked(path,a,row,f)
            saved[a]=parse(a,r)[0];data[a][row['dataset']].append(metric_row(row,saved[a],saved['gold']))
            cost[a]+=r['usage']['total_tokens'];hashes[path.relative_to(ROOT).as_posix()]=file_hash(path)
        flat.append(saved)
    result={'n':len(flat),'methods':{a:{d:compute_metrics(data[a][d]) for d in ('basic','challenge')} for a in data},'tokens':dict(cost),'paired':{},'statistics':{}}
    guards=True
    for d in ('basic','challenge'):
        b,a=(result['methods'][arm][d] for arm in ('baseline','nli'))
        result['paired'][d]=paired_comparison(data['baseline'][d],data['nli'][d])
        diffs=defaultdict(int)
        for r in flat:
            if r['dataset']==d:diffs[r['group']]+=int(r['nli']==r['gold'])-int(r['baseline']==r['gold'])
        result['statistics'][d]={'groups':len(diffs),'group_net_correct':dict(diffs),'accuracy_delta':sum(diffs.values())/a['n'],
            'one_sided_group_permutation_p':exact_p(list(diffs.values())),'bootstrap':cluster_interval(data['baseline'][d],data['nli'][d])}
        guards &= a['macro_f1']>=b['macro_f1']-(.02 if d=='basic' else 0)-1e-12
        if d=='basic':guards &= a['accuracy']>=b['accuracy']-.02-1e-12
        guards &= all(a['classes'][l]['recall']>=b['classes'][l]['recall']-.05-1e-12 for l in LABELS)
    s=result['statistics']['challenge']
    result.update(primary_and_guardrails_passed=bool(guards and s['accuracy_delta']>=.05 and s['one_sided_group_permutation_p']<=p['alpha']),guardrails_passed=bool(guards),alpha_spent=p['alpha'],cumulative_alpha_spent=p['cumulative_alpha'],noninferiority_proven=False,test_access=False,raw_sha256=hashes)
    frozen_json(ROOT/EXP/'assessment.json',result)
    buf=io.StringIO(newline='');w=csv.DictWriter(buf,fieldnames=list(flat[0]));w.writeheader();w.writerows(flat)
    atomic_bytes(ROOT/EXP/'predictions.csv',buf.getvalue().encode('utf-8'))
    print(json.dumps({'scores':{a:{d:(m['correct'],m['n']) for d,m in v.items()} for a,v in result['methods'].items()},'success':result['primary_and_guardrails_passed'],'p':s['one_sided_group_permutation_p']}),flush=True)
    return result


def run():
    p,f=verify();state={'started':now(),'status':'running'};atomic_json(ROOT/OUT/'pipeline.json',state)
    client=Client();done=0;total=len(p['rows'])*2
    def job(pair):
        row,a=pair;path=ROOT/OUT/'records'/row['dataset']/row['id']/(a+'.json')
        client.receive(path,request(a,claim=row['claim'],evidence=row['evidence']),digest(f));checked(path,a,row,f)
    try:
        with exclusive(ROOT/OUT/'run.lock'),ThreadPoolExecutor(max_workers=4) as pool:
            tasks=((r,a) for r in p['rows'] for a in ('baseline','nli'))
            while batch:=list(itertools.islice(tasks,4)):
                for _ in pool.map(job,batch):
                    done+=1
                    if done%40==0 or done==total:print(json.dumps({'completed':done,'total':total}),flush=True)
        result=evaluate();state.update(status='complete',success=result['primary_and_guardrails_passed'])
    except Exception as exc:state.update(status='requires_inspection',error_type=type(exc).__name__);raise
    finally:
        client.close();state['ended']=now();atomic_json(ROOT/OUT/'pipeline.json',state)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('prepare','run'));args=parser.parse_args()
    {'prepare':prepare,'run':run}[args.command]()
