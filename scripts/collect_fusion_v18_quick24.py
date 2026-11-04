"""Download byte-preserved quick artifacts, independently recompute, publish locally."""
import argparse
import json
from pathlib import Path
import shutil
import tarfile
import time

from collect_fusion_v18 import transport, ROOT, REMOTE
from ab_factcheck import fusion_v18_quick24 as q, finetune27b_v2 as c


def collect():
    q.verify()
    folder = ROOT / 'outputs/fusion_v18_collection' / ('quick24-' + str(time.time_ns()))
    folder.mkdir(parents=True)
    archive = folder / 'received.tar.gz'
    transport('download', REMOTE + '/setup/fusion_v18_quick24_results.tar.gz', str(archive))
    received = folder / 'received'; received.mkdir()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not member.isfile() or not (received / member.name).resolve().is_relative_to(received.resolve()):
                raise ValueError('Unsafe archive member')
        tar.extractall(received, filter='data')
    hashes = {p.relative_to(received).as_posix(): c.sha(p) for p in received.rglob('*') if p.is_file()}
    restored = c.read_json(received / 'service_recovery.json')
    if not restored.get('restored') or not restored.get('generation_checked'):
        raise ValueError('API restoration not verified')
    completion = c.read_json(received / 'completion.json')
    local = folder / 'local_recompute'; shutil.copytree(received, local)
    for part in ('validation', 'evaluation'):
        if (received / part / 'audit.json').exists():
            result = q.report(local, part)
            if result != c.read_json(received / part / 'results.json'):
                raise ValueError('Local independent recomputation differs')
    if q.physical_cost(local) != c.read_json(received / 'costs.json'):
        raise ValueError('Physical cost recomputation differs')
    if completion['status'] != 'complete':
        q.finish(local, completion['status'])
        if c.read_json(local / 'partial_results.json') != c.read_json(received / 'partial_results.json'):
            raise ValueError('Partial method metrics differ')
    if hashes != {p.relative_to(received).as_posix(): c.sha(p) for p in received.rglob('*') if p.is_file()}:
        raise ValueError('Received bytes changed')
    publish = ROOT / q.f.EXP / 'quick24_results'
    for relative in ['validation', 'evaluation']:
        for name in ('results.json', 'RESULTS.md', 'audit.json', 'predictions.csv', 'recommended_method.json'):
            path = local / relative / name
            if path.exists():
                dest = publish / relative / name; dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
    for name in ('quick_recommendation.json', 'completion.json', 'partial_results.json', 'costs.json',
                 'historical_costs.json', 'service_recovery.json', 'STATUS.md', 'launch_identity.json'):
        if (local / name).exists():
            publish.mkdir(parents=True, exist_ok=True); shutil.copy2(local / name, publish / name)
    receipt = {'verified': True, 'status': completion['status'], 'files': len(hashes),
               'archive_sha256': c.sha(archive), 'received': str(received), 'published': str(publish),
               'api_restored': True, 'original_full_plan_complete': False}
    c.save(folder / 'manifest.json', hashes); c.save(folder / 'receipt.json', receipt)
    c.save(ROOT / 'outputs/fusion_v18_collection/latest_quick24.json', receipt)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    argparse.ArgumentParser().parse_args()
    collect()
