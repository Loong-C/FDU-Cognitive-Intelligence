"""主跑结束后，仅补请求级网络失败；保留主跑计分及原始文件。"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import prompt_v2_full as full
from api_client import load_key
from baseline_eval import evaluate_one,stamp
from benchmark import grouped_scores,read_sources,sha,write_json


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    out=full.OUT
    primary=full.read_unique(out/'challenge.jsonl')
    m=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    rows=read_sources()[0]['challenge']
    if len(primary)!=885:raise ValueError('主跑尚未完成')
    selected=[r for r in rows if primary[r['id']]['status']=='request_error' and primary[r['id']].get('error_kind')=='network_error']
    target=out/'network-retry'
    target.mkdir(exist_ok=True)
    plan={'selected_ids':[r['id'] for r in selected],'selection_rule':'primary status=request_error AND error_kind=network_error',
          'uses_gold_for_selection':False,'config':m['settings']['config'],'prompt_sha256':m['settings']['prompt_sha256'],
          'primary_records_sha256':sha((out/'challenge.jsonl').read_bytes()),
          'note':'原主结果及主评分不变；请求失败补跑另报，不重跑有效输出或按正确与否筛选。'}
    manifest_path=target/'manifest.json'
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest['settings']!=plan:raise ValueError('补跑计划不一致')
    else:
        manifest={'created_at':stamp(),'settings':plan};write_json(manifest_path,manifest)
    key=load_key()
    if not key:raise ValueError('密钥未配置')
    records=full.read_unique(target/'retry.jsonl')
    if set(records)-set(plan['selected_ids']):raise ValueError('补跑记录包含计划外ID')
    with ThreadPoolExecutor(max_workers=min(4,max(1,len(selected)))) as pool:
        active={pool.submit(evaluate_one,row,primary[row['id']],plan['config'],key,m['settings']['prompt_template']):row['id']
                for row in selected if row['id'] not in records}
        for future in as_completed(active):
            record=future.result();record['prompt_version']='prompt-v2-network-retry'
            with (target/'retry.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
            records[record['id']]=record
            print(json.dumps({'retry_completed':len(records),'target':len(selected),'status':record['status']},ensure_ascii=False),flush=True)
    merged=dict(primary)
    for i,r in records.items():
        if r['status']=='ok':merged[i]=r
    assert sha((out/'challenge.jsonl').read_bytes())==plan['primary_records_sha256']
    result={'complete':set(records)==set(plan['selected_ids']),'updated_at':stamp(),
            'primary':grouped_scores(rows,primary),'after_network_retry':grouped_scores(rows,merged),
            'retry_count':len(records),'retry_status_counts':{status:sum(r['status']==status for r in records.values()) for status in ('ok','parse_error','request_error')},
            'primary_records_unchanged':True,'primary_comparisons_unchanged':True}
    write_json(target/'summary.json',result)
    with (target/'supplemented-predictions.jsonl').open('w',encoding='utf-8') as f:
        for row in rows:
            r=merged[row['id']]
            f.write(json.dumps({k:r[k] for k in ('id','gold','prediction','status','latency_seconds')},ensure_ascii=False)+'\n')
    print(json.dumps({'complete':result['complete'],'primary_correct':result['primary']['correct'],
                      'after_network_retry_correct':result['after_network_retry']['correct'],
                      'retry_status_counts':result['retry_status_counts']},ensure_ascii=False))


if __name__=='__main__':main()
