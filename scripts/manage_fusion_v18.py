"""Isolated V18 deployment and guarded two-card stage controller.

Only devices 2/3 are assigned. The already authorized named API is restored on
completion/failure. Teacher completion deliberately stops before manual review.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tarfile
import time

BASE = Path('/root/ab_finetune27b_20261030')
WORK = BASE / 'fusion_v18_workspace'
OUT = BASE / 'fusion_v18_runs'
PYTHON = BASE / 'venv/bin/python'


def guard_module():
    spec = importlib.util.spec_from_file_location('v18_service_guard', WORK / 'scripts/finetune27b_service_guard.py')
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def env_for(device=None):
    previous = json.loads((BASE / 'revision_2_runs/formal/smoke/receipt.json').read_text())['environment']
    env = dict(os.environ, PYTHONPATH=str(WORK / 'src'), PYTHONUNBUFFERED='1')
    for key, value in previous['compute_environment'].items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    if device is not None:
        env['ASCEND_RT_VISIBLE_DEVICES'] = str(device)
    return env


def alive(path):
    return path.exists() and guard_module().matching(json.loads(path.read_text()))


def deploy():
    if (OUT / 'controller.json').exists() and alive(OUT / 'controller.json'):
        raise RuntimeError('Cannot deploy into an active stage')
    WORK.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)
    import hashlib
    with tarfile.open(BASE / 'setup/fusion_v18.tar.gz') as archive:
        for member in archive.getmembers():
            target = WORK / member.name
            if not member.isfile() or not target.resolve().is_relative_to(WORK.resolve()):
                raise ValueError('Unsafe package member')
            if '/data/raw/' in '/' + member.name or member.name.endswith('/test.jsonl') or Path(member.name).name.startswith('.env'):
                raise ValueError('Forbidden test/raw/secret package member')
            content = archive.extractfile(member).read()
            if target.exists() and hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(content).digest():
                raise ValueError('Refusing to overwrite deployed artifact: ' + member.name)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
    print(json.dumps({'deployed': str(WORK)}))


def launch(phase):
    guard = guard_module()
    if alive(OUT / 'controller.json'):
        raise RuntimeError('Controller already active')
    if (OUT / (phase + '_complete.json')).exists():
        raise RuntimeError('Stage already complete')
    if phase == 'experiment' and not (WORK / 'experiments/018_fusion/supervision/completion.json').exists():
        raise RuntimeError('All 2184 reviews must be frozen before training')
    inflight = list(OUT.rglob('*.inflight'))
    if inflight:
        raise RuntimeError('Unresolved attempts require explicit archive-unanswered accounting')
    service = json.loads((BASE / 'private/current_service.json').read_text())
    if not guard.matching(service):
        raise RuntimeError('Saved service identity no longer matches')
    guard.health('http://10.176.30.103:20027/v1', BASE / 'private/api_key')
    with (OUT / (phase + '_controller.log')).open('ab') as log:
        child = subprocess.Popen([str(PYTHON), str(Path(__file__).resolve()), 'guarded', '--phase', phase],
                cwd=WORK, env=env_for(), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    pointer = {'pid': child.pid, 'start_time': guard.proc_start(child.pid), 'phase': phase}
    (OUT / 'controller.json').write_text(json.dumps(pointer))
    print(json.dumps({'started': pointer, 'devices': [2, 3], 'api_restore_guard': True}))


def memory_preflight():
    for _ in range(20):
        text = subprocess.check_output(['bash', '-c', 'export LD_LIBRARY_PATH=/usr/local/Ascend/driver/lib64/common:/usr/local/Ascend/driver/lib64/driver:$LD_LIBRARY_PATH; npu-smi info'], text=True)
        devices, current = {}, None
        for line in text.splitlines():
            hit = re.match(r'^\|\s*(\d+)\s+910B3\b', line)
            if hit:
                current = int(hit[1])
            values = re.search(r'(\d+)\s*/\s*(\d+)\s*\|\s*$', line)
            if current is not None and values:
                used, total = map(int, values.groups()); devices[current] = {'used_mib': used, 'total_mib': total}
        if all(devices.get(d, {}).get('total_mib', 0) - devices.get(d, {}).get('used_mib', 0) >= 58000 for d in (2, 3)):
            return {str(d): devices[d] for d in (2, 3)}
        time.sleep(3)
    raise RuntimeError('Cards 2/3 lack required free HBM; restore API')


def batch(jobs):
    children = []
    try:
        pending = list(jobs)
        while pending or children:
            used = {d for d, _, _ in children}
            for device in (2, 3):
                if pending and device not in used:
                    label, args = pending.pop(0)
                    command = 'source /usr/local/Ascend/ascend-toolkit/set_env.sh && exec ' + shlex.join(
                        [str(PYTHON), '-m', 'ab_factcheck.fusion_v18_run', *args, '--output', str(OUT)])
                    with (OUT / (label + '.log')).open('ab') as log:
                        child = subprocess.Popen(['bash', '-c', command], cwd=WORK, env=env_for(device), stdout=log, stderr=subprocess.STDOUT)
                    children.append((device, label, child))
                    print(json.dumps({'job': label, 'device': device, 'pid': child.pid}), flush=True)
            for _, label, child in children:
                if child.poll() not in (None, 0):
                    (OUT / 'worker_failure.json').write_text(json.dumps({'job': label, 'returncode': child.returncode, 'time_unix': time.time()}))
                    raise RuntimeError('Stage worker failed: ' + label)
            children = [(d, label, child) for d, label, child in children if child.poll() is None]
            if children:
                time.sleep(3)
    finally:
        for _, _, child in children:
            if child.poll() is None:
                child.terminate()
        for _, _, child in children:
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait()


def paired_jobs(action, part='validation', arm='all'):
    return [(f'{action}-{part}-{worker}', [action, '--part', part, '--worker', str(worker), '--arm', arm]) for worker in (0, 1)]


def supervise(phase):
    sys.path.insert(0, str(WORK / 'src'))
    from ab_factcheck import fusion_v18 as f, finetune27b_v2 as c
    from ab_factcheck.fusion_v18_run import verify_runtime
    f.verify(); verify_runtime()
    def interrupted(signum, frame):
        raise KeyboardInterrupt('V18 controller interrupted')
    signal.signal(signal.SIGTERM, interrupted); signal.signal(signal.SIGINT, interrupted)
    c.save(OUT / ('memory_' + phase + '.json'), {'passed': True, 'devices': memory_preflight()})
    manifest = c.read_json(WORK / 'experiments/016_finetune_27b/model_source.json')
    model = BASE / 'models/Qwen3.8-27B'
    for entry in manifest['files']:
        expected = entry.get('Sha256') or entry.get('sha256')
        if expected and c.sha(model / entry['Path']) != expected:
            raise ValueError('Original model bytes changed: ' + entry['Path'])
    c.save(OUT / ('model_verified_' + phase + '.json'), {'manifest_sha256': c.sha(WORK / 'experiments/016_finetune_27b/model_source.json'), 'files': len(manifest['files'])})
    if phase == 'teachers':
        batch(paired_jobs('teachers'))
        hashes = {}
        for row in f.data('train'):
            for source in f.SOURCES:
                relative = Path('teachers') / source / (c.record_key(row) + '.json')
                r = f.check_record(c.read_json(OUT / relative)); hashes[relative.as_posix()] = r['record_sha256']
        f.immutable(OUT / 'teachers_complete.json', {'completed': True, 'records': len(hashes), 'record_hashes': hashes,
                    'next': 'Manual per-item review of 2184 explanations; training has NOT started.'})
    else:
        batch(paired_jobs('direct', arm='base_a0'))
        batch([(f'smoke-{source}', ['smoke-train', '--source', source]) for source in f.SOURCES
               if not (OUT / 'training' / source / 'smoke/receipt.json').exists()])
        batch([(f'train-{source}-{seed}', ['train', '--source', source, '--seed', str(seed)])
               for source in f.SOURCES for seed in f.SEEDS
               if not (OUT / 'training' / source / f'seed-{seed}/training_complete.json').exists()])
        batch([(f'select-{source}-{seed}', ['select', '--source', source, '--seed', str(seed)])
               for source in f.SOURCES for seed in f.SEEDS])
        for part in ('validation', 'evaluation'):
            batch(paired_jobs('direct', part)); batch(paired_jobs('fusion', part))
            subprocess.run([str(PYTHON), '-m', 'ab_factcheck.fusion_v18_report', str(OUT), '--part', part], cwd=WORK, env=env_for(), check=True)
            subprocess.run([str(PYTHON), str(WORK / 'scripts/audit_fusion_v18.py'), str(OUT), '--part', part], cwd=WORK, env=env_for(), check=True)
        from ab_factcheck.fusion_v18_report import costs
        costs(OUT)
        f.immutable(OUT / 'experiment_complete.json', {'completed': True, 'evaluation_results_sha256': c.sha(OUT / 'evaluation/results.json'),
                    'audit_sha256': c.sha(OUT / 'evaluation/audit.json')})


def guarded(phase):
    guard = guard_module()
    pointer = json.loads((BASE / 'private/current_service.json').read_text())
    if not guard.matching(pointer):
        raise RuntimeError('API identity changed before pause')
    snapshot = guard.capture(pointer['pid'])
    directory = BASE / 'private' / f'guard-fusion-v18-{phase}-{time.time_ns()}'
    (OUT / ('guard_' + phase + '.json')).write_text(json.dumps({'directory': str(directory)}))
    code = guard.guarded_run(snapshot, directory,
        [str(PYTHON), str(Path(__file__).resolve()), 'supervise', '--phase', phase],
        'http://10.176.30.103:20027/v1', BASE / 'private/api_key')
    restored = json.loads((directory / 'restored.json').read_text())
    (OUT / ('service_recovery_' + phase + '.json')).write_text(json.dumps(restored, indent=2) + '\n')
    if code:
        raise RuntimeError('Stage failed; service restoration completed')
    with tarfile.open(BASE / 'setup' / f'fusion_v18_{phase}_results.tar.gz', 'w:gz') as tar:
        for path in sorted(OUT.rglob('*')):
            if path.is_file() and path.suffix not in ('.lock', '.inflight', '.pt', '.safetensors'):
                tar.add(path, arcname=path.relative_to(OUT).as_posix())
    print(json.dumps({'phase': phase, 'completed': True, 'api_restored': True}), flush=True)


def status():
    pointer = OUT / 'controller.json'
    info = json.loads(pointer.read_text()) if pointer.exists() else {}
    groups = {source: list((OUT / 'teachers' / source).glob('*.json')) for source in ('nli', 'pj', 'joint')}
    recent, means = {}, {}
    for source, paths in groups.items():
        newest = sorted(paths, key=lambda p: p.stat().st_mtime)[-40:]
        values = [json.loads(p.read_text())['seconds'] for p in newest]
        means[source] = sum(values) / len(values) if values else None
        recent[source] = max((p.stat().st_mtime for p in paths), default=None)
    eta = sum((728 - len(groups[s])) * means[s] for s in means) / 2 if all(means.values()) else None
    result = {'running': alive(pointer), 'controller': info, 'teacher_counts': {s: len(v) for s, v in groups.items()},
              'teacher_total': sum(map(len, groups.values())), 'teacher_target': 2184, 'latest_updates_unix': recent,
              'mean_last_40_seconds': means, 'teacher_eta_seconds_estimate': eta,
              'teacher_complete': (OUT / 'teachers_complete.json').exists(),
              'experiment_complete': (OUT / 'experiment_complete.json').exists(),
              'inflight_calls': len(list(OUT.rglob('*.inflight'))),
              'last_worker_failure': json.loads((OUT / 'worker_failure.json').read_text()) if (OUT / 'worker_failure.json').exists() else None,
              'service_restored': {p.stem: json.loads(p.read_text()) for p in OUT.glob('service_recovery_*.json')}}
    print(json.dumps(result))


def archive_unanswered():
    if alive(OUT / 'controller.json'):
        raise RuntimeError('Cannot archive attempts while controller is alive')
    destination = OUT / 'interruptions' / str(time.time_ns())
    destination.mkdir(parents=True)
    records = []
    for path in OUT.rglob('*.inflight'):
        if destination in path.parents:
            continue
        relative = path.relative_to(OUT)
        target = destination / relative; target.parent.mkdir(parents=True, exist_ok=True)
        received = path.with_suffix('.json').exists()
        records.append({'path': relative.as_posix(), 'received_answer_preserved': received, 'unanswered_cost_unknown': not received})
        path.rename(target.with_suffix('.interrupted.json'))
    (destination / 'accounting.json').write_text(json.dumps(records, indent=2) + '\n')
    print(json.dumps({'archived': len(records), 'received_answers_unchanged': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['deploy', 'launch', 'guarded', 'supervise', 'status', 'archive-unanswered'])
    parser.add_argument('--phase', choices=['teachers', 'experiment'], default='teachers')
    args = parser.parse_args()
    if args.action in ('launch', 'guarded', 'supervise'):
        {'launch': launch, 'guarded': guarded, 'supervise': supervise}[args.action](args.phase)
    else:
        {'deploy': deploy, 'status': status, 'archive-unanswered': archive_unanswered}[args.action]()
