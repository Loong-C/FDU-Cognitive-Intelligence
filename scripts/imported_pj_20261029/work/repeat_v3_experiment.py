"""两次冻结v3全量复测；静默写日志，主跑与网络恢复分别评分。"""
from pathlib import Path
import collections
import contextlib
import itertools
import json
import math
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import prompt_v3_full as full
from api_client import APIError,Client,load_key
from baseline_eval import stamp
from benchmark import LABELS,parse_response,read_sources,sha,write_json
from verify_prompt_v3_full import metrics
import retry_v3_network_failures as retry

EXPERIMENT=ROOT/'results'/'v3-repeat-comparison-20261028'
RUNS=[ROOT/'results'/f'challenge-prompt-v3-repeat{i}-20261028' for i in (1,2)]
ORIGINAL=ROOT/'results'/'challenge-prompt-v3-full-20261028'


def prepare_experiment():
    prepared=[full.prepare(path) for path in RUNS]
    settings={'runs':[str(p) for p in RUNS],'prompt_sha256':prepared[0][1]['settings']['prompt_sha256'],
              'config':prepared[0][1]['settings']['config'],'primary_requests':1770,
              'original_primary_sha256':sha((ORIGINAL/'challenge.jsonl').read_bytes()),
              'original_supplemented_sha256':sha((ORIGINAL/'network-retry/supplemented-predictions.jsonl').read_bytes()),
              'driver_sha256':sha(Path(__file__).read_bytes()),
              'network_recovery_policy':'Resume pending after network failure; retry primary network failures separately once using same Client retry config. Do not retry valid predictions based on correctness.',
              'majority_tie_rule':'If three distinct valid labels, choose the original v3 run label; otherwise most common valid label. Not a new single-call score.'}
    EXPERIMENT.mkdir(exist_ok=True)
    file=EXPERIMENT/'manifest.json'
    if file.exists():assert json.loads(file.read_text(encoding='utf-8'))['settings']==settings
    else:
        write_json(file,{'created_at':stamp(),'settings':settings})
        (EXPERIMENT/'实验预案.md').write_text(
            '# v3两次全量复测预案\n\n冻结v3提示词和全部生成参数，按原顺序分两次重新请求885条挑战集，共1770条主跑请求；不复用旧预测，不改提示词、标签或模型。顺序运行，每次并发4。用户要求静默运行，过程写入文件，结束后统一报告。\n\n'
            '主跑保留请求失败计分，网络中断检查接口后续跑未完成项；网络失败另存补跑，不按预测正确与否重跑。主结果与恢复结果分别比较。\n\n'
            '报告准确率范围、三类Recall、Macro-F1、逐条一致率、反复错例和错误机制。另计算三轮多数票（全异选原轮标签）及至少一轮正确的金标准辅助上限；二者都不是新提示词单次表现。金标准辅助上限不可部署。\n\n'
            '同一885条数据重复使用，不能当成1770或2655条独立测试样本。temperature=0的复测反映当前服务/输出稳定性，不能证明提示词可达到90%，也不能证明模型能力上限低于90%。90%至少需要797/885条正确，最终统计与该门槛的距离。旧挑战集已观察，泛化仍需新保留数据验证。\n',encoding='utf-8')
    return prepared


def health(config,key):
    c=dict(config);c['timeout_seconds']=15
    for attempt in range(12):
        try:
            if c['model'] in Client(c,key).models()[0]:return
        except APIError:pass
        time.sleep(10)
    raise RuntimeError('模型接口连续检查失败，需要恢复服务后续跑')


def verify(path,rows,manifest):
    records=full.read_unique(path/'challenge.jsonl')
    assert len(records)==885 and set(records)=={r['id'] for r in rows}
    assert (path/'prompt-v3.txt').read_bytes()==(full.DRAFT/'prompt-v3.txt').read_bytes()
    assert all(sha((ROOT/name).read_bytes())==value for name,value in manifest['settings']['code_hashes'].items())
    assert all(sha(file.read_bytes())==manifest['settings']['comparator_records_sha256'][name] for name,file in full.COMPARATORS.items())
    for row in rows:
        r=records[row['id']]
        assert r['gold']==row['label'] and r['timestamp']>=manifest['created_at'] and r['evaluation_attempt']==1
        if r['status']!='request_error':assert parse_response(r['raw_response'])==(r['prediction'],r['parse_error'],r['raw_text'])
    summary=json.loads((path/'summary.json').read_text(encoding='utf-8'))
    actual=metrics(rows,records)
    for k in ('count','correct','accuracy','macro_f1'):assert abs(actual[k]-summary['scores']['prompt_v3'][k])<1e-12
    for label in LABELS:assert actual['matrix'][label]==summary['scores']['prompt_v3']['confusion_matrix'][label]
    supplemental=full.read_unique(path/'network-retry/supplemented-predictions.jsonl')
    retried=full.read_unique(path/'network-retry/retry.jsonl')
    expected={i for i,r in records.items() if r['status']=='request_error' and r.get('error_kind')=='network_error'}
    assert set(retried)==expected
    for row in rows:
        i=row['id'];a=retried.get(i)
        if a:
            assert a['gold']==row['label'] and a['evaluation_attempt']==2
            if a['status']!='request_error':assert parse_response(a['raw_response'])==(a['prediction'],a['parse_error'],a['raw_text'])
        desired=a['prediction'] if a and a['status']=='ok' else records[i]['prediction']
        assert supplemental[i]['prediction']==desired and supplemental[i]['gold']==row['label']
    write_json(path/'repeat-verification.json',{'passed':True,'unique_primary_ids':885,'fresh_primary_records':True,
                 'gold_and_frozen_prompt_unchanged':True,'primary_metrics_recomputed':True,'network_retries':len(retried)})
    return records,supplemental


def analyze(rows,verified):
    original=full.read_unique(ORIGINAL/'network-retry/supplemented-predictions.jsonl')
    records={'original_v3':original,**{f'repeat{i}':v[1] for i,v in enumerate(verified,1)}}
    all_scores={name:metrics(rows,r) for name,r in records.items()}
    paired={}
    for a,b in itertools.combinations(records,2):
        agree=sum(records[a][r['id']]['prediction']==records[b][r['id']]['prediction'] for r in rows)
        corrected=sum(records[a][r['id']]['prediction']!=r['label'] and records[b][r['id']]['prediction']==r['label'] for r in rows)
        lost=sum(records[a][r['id']]['prediction']==r['label'] and records[b][r['id']]['prediction']!=r['label'] for r in rows)
        paired[a+'__'+b]={'agreement_count':agree,'agreement_rate':agree/885,'corrected':corrected,'regressed':lost,'net':corrected-lost}
    majority={};oracle=0;always_wrong=[];flips=[]
    for row in rows:
        i=row['id'];preds=[r[i]['prediction'] for r in records.values()];valid=[p for p in preds if p in LABELS]
        counts=collections.Counter(valid)
        label=counts.most_common(1)[0][0] if counts else None
        if len(counts)==3:label=preds[0]
        majority[i]={'prediction':label,'status':'ok' if label in LABELS else 'request_error'}
        oracle+=row['label'] in valid
        if all(p!=row['label'] for p in preds):always_wrong.append(row)
        if len(set(preds))>1:flips.append({'id':i,'gold':row['label'],'mechanism':row['mechanism'],'predictions':preds})
    target=math.ceil(.90*885)
    report={'updated_at':stamp(),'complete':True,'scores':all_scores,
            'primary_scores':{f'repeat{i}':metrics(rows,v[0]) for i,v in enumerate(verified,1)},
            'paired':paired,'majority_vote':metrics(rows,majority),
            'gold_assisted_oracle_correct':oracle,'gold_assisted_oracle_accuracy':oracle/885,
            'always_wrong_count':len(always_wrong),'always_wrong_by_mechanism':dict(collections.Counter(r['mechanism'] for r in always_wrong)),
            'different_prediction_count':len(flips),'target_90_percent_correct_count':target,
            'gap_to_90':{name:target-s['correct'] for name,s in all_scores.items()}}
    write_json(EXPERIMENT/'summary.json',report);write_json(EXPERIMENT/'prediction_flips.json',flips)
    write_json(EXPERIMENT/'always_wrong.json',always_wrong)
    lines=['# v3两次全量复测与90%目标分析','',
           '冻结同一v3提示词与参数，新增两次885条全量请求；temperature=0、关闭thinking、max_tokens4096、并发4。数据与标签未改。网络失败主评分保留、恢复结果另列。','',
           '| 轮次 | 主跑正确数 | 主跑Accuracy | 网络恢复后正确数 | 恢复后Accuracy | NEI Recall | REFUTES Recall | SUPPORTS Recall |',
           '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    original_primary=metrics(rows,full.read_unique(ORIGINAL/'challenge.jsonl'))
    for name,score in all_scores.items():
        primary=original_primary if name=='original_v3' else report['primary_scores'][name]
        lines.append(f"| {name} | {primary['correct']}/885 | {primary['accuracy']:.2%} | {score['correct']}/885 | {score['accuracy']:.2%} | {score['per_class']['NOT ENOUGH INFO']['recall']:.2%} | {score['per_class']['REFUTES']['recall']:.2%} | {score['per_class']['SUPPORTS']['recall']:.2%} |")
    lines+=['','## 逐条稳定性','']
    for name,p in paired.items():lines.append(f"- {name}：预测一致{p['agreement_count']}/885（{p['agreement_rate']:.2%}），纠正{p['corrected']}、退步{p['regressed']}、净变化{p['net']:+d}。")
    lines+=['',f"三轮预测出现变化的样本{len(flips)}条；三轮始终错误{len(always_wrong)}条，机制分布{json.dumps(report['always_wrong_by_mechanism'],ensure_ascii=False)}。",'',
            f"按预先规则取三轮多数票：{report['majority_vote']['correct']}/885（{report['majority_vote']['accuracy']:.2%}）。这是三次调用的组合，不能记为单提示词单次结果。",'',
            f"利用金标准事后选择三轮中正确答案的上限为{oracle}/885（{oracle/885:.2%}）。该数使用真实标签，无法作为可部署结果；仅反映这三轮输出是否存在互补。",'',
            '## 能否据此推断90%','',
            f"至少90%需要{target}/885条正确。各轮距门槛的正确数差距：{json.dumps(report['gap_to_90'],ensure_ascii=False)}。",'',
            '如果复测仍在85%左右，可以支持当前冻结方案在当前数据与服务条件下的表现较稳定；不能推出存在一个必然可找到的提示词达到90%，也不能证明模型能力上限低于90%。85%到90%的提升仍须实际验证。', '',
            '两次复测使用的是同一885条样本，不能把结果当作1770个独立测试样本，也不能因重复运行就消除开发集过拟合。temperature=0并不使服务端输出必然逐字相同；本实验只报告实际波动，不预设其成因。','',
            '要支持90%以上的结论，需要冻结候选提示词，在同样推理预算下实际达到该分数，并用新的保留样本及基础能力回归验证。多数票或金标准辅助上限不能代替这个实证。']
    (EXPERIMENT/'两次复测对照报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return report


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    prepared=prepare_experiment();key=load_key()
    if not key:raise RuntimeError('密钥未配置')
    verified=[]
    with (EXPERIMENT/'execution.log').open('a',encoding='utf-8') as log,contextlib.redirect_stdout(log):
        for index,(path,(rows,manifest)) in enumerate(zip(RUNS,prepared),1):
            health(manifest['settings']['config'],key)
            while True:
                write_json(EXPERIMENT/'status.json',{'stage':'running','run':index,'updated_at':stamp()})
                full.execute(path,rows,manifest,key)
                status=json.loads((path/'run_status.json').read_text(encoding='utf-8'))
                file=path/'run_segments.json';segments=json.loads(file.read_text(encoding='utf-8')) if file.exists() else []
                segments.append(status);write_json(file,segments)
                if status['complete']:break
                if status['aborted_reason']!='network_error':raise RuntimeError('评测停止，需要检查输出或接口配置')
                health(manifest['settings']['config'],key)
            full.OUT=path;retry.main();verified.append(verify(path,rows,manifest))
        result=analyze(prepared[0][0],verified)
        assert sha((ORIGINAL/'challenge.jsonl').read_bytes())==json.loads((EXPERIMENT/'manifest.json').read_text(encoding='utf-8'))['settings']['original_primary_sha256']
        found=any(key in f.read_text(encoding='utf-8-sig') for base in [EXPERIMENT,*RUNS] for f in base.rglob('*') if f.is_file())
        assert not found
        write_json(EXPERIMENT/'verification.json',{'passed':True,'two_full_runs':True,'primary_records':1770,'original_unchanged':True,'key_found_in_outputs':False})
        write_json(EXPERIMENT/'status.json',{'stage':'completed','updated_at':stamp()})
    print(json.dumps({'complete':True,'correct_counts':{k:v['correct'] for k,v in result['scores'].items()}},ensure_ascii=False))


if __name__=='__main__':main()
