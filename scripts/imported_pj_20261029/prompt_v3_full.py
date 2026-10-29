"""冻结v3草案，对885条挑战集进行全新单次调用评测。"""
from __future__ import annotations
import argparse
import collections
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
import os
from pathlib import Path
import sys
import time

from api_client import APIError, Client, ROOT, load_config, load_key
from baseline_eval import evaluate_one, percentage, stamp
from benchmark import LABELS, digest, grouped_scores, read_sources, sha, write_json

DRAFT=ROOT/'results'/'prompt-v3-draft-20261028'
OUT=ROOT/'results'/'challenge-prompt-v3-full-20261028'
COMPARATORS={
    'baseline':ROOT/'results'/'full-4096-20261027'/'challenge.jsonl',
    'prompt_v1':ROOT/'results'/'challenge-refutation-v1-full-20261027'/'challenge.jsonl',
    'prompt_v2':ROOT/'results'/'challenge-prompt-v2-full-20261027'/'network-retry'/'supplemented-predictions.jsonl',
}
NAMES={'baseline':'原4096 Baseline','prompt_v1':'单次Prompt-v1','prompt_v2':'单次v2（网络补齐）','prompt_v3':'单次Prompt-v3'}
NEI='NOT ENOUGH INFO'


def read_unique(path):
    records={}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():continue
            record=json.loads(line)
            if record['id'] in records:raise ValueError('发现重复样本ID，保留现场停止')
            records[record['id']]=record
    return records


def prepare(out):
    datasets,_,audit=read_sources()
    rows=datasets['challenge']
    if len(rows)!=885:raise ValueError('必须使用完整885条挑战集')
    draft_meta=json.loads((DRAFT/'draft-manifest.json').read_text(encoding='utf-8'))
    prompt=(DRAFT/'prompt-v3.txt').read_text(encoding='utf-8').removesuffix('\n')
    if sha(prompt.encode())!=draft_meta['prompt_sha256']:raise ValueError('v3草案提示词哈希不一致')
    if sha((ROOT/'results'/'challenge-prompt-v2-full-20261027'/'prompt-v2.txt').read_bytes())!=draft_meta['base_prompt_file_sha256']:
        raise ValueError('v3所基于的v2提示词发生变化')
    config=load_config(ROOT/'config-4096.json')
    v1_meta=json.loads((COMPARATORS['prompt_v1'].parent/'manifest.json').read_text(encoding='utf-8'))
    if config!=json.loads((ROOT/'results'/'challenge-prompt-v2-full-20261027'/'manifest.json').read_text(encoding='utf-8'))['settings']['config'] or config!=v1_meta['settings']['config']:
        raise ValueError('参数与v3草案或v1不一致')
    if audit!=v1_meta['settings']['data_audit']:raise ValueError('数据与冻结v1不一致')
    v1_prompt=v1_meta['settings']['prompt_template']
    if prompt[:prompt.index('Additional decision discipline:')]!=v1_prompt[:v1_prompt.index('Additional decision discipline:')]:
        raise ValueError('基础任务定义发生变化')
    if prompt[prompt.index('\n\nEVIDENCE:'):]!=v1_prompt[v1_prompt.index('\n\nEVIDENCE:'):]:
        raise ValueError('输入与输出格式发生变化')
    expected={r['id']:r['label'] for r in rows}
    for path in COMPARATORS.values():
        records=read_unique(path)
        if set(records)!=set(expected) or any(r['gold']!=expected[i] or r['status']!='ok' for i,r in records.items()):
            raise ValueError('历史对照不完整或ID、标签、有效性不一致')
    settings={'config':config,'workers':4,'prompt_template':prompt,'prompt_sha256':sha(prompt.encode()),
              'data_audit':audit,'selected_ids':[r['id'] for r in rows],
              'draft_prompt_file_sha256':sha((DRAFT/'prompt-v3.txt').read_bytes()),
              'draft_manifest_sha256':sha((DRAFT/'draft-manifest.json').read_bytes()),
              'comparator_records_sha256':{name:sha(path.read_bytes()) for name,path in COMPARATORS.items()},
              'input_fields':['evidence','claim'],'calls_per_sample':1,'uses_cached_predictions':False,
              'code_hashes':{name:sha((ROOT/name).read_bytes()) for name in
                             ('prompt_v3_full.py','api_client.py','benchmark.py','baseline_eval.py')}}
    manifest={'created_at':stamp(),'fingerprint':digest(settings),'settings':settings,
              'comparison_note':'本轮v3全部重新调用，其他版本为已冻结历史结果，含服务端波动影响；主对照为v2网络补齐后的750/885，保留其主跑749/885口径。'}
    out.mkdir(parents=True,exist_ok=True)
    target=out/'manifest.json'
    if target.exists():
        previous=json.loads(target.read_text(encoding='utf-8'))
        if previous['fingerprint']!=manifest['fingerprint']:raise ValueError('已有实验与当前参数、提示词、代码或数据不一致')
        manifest=previous
    else:
        if any(out.iterdir()):raise ValueError('目标非空且缺少manifest')
        write_json(target,manifest)
        (out/'prompt-v3.txt').write_text(prompt+'\n',encoding='utf-8')
        (out/'全量评测预案.md').write_text(
            '# 单次调用Prompt-v3挑战集全量评测预案\n\n'
            '冻结此前v3草案，对完整885条挑战集全部重新调用，不复用旧预测。模型只接收证据和陈述，专项规则替换v1相应段落，任务定义与最终Verdict格式保持。原始标签不改。\n\n'
            '参数沿用v1：qwen38-27b、temperature=0、关闭thinking、max_tokens=4096、并发4。网络超时重试沿用原配置，输出格式错误和截断不额外补跑。请求失败或发现thinking开启时停止提交新请求。\n\n'
            '比较原4096 Baseline、单次Prompt-v1、v2网络补齐结果（750/885）；v2主跑749/885另记。本轮只重新评测v3挑战集，不重跑基础集和历史对照。\n\n'
            '报告Accuracy、Macro-F1、NEI Recall、REFUTES Precision/Recall、SUPPORTS Recall、NEI误反数、逐条纠正/退步、分机制结果、失败/截断率、耗时和token。所有885条保留计分，失败不剔除。\n\n'
            '全部挑战样本此前已观察，属于开发性全量验证，不能作为独立盲测。历史对照包含服务端波动，不能将所有差异归因于提示词。\n',encoding='utf-8')
    return rows,manifest


def summarize(out,rows,manifest):
    current=read_unique(out/'challenge.jsonl')
    old={name:read_unique(path) for name,path in COMPARATORS.items()}
    scores={name:grouped_scores(rows,records) for name,records in old.items()}
    new=grouped_scores(rows,current)
    scores['prompt_v3']=new
    comparisons={};changes={}
    for name,records in old.items():
        counts=collections.Counter();change=[]
        for row in rows:
            i,g=row['id'],row['label'];b=current.get(i)
            if b is None:continue
            a=records[i];ac,bc=a['prediction']==g,b['prediction']==g
            counts['paired_samples']+=1
            counts['wrong_to_correct']+=not ac and bc
            counts['correct_to_wrong']+=ac and not bc
            counts['same_prediction']+=a['prediction']==b['prediction']
            counts['true_refutes_lost_to_nei']+=g=='REFUTES' and a['prediction']=='REFUTES' and b['prediction']==NEI
            if a['prediction']!=b['prediction']:
                change.append({**row,'comparison_version':name,'previous_prediction':a['prediction'],
                               'v3_prediction':b['prediction'],'v3_status':b['status'],
                               'transition':'wrong_to_correct' if not ac and bc else 'correct_to_wrong' if ac and not bc else 'other_change'})
        comparisons[name]={'transitions':dict(counts),'correct_delta':new['correct']-scores[name]['correct'],
                           'accuracy_delta_percentage_points':100*(new['accuracy']-scores[name]['accuracy'])}
        changes[name]=change
    usage=collections.Counter();errors=collections.Counter();fingerprints=collections.Counter()
    for record in current.values():
        raw=record.get('raw_response',{})
        fingerprints[str(raw.get('system_fingerprint'))]+=1
        if record['status']!='ok':errors[record.get('parse_error') or record.get('error_kind')]+=1
        for k,v in (raw.get('usage') or {}).items():
            if type(v) is int:usage[k]+=v
    operations={'usage':dict(usage),'error_counts':dict(errors),'service_fingerprints':dict(fingerprints),
                'failed_request_attempts':sum(len(r.get('failed_request_attempts',[])) for r in current.values()),
                'latency_sum_seconds':sum(r['latency_seconds'] for r in current.values())}
    result={'updated_at':stamp(),'fingerprint':manifest['fingerprint'],'complete':new['completed']==len(rows),
            'scores':scores,'comparisons':comparisons,'operations':operations}
    write_json(out/'summary.json',result)
    write_json(out/'prediction_changes.json',changes)
    with (out/'逐条对照.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f)
        w.writerow(['id','group','mechanism','gold',*old,'prompt_v3','v3_status'])
        for row in rows:
            i=row['id'];r=current.get(i,{})
            w.writerow([i,row['group'],row['mechanism'],row['label'],*[records[i]['prediction'] for records in old.values()],r.get('prediction'),r.get('status','pending')])
    lines=['# 单次调用Prompt-v3挑战集全量对照报告','',f"本轮完成{new['completed']}/{len(rows)}条；885条全部重新请求，不复用旧预测。",'',
           '参数：qwen38-27b，temperature=0，关闭thinking，max_tokens=4096，并发4。只输入原证据与陈述，金标准不变。','',
           '| 指标 | 原Baseline | 单次v1 | v2网络补齐 | 单次v3 |','| --- | ---: | ---: | ---: | ---: |']
    metrics=[('正确数',lambda x:f"{x['correct']}/{x['count']}"),('Accuracy',lambda x:percentage(x['accuracy'])),
             ('Macro-F1',lambda x:f"{x['macro_f1']:.4f}"),('NEI Recall',lambda x:percentage(x['per_class'][NEI]['recall'])),
             ('REFUTES Precision',lambda x:percentage(x['per_class']['REFUTES']['precision'])),
             ('REFUTES Recall',lambda x:percentage(x['per_class']['REFUTES']['recall'])),
             ('SUPPORTS Recall',lambda x:percentage(x['per_class']['SUPPORTS']['recall'])),
             ('NEI误反条数',lambda x:str(x['confusion_matrix'][NEI]['REFUTES'])),
             ('合并预测解析失败',lambda x:str(x['status_counts']['parse_error'])),
             ('合并预测请求失败',lambda x:str(x['status_counts']['request_error']))]
    for title,func in metrics:lines.append('| '+title+' | '+' | '.join(func(scores[k]) for k in (*old,'prompt_v3'))+' |')
    lines+=['','差值按未四舍五入的原始分数计算。v2主跑749/885（84.63%），网络补齐后750/885（84.75%），本表使用后者；两套v2口径不混写。','',
            '## 逐条变化','','| 对照版本 | 纠正 | 退步 | 正确数净变化 | Accuracy变化（百分点） | 真反驳改NEI |','| --- | ---: | ---: | ---: | ---: | ---: |']
    for name,c in comparisons.items():
        t=c['transitions']
        lines.append(f"| {NAMES[name]} | {t.get('wrong_to_correct',0)} | {t.get('correct_to_wrong',0)} | {c['correct_delta']:+d} | {c['accuracy_delta_percentage_points']:+.2f} | {t.get('true_refutes_lost_to_nei',0)} |")
    lines+=['','## v3混淆矩阵','','| 真实\\预测 | SUPPORTS | REFUTES | NEI | 解析失败 | 请求失败 | 未完成 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for label,cells in new['confusion_matrix'].items():lines.append('| '+label+' | '+' | '.join(str(v) for v in cells.values())+' |')
    lines+=['','## 分机制结果','','| 机制 | Baseline Accuracy | v2 Accuracy | v3 Accuracy | v2 NEI Recall | v3 NEI Recall |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for mech,b in scores['baseline']['by_mechanism'].items():
        a,c=scores['prompt_v2']['by_mechanism'][mech],new['by_mechanism'][mech]
        lines.append(f"| {mech} | {percentage(b['accuracy'])} | {percentage(a['accuracy'])} | {percentage(c['accuracy'])} | {percentage(a['per_class'][NEI]['recall'])} | {percentage(c['per_class'][NEI]['recall'])} |")
    lines+=['','## 调用状态与解释边界','',
            f"v3输出错误：{json.dumps(dict(errors),ensure_ascii=False)}；失败请求尝试：{operations['failed_request_attempts']}。",'',
            f"v3成功响应可见token：{json.dumps(dict(usage),ensure_ascii=False)}；并发请求耗时之和{operations['latency_sum_seconds']:.1f}秒（非墙钟时长）。",'',
            manifest['comparison_note'],'',
            '全部挑战样本已经观察，属于开发性验证，非独立盲测。所有885条保留计分，失败或未完成不剔除；未改数据及金标准，本轮未重跑基础集或训练LoRA。原历史结果不覆盖。']
    if not result['complete']:lines+=['','本轮尚未完成，当前得分含未完成项，净变化不能作为最终提升结论。']
    (out/'全量对照报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result


def execute(out,rows,manifest,key):
    current=read_unique(out/'challenge.jsonl')
    expected={r['id']:r['label'] for r in rows}
    if set(current)-set(expected) or any(r['gold']!=expected[i] for i,r in current.items()):
        raise ValueError('已有记录含计划外ID或标签不一致')
    pending=iter(r for r in rows if r['id'] not in current)
    completed=len(current);aborted=None;started=time.perf_counter()
    def status(stage):
        write_json(out/'run_status.json',{'updated_at':stamp(),'stage':stage,'completed':completed,'target':len(rows),
                                         'complete':completed==len(rows),'aborted_reason':aborted,
                                         'session_wall_seconds':time.perf_counter()-started})
    status('running')
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            active={}
            def submit_next():
                try:row=next(pending)
                except StopIteration:return
                active[pool.submit(evaluate_one,row,None,manifest['settings']['config'],key,manifest['settings']['prompt_template'])]=row['id']
            for _ in range(4):submit_next()
            while active:
                future=next(as_completed(active));active.pop(future)
                record=future.result();record['prompt_version']='prompt-v3-frozen'
                with (out/'challenge.jsonl').open('a',encoding='utf-8') as f:
                    f.write(json.dumps(record,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
                completed+=1
                if record['status']=='request_error' or record.get('parse_error')=='thinking_not_disabled':
                    aborted=record.get('error_kind') or record.get('parse_error')
                status('stopping' if aborted else 'running')
                print(f"{completed}/{len(rows)} {record['status']}",flush=True)
                if completed%50==0:summarize(out,rows,manifest)
                if not aborted:submit_next()
    except KeyboardInterrupt:aborted='user_interrupted'
    finally:
        result=summarize(out,rows,manifest)
        status('completed' if result['complete'] else 'stopped')
    return 0 if result['complete'] else 2


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser();p.add_argument('command',choices=('prepare','run','summarize'));p.add_argument('--out',type=Path,default=OUT)
    args=p.parse_args()
    try:
        out=args.out.resolve();rows,manifest=prepare(out)
        if args.command=='run':
            key=load_key()
            if not key:raise ValueError('密钥未配置')
            if manifest['settings']['config']['model'] not in Client(manifest['settings']['config'],key).models()[0]:raise ValueError('接口模型不匹配')
            return execute(out,rows,manifest,key)
        if args.command=='summarize':summarize(out,rows,manifest)
        print(json.dumps({'prepared':True,'fresh_requests':len(rows),'prompt_sha256':manifest['settings']['prompt_sha256'],'out':str(out)},ensure_ascii=False))
        return 0
    except (APIError,ValueError,OSError) as exc:
        print('停止：'+str(exc),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
