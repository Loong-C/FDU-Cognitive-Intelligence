"""Read-only remote status, verified collection and local independent recomputation."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ab_factcheck import fusion_v18 as f, finetune27b_v2 as c

REMOTE = '/root/ab_finetune27b_20261030'


def transport(*args):
    value = subprocess.run([sys.executable, '-W', 'ignore', str(ROOT / 'scripts/remote_finetune.py'), *args],
                           cwd=ROOT, text=True, encoding='utf-8', capture_output=True, check=True)
    return value.stdout


def collect(phase):
    folder = ROOT / 'outputs/fusion_v18_collection' / (phase + '-' + str(time.time_ns()))
    folder.mkdir(parents=True)
    archive = folder / 'received.tar.gz'
    transport('download', REMOTE + f'/setup/fusion_v18_{phase}_results.tar.gz', str(archive))
    received = folder / 'received'; received.mkdir()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not member.isfile() or not (received / member.name).resolve().is_relative_to(received.resolve()):
                raise ValueError('Unsafe result archive member')
        tar.extractall(received, filter='data')
    hashes = {p.relative_to(received).as_posix(): c.sha(p) for p in received.rglob('*') if p.is_file()}
    recovery = c.read_json(received / f'service_recovery_{phase}.json')
    if not recovery['restored'] or not recovery['generation_checked']:
        raise ValueError('API recovery not verified')
    f.verify()
    if phase == 'teachers':
        completed = c.read_json(received / 'teachers_complete.json')
        if completed['records'] != 2184:
            raise ValueError('Incomplete teacher collection')
        prompts = c.read_json(ROOT / f.EXP / 'prompts.json')
        for row in f.data('train'):
            records = []
            for source in f.SOURCES:
                relative = f'teachers/{source}/{c.record_key(row)}.json'
                record = f.check_record(c.read_json(received / relative))
                if record['record_sha256'] != completed['record_hashes'][relative]:
                    raise ValueError('Teacher record changed')
                prompt = prompts[source] if source != 'joint' else f.review_prompt(row, records, 'train')
                if record['input_sha256'] != c.digest(c.messages(row, prompt)) or record['identity']['adapter_sha256'] is not None:
                    raise ValueError('Teacher input/adapter mismatch')
                records.append(record)
    else:
        from ab_factcheck.fusion_v18_report import report
        local = folder / 'local_recompute'
        shutil.copytree(received, local)
        for part in ('validation', 'evaluation'):
            result = report(local, part)
            if result != c.read_json(received / part / 'results.json'):
                raise ValueError('Independent local recomputation differs')
            subprocess.run([sys.executable, str(ROOT / 'scripts/audit_fusion_v18.py'), str(local), '--part', part], check=True)
        publish = ROOT / f.EXP / 'results'
        for part in ('validation', 'evaluation'):
            (publish / part).mkdir(parents=True, exist_ok=True)
            for name in ('results.json', 'RESULTS.md', 'predictions.csv', 'audit.json'):
                shutil.copy2(local / part / name, publish / part / name)
        shutil.copy2(local / 'evaluation/recommended_method.json', publish / 'recommended_method.json')
        shutil.copy2(local / 'recommendation.json', publish / 'validation_recommendation.json')
        shutil.copy2(local / 'costs.json', publish / 'costs.json')
        shutil.copy2(local / 'service_recovery_experiment.json', publish / 'service_recovery.json')
    if hashes != {p.relative_to(received).as_posix(): c.sha(p) for p in received.rglob('*') if p.is_file()}:
        raise ValueError('Received bytes changed during verification')
    receipt = {'phase': phase, 'received': str(received), 'files': len(hashes), 'archive_sha256': c.sha(archive),
               'verified': True, 'api_restored': True, 'local_recompute': phase == 'experiment'}
    c.save(folder / 'manifest.json', hashes); c.save(folder / 'completion.json', receipt)
    c.save(ROOT / 'outputs/fusion_v18_collection' / f'latest_{phase}.json', receipt)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['status', 'collect'])
    parser.add_argument('--phase', choices=['teachers', 'experiment'], default='teachers')
    args = parser.parse_args()
    if args.action == 'status':
        print(transport('exec', REMOTE + '/venv/bin/python ' + REMOTE + '/fusion_v18_workspace/scripts/manage_fusion_v18.py status').strip())
    else:
        collect(args.phase)
