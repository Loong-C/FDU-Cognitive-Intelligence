"""Small staged, dev-only comparison of content-preserving inference changes."""
import argparse
from collections import Counter, defaultdict
import copy
import csv
import io
import json
import time

from .common import ROOT, LABELS, atomic_bytes, atomic_json, file_hash, frozen_json, now
from .groq_client import GroqStop, exclusive, load_local_key
from .macro_v7.experiment import load_dev, receive, source_hashes, verify as verify_v7
from .macro_v7.inference import digest, messages, parse, schema
from .macro_v7.report import metric_row
from .macro_v7.assess import paired_statistics
from .metrics import compute_metrics, paired_comparison
from .negation_v8.inference import negate, decide
from .negation_v8.experiment import verify as verify_v8
from .symbolic_z3.client import SymbolicClient

EXP = "experiments/009_small_search"
OUT = "outputs/search_v9"
ARMS = ("repeat_nli", "claim_first_nli", "reason_first_nli", "repeat_baseline")
SEED = 2026102809


def request(arm, *, claim, evidence):
    if arm not in (*ARMS, "baseline", "nli", "negative"):
        raise ValueError("Unknown arm")
    kind = "baseline" if arm in ("baseline", "repeat_baseline") else "nli"
    m = messages(kind, claim=negate(claim) if arm == "negative" else claim, evidence=evidence)
    s = schema(kind)
    if arm.startswith("repeat_"):
        m[1]["content"] = m[1]["content"] + "\n\n" + m[1]["content"]
    elif arm == "claim_first_nli":
        m[1]["content"] = f"HYPOTHESIS:\n{claim}\n\nPREMISE:\n{evidence}"
    elif arm == "reason_first_nli":
        properties = s["json_schema"]["schema"]["properties"]
        s["json_schema"]["schema"]["properties"] = {k: properties[k] for k in ("justification", "relation")}
        s["json_schema"]["schema"]["required"] = ["justification", "relation"]
    return {"messages": m, "response_format": s, "max_completion_tokens": 1024 if kind == "baseline" else 512}


def parsed(arm, record):
    return parse("baseline" if arm in ("baseline", "repeat_baseline") else "nli", record)["label"]


def policy(method, predictions):
    b = predictions["baseline"]
    if method == "signed_v8":
        return decide(b, predictions["nli"], predictions.get("negative"))[0]
    if method.startswith("agree__"):
        p, x = predictions["nli"], predictions[method[len("agree__"):]]
        return p if p in LABELS and p == x else b
    return predictions[method]


def prepare():
    scout = verify_v7("scout")[0]["rows"]
    verify_v8("confirm")
    strata = defaultdict(list)
    for r in scout:
        strata[r["dataset"], r["mechanism"]].append(r)
    assert len(scout) == 42 and len(strata) == 14
    pilot = [sorted(v, key=lambda r: digest([SEED, r["id"]]))[0] for k,v in sorted(strata.items())]
    excluded = set()
    for d in ("basic", "challenge"):
        old = json.loads((ROOT / f"experiments/001_two_world_pilot/pilot/{d}_manifest.json").read_text(encoding="utf-8"))
        excluded |= {(d,r["group"]) for r in old["assignments"] if r["is_pilot"]}
    old = json.loads((ROOT / "experiments/005_layered_worlds/fresh_dev_v5.json").read_text(encoding="utf-8"))
    for d, data in old["datasets"].items():
        excluded |= {(d,r["group"]) for r in data["rows"]}
    for dirname in ("007_macro_inference", "008_negation_consistency"):
        for p in (ROOT / "experiments" / dirname).glob("*/manifest.json"):
            excluded |= {(r["dataset"],r["group"]) for r in json.loads(p.read_text(encoding="utf-8"))["rows"] if r["dataset"] in ("basic", "challenge")}
    holdout, group_sizes = [], {}
    for d in ("basic", "challenge"):
        groups = defaultdict(lambda: defaultdict(list))
        for r in load_dev(d):
            if (d,r["group"]) not in excluded:
                groups[r["mechanism"]][r["group"]].append(r)
        assert len(groups) == 7
        for mechanism, choices in sorted(groups.items()):
            g = min(choices, key=lambda g: digest([SEED,d,mechanism,g]))
            selected = sorted(choices[g], key=lambda r: digest([SEED,d,r["id"]]))[:2]
            assert len(selected) == 2
            group_sizes[f"{d}/{g}"] = {"selected": 2, "available": len(choices[g])}
            holdout += [{k:r[k] for k in ("id","group","mechanism","claim","evidence")} | {"dataset":d} for r in selected]
    assert not {(r['dataset'],r['group']) for r in holdout} & excluded
    plan = {"seed": SEED, "pilot": pilot, "scout": scout, "confirm": holdout, "new_arms": list(ARMS),
        "selection": "Input IDs and group/mechanism strata only. No gold/predictions used in sample selection.",
        "stages": "4 arms on 14 old dev rows; select 2 underlying arms; extend those to all 42 old dev rows; freeze 1 winner; compare with fresh baseline on 28 new dev rows.",
        "ranking": "First prefer methods losing at most 1 correct item per dataset vs A27; then mean dataset accuracy, worst accuracy delta, mean macro-F1, fewer deployment calls, alphabetical tie-break.",
        "confirm_scope": "Two samples from each of 14 previously unused groups, 28 total. Groups are isolated but NOT fully enumerated; results apply to this small slice.",
        "confirm_group_sizes": group_sizes, "excluded_groups": sorted([list(k) for k in excluded]),
        "candidate_families": "single new arm; unanimity of old positive NLI and new arm with baseline fallback; old NLI and V8 as selectable controls; certificate/dual descriptive only.",
        "constraints": "Qwen-27B, nonthinking, dev inputs only, no training, no case/label-specific rules, no account/plan changes. Test stays sealed."}
    directory = ROOT / EXP
    frozen_json(directory / "plan.json", plan)
    paths = ["src/ab_factcheck/search_v9.py", "src/ab_factcheck/macro_v7/report.py", "src/ab_factcheck/macro_v7/assess.py", "src/ab_factcheck/metrics.py", "src/ab_factcheck/negation_v8/inference.py", "src/ab_factcheck/negation_v8/experiment.py", "experiments/006_symbolic_z3/evaluation.json", "experiments/008_negation_consistency/scout/metrics.json"]
    sources = source_hashes(ROOT) | {p:file_hash(ROOT/p) for p in paths}
    frozen_json(directory / "freeze.json", {"plan_sha256":file_hash(directory/"plan.json"), "source_sha256":sources,
        "config":json.loads((ROOT/"configs/experiment_macro_v7.json").read_text(encoding="utf-8"))})
    print(json.dumps({"frozen":True,"pilot":len(pilot),"scout":len(scout),"confirm":len(holdout),"fresh_groups":14}),flush=True)


def verify():
    directory = ROOT / EXP
    f = json.loads((directory/"freeze.json").read_text(encoding="utf-8"))
    assert file_hash(directory/"plan.json") == f["plan_sha256"]
    for p,h in f["source_sha256"].items():
        if file_hash(ROOT/p) != h:
            raise GroqStop("Frozen source changed: " + p)
    return json.loads((directory/"plan.json").read_text(encoding="utf-8")), f


def checked(path, arm, item, freeze=None):
    r = json.loads(path.read_text(encoding="utf-8"))
    assert r["record_sha256"] == digest({k:v for k,v in r.items() if k != "record_sha256"})
    if freeze is not None:
        assert r["freeze_sha256"] == digest(freeze)
    expected = {"model":"qwen/qwen3.8-27b","temperature":0,"seed":42,"reasoning_effort":"none","stream":False,**request(arm,claim=item["claim"],evidence=item["evidence"])}
    assert r["request_payload"] == expected
    assert r["actual_model_id"] == "qwen/qwen3.8-27b" and r["nonthinking_validation"]["passed"] and not r["provider_validation_issues"]
    return r


def historic(item):
    key = (item["dataset"], item["id"])
    old = json.loads((ROOT/"experiments/006_symbolic_z3/evaluation.json").read_text(encoding="utf-8"))
    b = next(r["baseline_A27"] for r in old["rows"] if (r["dataset"],r["id"]) == key)
    path = ROOT/"outputs/macro_v7/scout/records"/item["dataset"]/item["id"]
    result = {"baseline":b,"nli":parsed("nli",checked(path/"nli.json","nli",item))}
    # Prior frozen exploratory controls, never used as new independent validation.
    for arm in ("certificate","dual"):
        r = json.loads((path/(arm+".json")).read_text(encoding="utf-8"))
        assert r["record_sha256"] == digest({k:v for k,v in r.items() if k!="record_sha256"})
        result[arm] = parse(arm,r)["label"]
    p = ROOT/"outputs/negation_v8/scout/records"/item["dataset"]/item["id"]/"decision.json"
    decision = json.loads(p.read_text(encoding="utf-8"))
    assert decision["baseline"] == b and decision["positive"] == result["nli"]
    negative = decision["negative"]
    if negative is not None:
        negative = parsed("negative",checked(p.parent/"negative.json","negative",item))
    assert decide(b,result["nli"],negative)[0] == decision["prediction"]
    result["signed_v8"] = decision["prediction"]
    return result


def methods_for(arms):
    return ["baseline","nli","signed_v8","certificate","dual",*arms,*("agree__"+a for a in arms)]


def cost_calls(method):
    return 3 if method.startswith("agree__") else (2.2 if method == "signed_v8" else 1)


def rank(entry):
    metrics, base = entry["metrics"], entry["baseline_metrics"]
    ds = ("basic","challenge")
    deltas = [metrics[d]["accuracy"] - base[d]["accuracy"] for d in ds]
    eligible = all(metrics[d]["correct"] >= base[d]["correct"]-1 for d in ds)
    return (not eligible, -sum(metrics[d]["accuracy"] for d in ds)/2, -min(deltas),
            -sum(metrics[d]["macro_f1"] for d in ds)/2, cost_calls(entry["method"]),entry["method"])


def evaluate(stage, items, arms, selected=None):
    _,f = verify()
    gold = {(d,r["id"]):r["label"] for d in ("basic","challenge") for r in load_dev(d)}
    methods = ["baseline",selected] if stage=="confirm" else methods_for(arms)
    data = {method:defaultdict(list) for method in methods}
    flat, calls, tokens, valid = [], Counter(), Counter(), True
    for item in items:
        preds = {} if stage=="confirm" else historic(item)
        for arm in arms:
            p = ROOT/OUT/"records"/item["dataset"]/item["id"]/(arm+".json")
            if not p.exists():
                preds[arm] = "INVALID";valid=False;continue
            r=checked(p,arm,item,f);preds[arm]=parsed(arm,r)
            calls[arm]+=1;tokens[arm]+=r['usage']['total_tokens']
        if stage=="confirm" and selected=="signed_v8" and preds.get('baseline') != preds.get('nli') and preds.get('nli') in LABELS:
            p = ROOT/OUT/"records"/item["dataset"]/item["id"]/"negative.json"
            if not p.exists():valid=False;preds['negative']='INVALID'
            else:
                r=checked(p,'negative',item,f);preds['negative']=parsed('negative',r);calls['negative']+=1;tokens['negative']+=r['usage']['total_tokens']
        row = {k:item[k] for k in ('dataset','id','group','mechanism')} | {'gold':gold[item['dataset'],item['id']]}
        for method in methods:
            pred = preds[method] if stage!='confirm' and method in ('baseline','nli','signed_v8','certificate','dual') else policy(method,preds)
            data[method][item['dataset']].append(metric_row(item,pred,row['gold']))
            row[method]=pred
        flat.append(row)
    out={'stage':stage,'complete':valid,'n':len(items),'calls':dict(calls),'tokens':dict(tokens),'methods':{},'test_access':False}
    for method, datasets in data.items():
        e={'method':method,'metrics':{d:compute_metrics(r) for d,r in datasets.items()},'baseline_metrics':{d:compute_metrics(data['baseline'][d]) for d in datasets},
           'paired':{d:paired_comparison(data['baseline'][d],r) for d,r in datasets.items()}}
        if stage=='confirm' and method!='baseline' and valid:
            e['statistics']={d:paired_statistics(data['baseline'][d],r) for d,r in datasets.items()}
        out['methods'][method]=e
    directory=ROOT/EXP/stage
    atomic_json(directory/'metrics.json',out)
    buf=io.StringIO(newline='');writer=csv.DictWriter(buf,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
    atomic_bytes(directory/'predictions.csv',buf.getvalue().encode('utf-8'))
    print(json.dumps({'stage':stage,'complete':valid,'scores':{m:{d:(v['correct'],v['n']) for d,v in e['metrics'].items()} for m,e in out['methods'].items()},'tokens':dict(tokens)}),flush=True)
    return out


def run_calls(items, arms, selected=None):
    plan,f=verify();load_local_key(ROOT)
    c=f['config'];client=SymbolicClient(c['model'],ROOT/'outputs/groq/quota.json',c['quota_policy'],free_plan_confirmed=True)
    receipt={'started':now(),'new_responses':0,'requested_arms':list(arms)}
    def get(arm,item):
        p=ROOT/OUT/'records'/item['dataset']/item['id']/(arm+'.json');cached=p.exists()
        r=receive(client,p,request(arm,claim=item['claim'],evidence=item['evidence']),digest(f))
        checked(p,arm,item,f)
        if not cached:
            receipt['new_responses']+=1
            print(json.dumps({'received':receipt['new_responses'],'arm':arm,'tokens':r['usage']['total_tokens']}),flush=True)
        return parsed(arm,r)
    try:
        with exclusive(ROOT/OUT/'run.lock'):
            for item in items:
                preds={arm:get(arm,item) for arm in arms}
                if selected=='signed_v8' and preds['nli'] in LABELS and preds['baseline']!=preds['nli']:
                    get('negative',item)
        receipt['status']='complete'
    except (GroqStop,KeyboardInterrupt) as exc:
        receipt.update(status='stopped',reason=str(exc),error_type=type(exc).__name__)
    finally:
        receipt.update(ended=now(),new_http_attempts=client.new_attempts)
        atomic_json(ROOT/OUT/'last_execution.json',receipt);client.close()
    if receipt['status']!='complete':
        raise GroqStop(receipt['reason'])


def advance():
    plan,f=verify()
    run_calls(plan['pilot'],ARMS)
    pilot=evaluate('pilot',plan['pilot'],ARMS)
    assert pilot['complete']
    ranked=sorted(ARMS,key=lambda a:min(rank(pilot['methods'][m]) for m in (a,'agree__'+a)))
    shortlist=ranked[:2]
    frozen_json(ROOT/EXP/'shortlist.json',{'arms':shortlist,'pilot_metrics_sha256':file_hash(ROOT/EXP/'pilot/metrics.json')})
    run_calls(plan['scout'],shortlist)
    scout=evaluate('scout',plan['scout'],shortlist)
    assert scout['complete']
    eligible=['nli','signed_v8',*shortlist,*('agree__'+a for a in shortlist)]
    winner=min(eligible,key=lambda m:rank(scout['methods'][m]))
    frozen_json(ROOT/EXP/'winner.json',{'method':winner,'scout_metrics_sha256':file_hash(ROOT/EXP/'scout/metrics.json')})
    arms=['baseline']
    if winner in ('nli','signed_v8') or winner.startswith('agree__'):
        arms.append('nli')
    if winner.startswith('agree__'):arms.append(winner[len('agree__'):])
    elif winner in ARMS:arms.append(winner)
    run_calls(plan['confirm'],arms,selected=winner)
    result=evaluate('confirm',plan['confirm'],arms,selected=winner)
    assert result['complete']
    return winner


def pipeline():
    verify()
    state={'started':now(),'status':'running','purpose':'Small staged search, only definite provider quota pauses auto-resume.'}
    while True:
        atomic_json(ROOT/OUT/'pipeline.json',state)
        try:
            winner=advance()
            state.update(status='complete',winner=winner,ended=now());atomic_json(ROOT/OUT/'pipeline.json',state);return
        except GroqStop as exc:
            ledger=json.loads((ROOT/'outputs/groq/quota.json').read_text(encoding='utf-8'))
            last=ledger['attempts'][-1]
            safe=(last.get('http_status')==429 and ('Quota reset' in str(exc) or 'HTTP 429' in str(exc))
                  and not list((ROOT/OUT/'records').glob('*/*/*.inflight')))
            if not safe:
                state.update(status='requires_inspection',reason=str(exc),ended=now());atomic_json(ROOT/OUT/'pipeline.json',state);raise
            wait=max(30,ledger.get('blocked_until',0)-time.time()+1)
            state.update(status='quota_wait',reason=str(exc),wait_seconds=wait,updated=now());atomic_json(ROOT/OUT/'pipeline.json',state)
            print(json.dumps({'status':'quota_wait','seconds':round(wait),'at':now()}),flush=True)
            until=time.monotonic()+wait
            while time.monotonic()<until:time.sleep(max(0,min(30,until-time.monotonic())))
            state.update(status='running',updated=now())


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=('prepare','pipeline'));a=p.parse_args()
    {'prepare':prepare,'pipeline':pipeline}[a.command]()
