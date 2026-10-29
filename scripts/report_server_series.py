"""Report separate fixed-method confirmations; never pool primary p values."""
from collections import defaultdict
import csv
import json

from ab_factcheck.common import ROOT, atomic_bytes, atomic_json, file_hash, now


def main():
    paths={11:'experiments/011_server_search',12:'experiments/012_server_replication',13:'experiments/013_binary_bilingual'}
    all_results={};costs={};lines=['# 内网服务器实验总览','',
        '模型为服务器返回的 `qwen38-27b`，所有请求明确关闭思考。只使用开发输入，无 SFT/LoRA 或权重更新，无题目专用提示。各轮选法和完整组独立确认单独报告，不合并 p 值或事后放宽门槛。','',
        '| 轮次 | 固定方法 | 基础 A27 → 方法 | 挑战 A27 → 方法 | 挑战增益 | 组置换 p | 预定 alpha | 主标准及幅度限制 |',
        '|---|---|---:|---:|---:|---:|---:|---|']
    for version,folder in paths.items():
        directory=ROOT/folder
        assessment=json.loads((directory/'assessment.json').read_text(encoding='utf-8'))
        audit=json.loads((directory/'audit.json').read_text(encoding='utf-8'));assert audit['passed']
        costs[str(version)]={'responses':audit.get('new_responses',audit.get('raw_responses')),'tokens':audit.get('new_tokens',audit.get('tokens'))}
        winner=assessment.get('winner','nli')
        if version==12:
            methods=assessment['methods'];csvpath=directory/'predictions.csv'
        else:
            report=json.loads((directory/'confirm/metrics.json').read_text(encoding='utf-8'))
            methods={m:e['metrics'] for m,e in report['methods'].items()};csvpath=directory/'confirm/predictions.csv'
        with csvpath.open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
        mech=defaultdict(lambda:{'n':0,'baseline_correct':0,'method_correct':0,'groups':set()})
        for row in rows:
            entry=mech[row['dataset']+'/'+row['mechanism']];entry['n']+=1
            entry['baseline_correct']+=row['baseline']==row['gold'];entry['method_correct']+=row[winner]==row['gold'];entry['groups'].add(row['group'])
        for entry in mech.values():entry['groups']=len(entry['groups'])
        all_results[str(version)]={'method':winner,'methods':methods,'statistics':assessment['statistics'],'alpha':assessment['alpha_spent'],
            'primary_passed':assessment['primary_and_guardrails_passed'],'mechanisms':dict(mech),'assessment_sha256':file_hash(directory/'assessment.json'),
            'audit_sha256':file_hash(directory/'audit.json'),'predictions_sha256':file_hash(csvpath)}
        a,b=methods[winner],methods['baseline'];s=assessment['statistics']['challenge']
        lines.append(f"| V{version} | {winner} | {b['basic']['correct']}/{b['basic']['n']} → {a['basic']['correct']}/{a['basic']['n']} | {b['challenge']['correct']}/{b['challenge']['n']} → {a['challenge']['correct']}/{a['challenge']['n']} | {s['accuracy_delta']*100:+.2f} pp | {s['one_sided_group_permutation_p']:.8f} | {assessment['alpha_spent']} | {'通过' if assessment['primary_and_guardrails_passed'] else '未通过'} |")
    lines+=['','V13 的挑战确认只覆盖六种剩余机制，SETCLOSE 没有未使用开发组。V11/V12 覆盖七种机制；下表分轮列出结果，不能把旧机制结果说成 V13 的新确认，也不能当作测试集结果。幅度限制不是总体统计非劣效证明。', '',
        '## 挑战集分机制结果','','| 轮次 | 机制 | 完整组数 | A27 | 方法 | 准确率差 |','|---|---|---:|---:|---:|---:|']
    for version,result in all_results.items():
        for name,entry in sorted(result['mechanisms'].items()):
            if not name.startswith('challenge/'):continue
            n=entry['n'];b,a=entry['baseline_correct'],entry['method_correct']
            lines.append(f"| V{version} | {name.split('/')[1]} | {entry['groups']} | {b}/{n} | {a}/{n} | {(a-b)/n*100:+.2f} pp |")
    directory14=ROOT/'experiments/014_semantic_binary'
    audit14=json.loads((directory14/'audit.json').read_text(encoding='utf-8'));assert audit14['passed']
    result14=json.loads((directory14/'assessment.json').read_text(encoding='utf-8'))
    costs['14']={'responses':audit14['new_responses'],'tokens':audit14['new_tokens']}
    lines+=['','## V14 旧开发组补充探索','',
        '直接矛盾概率、先简短依据再作正反二元判断均只在旧开发组上筛选。最好的 proof_pair 为基础 21/21、挑战 18/21；既有 NLI 为 21/21、17/21。未达到事前挑战至少多对 2 题的扩展标准，按规则停止；没有独立确认或显著性声明。V13 的固定 NLI 确认不因此换方法。',
        '',f"V11–V14 共 {sum(c['responses'] for c in costs.values()):,} 次正式模型响应、{sum(c['tokens'] for c in costs.values()):,} tokens（不含人工短文本能力探针）。成本按唯一原始响应去重，探索复用的响应不重复计费。",'',
        '## 可复现材料','',
        '- 方法与逻辑对应：`docs/server_nli_method.md`。',
        '- 可移植请求模板：`experiments/server_summary/recommended_method.json`。',
        '- 原始请求与响应：`outputs/server_v11/records`、`outputs/server_v12/records`、`outputs/server_v13/records`、`outputs/server_v14/records`。',
        '- 固定协议、结果、审计：`experiments/011_server_search`、`experiments/012_server_replication`、`experiments/013_binary_bilingual`、`experiments/014_semantic_binary`。',
        '- 各轮审计脚本：`scripts/audit_server_v11.py`、`scripts/audit_server_v12.py`、`scripts/audit_server_v13.py`、`scripts/audit_server_v14.py`。',
        '- API 端点与密钥读取约定：`docs/qwen38_server_api.md`；报告及缓存不保存密钥。','']
    directory=ROOT/'experiments/server_summary'
    atomic_json(directory/'summary.json',{'generated_at':now(),'rounds':all_results,'exploration_v14':result14,'costs':costs,'pooled_primary_test':False,'test_files_read':False})
    atomic_bytes(directory/'RESULTS.md','\n'.join(lines).encode('utf-8'))
    print(json.dumps({'rounds':{v:{'method':r['method'],'primary_passed':r['primary_passed']} for v,r in all_results.items()}},ensure_ascii=False))


if __name__=='__main__':main()
