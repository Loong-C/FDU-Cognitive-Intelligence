"""数据审计、确定性抽样、输出解析与三分类评分。"""
from __future__ import annotations

import collections
import hashlib
import json
import random
import re
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
LABELS = ('SUPPORTS', 'REFUTES', 'NOT ENOUGH INFO')
DATASETS = {'challenge': ('核心挑战集.jsonl', 885), 'basic': ('基础能力集.jsonl', 900)}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def read_sources():
    archive = ROOT.parent / 'benchmark_1011(1).zip'
    with ZipFile(archive) as z:
        blobs = {name: z.read(name) for name in ['数据说明.md'] + [v[0] for v in DATASETS.values()]}
    # 保留A方原始字节；已有副本发生变化时停止，避免覆盖任何内容。
    target = ROOT / 'data'
    target.mkdir(exist_ok=True)
    for name, blob in blobs.items():
        p = target / name
        if p.exists() and p.read_bytes() != blob:
            raise ValueError(f'数据副本与原件不一致，保留现场并停止：{name}')
        if not p.exists():
            p.write_bytes(blob)
    match = re.search(r'```text\r?\n(.*?)\r?\n```', blobs['数据说明.md'].decode('utf-8-sig'), re.S)
    if match is None:
        raise ValueError('A方数据说明中没有找到原始提示词')
    prompt = match.group(1).replace('\r\n', '\n')
    if not prompt.startswith('System: ') or '{evidence}' not in prompt or '{claim}' not in prompt:
        raise ValueError('A方提示词格式发生变化，需人工核对')
    datasets, audit = {}, {}
    for key, (name, expected) in DATASETS.items():
        rows = [json.loads(s) for s in blobs[name].decode('utf-8-sig').splitlines() if s.strip()]
        if len(rows) != expected:
            raise ValueError(f'{name}应为{expected}条，实际{len(rows)}条')
        ids, pairs = set(), {}
        for row in rows:
            for field in ('id', 'group', 'evidence', 'claim', 'label', 'mechanism'):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    raise ValueError(f'{name}缺少有效的{field}')
            if row['id'] in ids or row['label'] not in LABELS:
                raise ValueError(f'{name}存在重复ID或非法标签')
            ids.add(row['id'])
            pair = (row['evidence'], row['claim'])
            if pair in pairs and pairs[pair] != row['label']:
                raise ValueError(f'{name}存在相同输入的冲突标签')
            pairs[pair] = row['label']
        datasets[key] = rows
        audit[key] = {'filename': name, 'sha256': sha(blobs[name]), 'count': len(rows),
                      'groups': len({r['group'] for r in rows}),
                      'labels': dict(collections.Counter(r['label'] for r in rows)),
                      'mechanisms': dict(collections.Counter(r['mechanism'] for r in rows)),
                      'human_review_status': dict(collections.Counter(r.get('human_review_status') for r in rows)),
                      'duplicate_input_count': len(rows) - len(pairs)}
    audit['cross_dataset_group_overlap'] = len({r['group'] for r in datasets['challenge']} & {r['group'] for r in datasets['basic']})
    audit['cross_dataset_id_overlap'] = len({r['id'] for r in datasets['challenge']} & {r['id'] for r in datasets['basic']})
    audit['source_zip_sha256'] = sha(archive.read_bytes())
    audit['prompt_sha256'] = sha(prompt.encode('utf-8'))
    return datasets, prompt, audit


def messages_for(row, prompt):
    system, user = prompt.split('\n\n', 1)
    # 使用一次正则替换，避免证据中的花括号或占位字样被再次替换。
    user = re.sub(r'\{(evidence|claim)\}', lambda m: row[m.group(1)], user)
    return [{'role': 'system', 'content': system.removeprefix('System: ')},
            {'role': 'user', 'content': user}]


def sample_rows(rows, limit, seed):
    if limit is None or limit >= len(rows):
        return list(rows)
    if limit < 1:
        raise ValueError('抽样数必须为正整数')
    rng = random.Random(seed)
    buckets = collections.defaultdict(list)
    for row in rows:
        buckets[(row['mechanism'], row['label'])].append(row)
    keys = sorted(buckets)
    rng.shuffle(keys)
    for values in buckets.values():
        rng.shuffle(values)
    chosen = []
    while len(chosen) < limit:
        for key in keys:
            if buckets[key]:
                chosen.append(buckets[key].pop())
                if len(chosen) == limit:
                    break
    selected = {r['id'] for r in chosen}
    return [r for r in rows if r['id'] in selected]


def parse_response(data):
    try:
        choice = data['choices'][0]
        message = choice['message']
        content = message['content']
        finish = choice['finish_reason']
    except (KeyError, IndexError, TypeError):
        return None, 'invalid_response_shape', ''
    if not isinstance(content, str):
        return None, 'non_text_content', ''
    if message.get('reasoning_content') or message.get('reasoning'):
        return None, 'thinking_not_disabled', content
    if finish != 'stop':
        return None, 'truncated' if finish == 'length' else 'unexpected_finish_reason', content
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return None, 'empty_content', content
    match = re.fullmatch(r'Verdict: (SUPPORTS|REFUTES|NOT ENOUGH INFO)', lines[-1])
    return (match.group(1), None, content) if match else (None, 'invalid_final_line', content)


def score(rows, records):
    columns = list(LABELS) + ['PARSE_ERROR', 'REQUEST_ERROR', 'PENDING']
    matrix = {label: {p: 0 for p in columns} for label in LABELS}
    statuses = collections.Counter()
    latencies = []
    for row in rows:
        record = records.get(row['id'])
        status = record['status'] if record else 'pending'
        statuses[status] += 1
        prediction = record.get('prediction') if record else None
        if prediction not in LABELS:
            prediction = {'parse_error': 'PARSE_ERROR', 'request_error': 'REQUEST_ERROR', 'pending': 'PENDING'}[status]
        matrix[row['label']][prediction] += 1
        if record:
            latencies.append(record['latency_seconds'])
    per_class = {}
    for label in LABELS:
        tp = matrix[label][label]
        support = sum(matrix[label].values())
        predicted = sum(matrix[gold][label] for gold in LABELS)
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else None
        f1 = 2 * tp / (support + predicted) if support + predicted else 0.0
        per_class[label] = {'support': support, 'precision': precision, 'recall': recall, 'f1': f1}
    n = len(rows)
    correct = sum(matrix[label][label] for label in LABELS)
    completed = n - statuses['pending']
    valid = statuses['ok']
    latencies.sort()
    return {'count': n, 'completed': completed, 'correct': correct,
            'accuracy': correct / n if n else None,
            'macro_f1': sum(p['f1'] for p in per_class.values()) / 3,
            'per_class': per_class, 'confusion_matrix': matrix,
            'status_counts': {s: statuses[s] for s in ('ok', 'parse_error', 'request_error', 'pending')},
            'parse_failure_rate': statuses['parse_error'] / completed if completed else None,
            'request_failure_rate': statuses['request_error'] / completed if completed else None,
            'valid_prediction_coverage': valid / n if n else None,
            'accuracy_on_valid_only': correct / valid if valid else None,
            'mean_latency_seconds': sum(latencies) / len(latencies) if latencies else None,
            'p95_latency_seconds': latencies[max(0, (95 * len(latencies) + 99) // 100 - 1)] if latencies else None}


def grouped_scores(rows, records):
    result = score(rows, records)
    result['by_mechanism'] = {m: score([r for r in rows if r['mechanism'] == m], records)
                              for m in sorted({r['mechanism'] for r in rows})}
    result['by_evidence_condition'] = {m: score([r for r in rows if r.get('evidence_condition') == m], records)
                                      for m in sorted({r['evidence_condition'] for r in rows if 'evidence_condition' in r})}
    return result
