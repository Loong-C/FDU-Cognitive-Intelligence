"""Task-agnostic input repetition with unchanged baseline instructions/decoding."""
import argparse
from collections import Counter, defaultdict
import json

from ..common import ROOT, atomic_json, file_hash, frozen_json, now
from ..groq_client import GroqStop, exclusive, load_local_key
from ..metrics import compute_metrics, paired_comparison
from ..symbolic_z3.client import SymbolicClient
from .experiment import CONFIG, EXPERIMENT, OUTPUT, choose_rows, load_dev, receive, source_hashes, verify
from .inference import digest, messages, parse, schema
from .report import gate, metric_row
from .assess import paired_statistics


def repeated_messages(*, claim, evidence, root=ROOT):
    original = messages("baseline", claim=claim, evidence=evidence, root=root)
    return [original[0], {"role": "user", "content": original[1]["content"] + "\n\n" + original[1]["content"]}]


def freeze(phase, root=ROOT):
    if phase not in ("repeat_scout", "repeat_confirm"):
        raise ValueError("Unknown repetition stage")
    if phase == "repeat_scout":
        rows = verify("scout", root)[0]["rows"]
    else:
        rows = choose_rows(phase, 20261028, 1, root)
    sources = source_hashes(root)
    sources.update({p:file_hash(root/p) for p in ("src/ab_factcheck/macro_v7/repetition.py", "experiments/006_symbolic_z3/evaluation.json")})
    manifest = {"phase": phase, "rows": rows, "transform": "repeat the entire A27 user input exactly twice, same system prompt and schema",
        "reference": "https://arxiv.org/abs/2512.14982", "reasoning_effort": "none", "test_access": False,
        "selection": "Old exploratory dev samples" if phase == "repeat_scout" else "Previously unused complete development groups",
        "no_case_specific_instructions": True}
    directory = root/EXPERIMENT/phase
    frozen_json(directory/"manifest.json", manifest)
    frozen_json(directory/"freeze.json", {"manifest_sha256":file_hash(directory/"manifest.json"), "source_sha256":sources,
        "config":json.loads((root/CONFIG).read_text(encoding="utf-8"))})
    print(json.dumps({"frozen":phase,"n":len(rows)}),flush=True)


def run(phase, root=ROOT):
    manifest,f=verify(phase,root)
    load_local_key(root)
    client=SymbolicClient(f["config"]["model"],root/"outputs/groq/quota.json",f["config"]["quota_policy"],free_plan_confirmed=True)
    directory=root/OUTPUT/phase
    receipt={"phase":phase,"started":now()}
    try:
        with exclusive(directory/"run.lock"):
            for index,item in enumerate(manifest["rows"]):
                arms=("repeat",) if phase=="repeat_scout" else ("baseline","repeat")
                for arm in arms:
                    m=repeated_messages(claim=item["claim"],evidence=item["evidence"],root=root) if arm=="repeat" else messages("baseline",claim=item["claim"],evidence=item["evidence"],root=root)
                    p=directory/"records"/item["dataset"]/item["id"]/(arm+".json")
                    r=receive(client,p,{"messages":m,"response_format":schema("baseline"),"max_completion_tokens":1024},digest(f))
                    if r["provider_validation_issues"]:
                        raise GroqStop("Provider protocol failure")
                    print(json.dumps({"item":index+1,"n":len(manifest["rows"]),"arm":arm,"label":parse("baseline",r)["label"],"tokens":r["usage"]["total_tokens"]}),flush=True)
            receipt["status"]="complete"
    except (GroqStop,KeyboardInterrupt) as exc:
        receipt.update(status="stopped",reason=str(exc),error_type=type(exc).__name__)
        print(json.dumps(receipt),flush=True)
    finally:
        receipt.update(ended=now(),new_http_attempts=client.new_attempts)
        atomic_json(directory/"last_execution.json",receipt)
        client.close()


def report(phase,root=ROOT):
    manifest,f=verify(phase,root)
    gold={(d,r["id"]):r["label"] for d in ("basic","challenge") for r in load_dev(d,root)}
    old=json.loads((root/"experiments/006_symbolic_z3/evaluation.json").read_text(encoding="utf-8"))
    historical={(r["dataset"],r["id"]):r["baseline_A27"] for r in old["rows"]}
    results=defaultdict(lambda:defaultdict(list))
    counts,tokens=Counter(),Counter()
    complete=True
    for item in manifest["rows"]:
        for arm in ("baseline","repeat"):
            if arm=="baseline" and phase=="repeat_scout":
                label=historical[item["dataset"],item["id"]]
            else:
                p=root/OUTPUT/phase/"records"/item["dataset"]/item["id"]/(arm+".json")
                label="INVALID"
                if p.exists():
                    r=json.loads(p.read_text(encoding="utf-8"))
                    if r["record_sha256"]!=digest({k:v for k,v in r.items() if k!="record_sha256"}) or r["freeze_sha256"]!=digest(f):
                        raise ValueError("Response integrity mismatch")
                    expected=repeated_messages(claim=item["claim"],evidence=item["evidence"],root=root) if arm=="repeat" else messages("baseline",claim=item["claim"],evidence=item["evidence"],root=root)
                    payload=r["request_payload"]
                    if payload!={"model":"qwen/qwen3.8-27b","reasoning_effort":"none","temperature":0,"seed":42,"stream":False,"max_completion_tokens":1024,"messages":expected,"response_format":schema("baseline")}:
                        raise ValueError("Unexpected transmitted content")
                    label=parse("baseline",r)["label"]
                    counts[arm]+=1
                    tokens[arm]+=r["usage"]["total_tokens"]
                else:
                    complete=False
            results[item["dataset"]][arm].append(metric_row(item,label,gold[item["dataset"],item["id"]]))
    out={"phase":phase,"complete":complete,"calls":dict(counts),"tokens":dict(tokens),"datasets":{},"baseline_provenance":"historical" if phase=="repeat_scout" else "contemporaneous"}
    for d,arms in results.items():
        out["datasets"][d]={a:{"metrics":compute_metrics(rows),"mechanisms":{m:compute_metrics([r for r in rows if r["mechanism"]==m]) for m in sorted({r["mechanism"] for r in rows})}} for a,rows in arms.items()}
        out["datasets"][d]["paired"]=paired_comparison(arms["baseline"],arms["repeat"])
        out["datasets"][d]["gate"]=gate(compute_metrics(arms["baseline"]),compute_metrics(arms["repeat"]))
        if complete:
            out["datasets"][d]["statistics"]=paired_statistics(arms["baseline"],arms["repeat"],resamples=5000)
    atomic_json(root/EXPERIMENT/phase/"metrics.json",out)
    print(json.dumps({"phase":phase,"complete":complete,"scores":{d:{a:(v[a]["metrics"]["correct"],v[a]["metrics"]["n"]) for a in ("baseline","repeat")} for d,v in out["datasets"].items()},"tokens":dict(tokens)}))
    return out


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=("freeze","run","report"))
    p.add_argument("--phase",default="repeat_scout",choices=("repeat_scout","repeat_confirm"))
    a=p.parse_args()
    {"freeze":freeze,"run":run,"report":report}[a.command](a.phase)
