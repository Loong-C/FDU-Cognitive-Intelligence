"""冻结通用草案，分开评测挑战集和基础集；支持原样续跑。"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import time

from api_client import ROOT, Client, APIError, load_config, load_key
from baseline_eval import evaluate_one, stamp
from benchmark import read_sources, sha, digest, write_json, grouped_scores, parse_response

DRAFT = ROOT / 'results/prompt-general-draft-20261028'
OUT = ROOT / 'results/general-full-20261029'
INSERT = ('Evaluate the whole claim using only facts stated in the evidence and their necessary logical consequences. '
          'Distinguish what is established from what would require an additional assumption. '
          'Respect the meaning and scope of every qualification in both the evidence and the claim. '
          'Lack of support alone does not establish a contradiction. '
          'Choose NOT ENOUGH INFO when neither support nor contradiction is established. '
          'Apply the same standard to every input.\n\n')


def unique(path):
    records = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r['id'] in records:
                raise ValueError('重复ID，保留现场')
            records[r['id']] = r
    return records


def recovery_targets(rows, records):
    return [r for r in rows if records[r['id']]['status'] == 'request_error'
            and records[r['id']].get('error_kind') == 'network_error']


def merged_records(primary, retries):
    merged = dict(primary)
    for i, r in retries.items():
        if r['status'] == 'ok':
            merged[i] = r
    return merged


def prepare():
    datasets, original, audit = read_sources()
    prompt = (DRAFT / 'prompt-general.txt').read_text(encoding='utf-8').removesuffix('\n')
    meta = json.loads((DRAFT / 'draft-manifest.json').read_text(encoding='utf-8'))
    assert sha(prompt.encode()) == meta['prompt_sha256']
    assert prompt.count(INSERT) == 1 and prompt.replace(INSERT, '', 1) == original
    config = load_config(ROOT / 'config-4096.json')
    baseline = ROOT / 'results/full-4096-20261027'
    bm = json.loads((baseline / 'manifest.json').read_text(encoding='utf-8'))
    assert config == bm['settings']['config'] and original == bm['prompt_template']
    settings = {'config': config, 'workers': 4, 'prompt_template': prompt,
                'prompt_sha256': sha(prompt.encode()), 'original_prompt_sha256': sha(original.encode()),
                'data_audit': audit, 'selected_ids': {k: [r['id'] for r in v] for k, v in datasets.items()},
                'baseline_hashes': {k: sha((baseline / (k + '.jsonl')).read_bytes()) for k in datasets},
                'code_hashes': {n: sha((ROOT / n).read_bytes()) for n in
                                ('general_full.py', 'api_client.py', 'baseline_eval.py', 'benchmark.py')},
                'input_fields': ['evidence', 'claim'], 'examples': 0,
                'network_recovery': 'Retry only final network failures separately; retain primary results. Never select by correctness.'}
    OUT.mkdir(exist_ok=True)
    file = OUT / 'manifest.json'
    if file.exists():
        manifest = json.loads(file.read_text(encoding='utf-8'))
        assert manifest['settings'] == settings
    else:
        assert not any(OUT.iterdir())
        manifest = {'created_at': stamp(), 'fingerprint': digest(settings), 'settings': settings,
                    'evaluation_scope': 'Both previously observed datasets; development evaluation, not independent blind testing.'}
        write_json(file, manifest)
        (OUT / 'prompt-general.txt').write_text(prompt + '\n', encoding='utf-8')
        (OUT / '与A组提示词的差异.txt').write_text(INSERT, encoding='utf-8')
    return datasets, prompt, config, manifest


def health(config, key):
    c = dict(config)
    c['timeout_seconds'] = 15
    for _ in range(12):
        try:
            if c['model'] in Client(c, key).models()[0]:
                return
        except APIError:
            pass
        time.sleep(10)
    raise RuntimeError('模型接口不可用，保留已完成记录后停止，可恢复续跑')


def progress(datasets, phase, name):
    counts = {k: len(unique(OUT / (k + '.jsonl'))) for k in datasets}
    write_json(OUT / 'run_status.json', {'updated_at': stamp(), 'stage': phase, 'dataset': name,
                                        'completed': counts, 'target': {k: len(v) for k, v in datasets.items()}})


def evaluate(rows, path, previous, prompt, config, key, datasets, name, phase):
    records = unique(path)
    assert set(records) <= {r['id'] for r in rows}
    pending = [r for r in rows if r['id'] not in records]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for start in range(0, len(pending), 4):
            futures = [pool.submit(evaluate_one, r, previous.get(r['id']), config, key, prompt)
                       for r in pending[start:start + 4]]
            batch = []
            for future in as_completed(futures):
                r = future.result()
                with path.open('a', encoding='utf-8') as f:
                    f.write(json.dumps(r, ensure_ascii=False) + '\n')
                    f.flush()
                    os.fsync(f.fileno())
                records[r['id']] = r
                batch.append(r)
                print(f'{name} {phase}: {len(records)}/{len(rows)} {r["status"]}', flush=True)
            progress(datasets, phase, name)
            if any(r.get('parse_error') == 'thinking_not_disabled' or
                   r['status'] == 'request_error' and r.get('error_kind') != 'network_error' for r in batch):
                raise RuntimeError('非网络错误，保留记录并停止检查')
            if batch and all(r['status'] == 'request_error' for r in batch):
                health(config, key)
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    datasets, prompt, config, manifest = prepare()
    if args.prepare:
        print(json.dumps({'prepared': True, 'counts': {k: len(v) for k, v in datasets.items()},
                          'single_insertion_only': True, 'prompt_sha256': sha(prompt.encode())}))
        return
    key = load_key()
    if not key:
        raise RuntimeError('未配置密钥')
    health(config, key)
    scores = {}
    try:
        for name, rows in datasets.items():
            progress(datasets, 'primary', name)
            primary = evaluate(rows, OUT / (name + '.jsonl'), {}, prompt, config, key, datasets, name, 'primary')
            assert len(primary) == len(rows)
            targets = recovery_targets(rows, primary)
            write_json(OUT / (name + '-retry-plan.json'), {'selected_ids': [r['id'] for r in targets],
                                                          'uses_gold_for_selection': False})
            retry = evaluate(targets, OUT / (name + '-network-retry.jsonl'), primary, prompt,
                             config, key, datasets, name, 'network_recovery')
            merged = merged_records(primary, retry)
            with (OUT / (name + '-supplemented.jsonl')).open('w', encoding='utf-8') as f:
                for row in rows:
                    f.write(json.dumps(merged[row['id']], ensure_ascii=False) + '\n')
            for row in rows:
                for record in [primary[row['id']], *([retry[row['id']]] if row['id'] in retry else [])]:
                    assert record['gold'] == row['label'] and record['timestamp'] >= manifest['created_at']
                    if record['status'] != 'request_error':
                        assert parse_response(record['raw_response']) == (record['prediction'], record['parse_error'], record['raw_text'])
            scores[name] = {'primary': grouped_scores(rows, primary), 'after_network_retry': grouped_scores(rows, merged),
                            'baseline': grouped_scores(rows, unique(ROOT / 'results/full-4096-20261027' / (name + '.jsonl'))),
                            'network_retries': len(retry)}
            for variant, records in [('primary', primary), ('after_network_retry', merged)]:
                assert scores[name][variant]['correct'] == sum(records[r['id']]['prediction'] == r['label'] for r in rows)
            write_json(OUT / 'summary.json', {'updated_at': stamp(), 'complete': len(scores) == len(datasets), 'datasets': scores})
        for name, h in manifest['settings']['baseline_hashes'].items():
            assert sha((ROOT / 'results/full-4096-20261027' / (name + '.jsonl')).read_bytes()) == h
        for name, h in manifest['settings']['code_hashes'].items():
            assert sha((ROOT / name).read_bytes()) == h
        assert not any(key in p.read_text(encoding='utf-8-sig') for p in OUT.rglob('*') if p.is_file())
        write_json(OUT / 'verification.json', {'passed': True, 'primary_records': 1785,
                                              'baseline_unchanged': True, 'raw_output_parse_checked': True,
                                              'independent_correct_counts_checked': True, 'key_found': False})
        lines = ['# 通用提示词全量对照', '', '两份集合分开评分；网络恢复只针对请求级网络失败，主结果保留。', '',
                 '| 集合 | 原始baseline | 通用主跑 | 通用网络恢复后 |', '| --- | ---: | ---: | ---: |']
        for name, s in scores.items():
            values = [s[k] for k in ['baseline', 'primary', 'after_network_retry']]
            lines.append('| ' + name + ' | ' + ' | '.join(f'{v["correct"]}/{v["count"]} ({v["accuracy"]:.2%})' for v in values) + ' |')
        lines += ['', '详细各类召回、混淆矩阵与机制结果见summary.json。当前数据已参与开发，不能称独立盲测。']
        (OUT / '对照报告.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        progress(datasets, 'completed', 'all')
        print('completed', flush=True)
    except Exception:
        progress(datasets, 'stopped', 'see_error_log')
        raise


if __name__ == '__main__':
    main()
