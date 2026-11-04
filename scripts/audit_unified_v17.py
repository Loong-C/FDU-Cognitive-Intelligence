"""Independent raw-answer/denominator/metric/group-test audit; no model calls."""
import argparse
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import re
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT/'experiments/017_unified_comparison'
LABELS = ('SUPPORTS','REFUTES','NOT ENOUGH INFO')
FAMILIES = {'baseline':['baseline'],'nli':['nli'],'pj_v3':['pj_v3'],
            'lora':['lora42','lora43','lora44']}
ARMS = sum(FAMILIES.values(), [])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',',':')).encode()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def parse(record):
    lines = record['text'].strip().splitlines()
    raw = record.get('raw_text','').lower()
    if not record['finished'] or '<think' in raw or '</think' in raw or record.get('thinking_generated'):
        return 'INVALID'
    last = next((line.strip() for line in reversed(lines) if line.strip()), '')
    match = re.fullmatch(r'Verdict: (SUPPORTS|REFUTES|NOT ENOUGH INFO)', last)
    return match[1] if match else 'INVALID'


def group_p(values):
    # Polynomial coefficients count subset sums of absolute group effects.
    weights = [abs(v) for v in values if v]
    coefficients = [1]
    for weight in weights:
        new = coefficients+[0]*weight
        for i, n in enumerate(coefficients):
            new[i+weight] += n
        coefficients = new
    total, observed = sum(weights), abs(sum(values))
    return sum(n for i,n in enumerate(coefficients) if abs(2*i-total) >= observed)/2**len(weights)


def close(a,b):
    if abs(a-b) > 1e-11:
        raise ValueError(f'Independent calculation differs: {a} versus {b}')


def audit(output):
    freeze = sha(EXP/'freeze.json')
    for name, expected in load(EXP/'freeze.json').items():
        if sha(ROOT/name) != expected:
            raise ValueError('Frozen dependency changed: '+name)
    protocol, prompts = load(EXP/'protocol.json'), load(EXP/'prompts.json')
    rows = [json.loads(line) for line in (EXP/'evaluation.jsonl').read_text(encoding='utf-8').splitlines()]
    result = load(output/'results.json')
    assert result['freeze_sha256'] == freeze
    assert len(rows) == 261 and len({(r['dataset'],r['id']) for r in rows}) == 261
    by_arm = {a:[] for a in ARMS}
    identities = [load(output/f'worker-{i}-identity.json') for i in range(2)]
    for i in range(2):
        completion = load(output/f'worker-{i}-complete.json')
        assert completion == {'complete':True,'n':len(rows[i::2])*6,'freeze_sha256':freeze}
    for key in ('packages','precision','attention','gated_delta','code_sha256','device_name',
                'model_manifest_sha256','engine_sha256','adapter_parameter_dtypes','backbone_parameter_dtypes'):
        assert identities[0]['environment'][key] == identities[1]['environment'][key]
    assert not list((output/'records').rglob('*.inflight'))
    for a in ARMS:
        assert len(list((output/'records'/a).glob('*.json'))) == len(rows)
    for i,row in enumerate(rows):
        input_hashes = []
        for a in ARMS:
            name = row['dataset']+'_'+row['id']
            record = load(output/'records'/a/(name+'.json'))
            assert record['worker'] == i%2 and record['arm'] == a
            assert record['dataset'] == row['dataset'] and record['id'] == row['id']
            assert record['freeze_sha256'] == freeze
            assert record['worker_identity_sha256'] == digest(identities[i%2])
            assert record['record_sha256'] == digest({k:v for k,v in record.items() if k != 'record_sha256'})
            assert result['record_hashes'][a+'/'+name] == record['record_sha256']
            messages = [{'role':'system','content':prompts[a]['system']},
                        {'role':'user','content':prompts[a]['user'].format(evidence=row['evidence'],claim=row['claim'])}]
            assert record['input_sha256'] == digest(messages)
            assert record['prediction'] == parse(record)
            assert record['output_tokens'] == len(record['output_token_ids'])
            if a in ('baseline','lora42','lora43','lora44'):
                input_hashes.append(record['input_token_sha256'])
            by_arm[a].append(record)
        assert len(set(input_hashes)) == 1
    summary = {}
    for dataset in ('basic','challenge'):
        indices = [i for i,row in enumerate(rows) if row['dataset'] == dataset]
        summary[dataset] = {}
        for a in ARMS:
            expected = result['datasets'][dataset]['scores'][a]
            gold = [rows[i]['label'] for i in indices]
            predicted = [by_arm[a][i]['prediction'] for i in indices]
            correct = sum(x==y for x,y in zip(gold,predicted))
            assert correct == expected['correct'] and len(indices) == expected['n']
            assert predicted.count('INVALID') == expected['invalid']
            close(correct/len(indices), expected['accuracy'])
            f1s = []
            for label in LABELS:
                tp = sum(g==p==label for g,p in zip(gold,predicted))
                support, positive = gold.count(label), predicted.count(label)
                recall, precision = tp/support, tp/positive if positive else 0
                f1 = 2*tp/(support+positive)
                close(recall, expected['classes'][label]['recall'])
                close(precision, expected['classes'][label]['precision'])
                close(f1, expected['classes'][label]['f1']); f1s.append(f1)
                for pred in (*LABELS,'INVALID'):
                    assert sum(g==label and p==pred for g,p in zip(gold,predicted)) == expected['confusion_matrix'][label][pred]
            close(mean(f1s),expected['macro_f1'])
            for mechanism, metric in expected['mechanisms'].items():
                subset = [i for i in indices if rows[i]['mechanism'] == mechanism]
                right = sum(rows[i]['label'] == by_arm[a][i]['prediction'] for i in subset)
                assert len(subset) == metric['n'] and right == metric['correct']
                close(right/len(subset),metric['accuracy'])
            assert sum(by_arm[a][i]['input_tokens'] for i in indices) == expected['input_tokens']
            assert sum(by_arm[a][i]['output_tokens'] for i in indices) == expected['output_tokens']
            close(mean(by_arm[a][i]['seconds'] for i in indices), expected['latency_mean_seconds'])
            summary[dataset][a] = correct
        pairs = result['datasets'][dataset]['pairs']
        assert {(v['left'],v['right']) for v in pairs} == set(itertools.combinations(FAMILIES,2))
        for v in pairs:
            effects = Counter()
            for i in indices:
                scores = {}
                for family in (v['left'],v['right']):
                    arms = FAMILIES[family]
                    scores[family] = sum(by_arm[a][i]['prediction'] == rows[i]['label'] for a in arms)*(3//len(arms))
                effects[rows[i]['group']] += scores[v['right']]-scores[v['left']]
            close(group_p(list(effects.values())),v['p'])
            close(sum(effects.values())/(3*len(indices)),v['accuracy_delta'])
        ordered = sorted(pairs,key=lambda v:v['p'])
        for i,v in enumerate(ordered):
            close(min(1,max((6-j)*ordered[j]['p'] for j in range(i+1))),v['holm_p'])
    # Independently verify every reported safeguard and baseline acceptance flag.
    safeguards = {}
    for a in ARMS[1:]:
        passed = True
        for d in ('basic','challenge'):
            scores = result['datasets'][d]['scores']; base, current = scores['baseline'],scores[a]
            if d == 'basic':
                passed &= current['accuracy'] >= base['accuracy']-.02-1e-12
            passed &= all(current['classes'][l]['recall'] >= base['classes'][l]['recall']-.05-1e-12 for l in LABELS)
        assert passed == result['guardrails'][a]['passed']
        safeguards[a] = passed
    for v in result['datasets']['challenge']['pairs']:
        if v['left'] == 'baseline':
            passed = v['accuracy_delta'] >= .05-1e-12 and v['holm_p'] <= .05 and all(safeguards[a] for a in FAMILIES[v['right']])
            assert passed == result['baseline_success'][v['right']]
    value = {'passed':True,'records':1566,'independent_correct_counts':summary,
             'results_sha256':sha(output/'results.json'),'freeze_sha256':freeze,
             'scope':protocol['data_scope']}
    (output/'audit.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('output',type=Path)
    print(json.dumps(audit(parser.parse_args().output),indent=2))
