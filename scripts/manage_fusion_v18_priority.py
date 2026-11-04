"""Additive priority controller; preserves the original frozen full pipeline."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
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


def original():
    spec = importlib.util.spec_from_file_location('original_manager', WORK / 'scripts/manage_fusion_v18.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def verify():
    sys.path.insert(0, str(WORK / 'src'))
    from ab_factcheck import fusion_v18_priority as priority
    return priority.verify()


def launch():
    verify()
    manager = original(); guard = manager.guard_module()
    if manager.alive(OUT / 'controller.json'):
        raise RuntimeError('Existing controller still active')
    if (OUT / 'experiment_complete.json').exists() or list(OUT.rglob('*.inflight')):
        raise RuntimeError('Completed experiment or unresolved attempts')
    service = json.loads((BASE / 'private/current_service.json').read_text())
    if not guard.matching(service):
        raise RuntimeError('Service identity changed')
    guard.health('http://10.176.30.103:20027/v1', BASE / 'private/api_key')
    history = OUT / 'priority/transitions' / str(time.time_ns())
    history.mkdir(parents=True)
    for name in ('controller.json', 'service_recovery_experiment.json', 'worker_failure.json', 'guard_experiment.json'):
        path = OUT / name
        if path.exists():
            path.rename(history / name)
    with (OUT / 'priority_controller.log').open('ab') as log:
        child = subprocess.Popen([str(PYTHON), str(Path(__file__).resolve()), 'guarded'],
                  cwd=WORK, env=manager.env_for(), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    pointer = {'pid': child.pid, 'start_time': guard.proc_start(child.pid), 'phase': 'experiment_priority'}
    (OUT / 'controller.json').write_text(json.dumps(pointer))
    print(json.dumps({'started': pointer, 'devices': [2, 3], 'api_restore_guard': True}))


def paired(stage):
    manager = original(); children = []
    try:
        for worker, device in enumerate((2, 3)):
            label = f'priority-{stage}-{worker}'
            args = [str(PYTHON), '-m', 'ab_factcheck.fusion_v18_priority', 'worker',
                    '--stage', stage, '--worker', str(worker), '--output', str(OUT)]
            command = 'source /usr/local/Ascend/ascend-toolkit/set_env.sh && exec ' + shlex.join(args)
            with (OUT / (label + '.log')).open('ab') as log:
                child = subprocess.Popen(['bash', '-c', command], cwd=WORK, env=manager.env_for(device),
                                         stdout=log, stderr=subprocess.STDOUT)
            children.append(child)
            print(json.dumps({'job': label, 'device': device, 'pid': child.pid}), flush=True)
        while any(child.poll() is None for child in children):
            failed = [child for child in children if child.poll() not in (None, 0)]
            if failed:
                raise RuntimeError('Priority worker failed: ' + stage)
            time.sleep(3)
        if any(child.returncode for child in children):
            raise RuntimeError('Priority worker failed: ' + stage)
    except BaseException as error:
        (OUT / 'worker_failure.json').write_text(json.dumps({'job': 'priority-'+stage,
                    'error_type': type(error).__name__, 'time_unix': time.time()}))
        raise
    finally:
        for child in children:
            if child.poll() is None: child.terminate()
        for child in children:
            try: child.wait(timeout=20)
            except subprocess.TimeoutExpired: child.kill(); child.wait()


def supervise():
    manifest, _ = verify()
    manager = original()
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Priority supervisor interrupted')
    signal.signal(signal.SIGTERM, interrupted); signal.signal(signal.SIGINT, interrupted)
    from ab_factcheck import fusion_v18 as f, finetune27b_v2 as c
    from ab_factcheck import fusion_v18_priority as priority
    c.save(OUT / 'memory_priority.json', {'passed': True, 'devices': manager.memory_preflight()})
    source = c.read_json(WORK / 'experiments/016_finetune_27b/model_source.json')
    for entry in source['files']:
        expected = entry.get('Sha256') or entry.get('sha256')
        if expected and c.sha(BASE / 'models/Qwen3.8-27B' / entry['Path']) != expected:
            raise ValueError('Original model changed')
    for stage in manifest['stage_order']:
        if not (OUT / 'priority' / stage / 'audit.json').exists():
            paired(stage)
        priority.report(OUT, stage)
        print(json.dumps({'stage_complete': stage, 'report': str(OUT / 'priority' / stage / 'RESULTS.md')}), flush=True)
    # All early answers have unchanged physical identities and are reused here.
    print(json.dumps({'priority_complete': True, 'next': 'original_full_experiment'}), flush=True)
    manager.supervise('experiment')


def guarded():
    manager = original(); guard = manager.guard_module()
    pointer = json.loads((BASE / 'private/current_service.json').read_text())
    if not guard.matching(pointer):
        raise RuntimeError('API identity changed before pause')
    directory = BASE / 'private' / f'guard-fusion-v18-priority-{time.time_ns()}'
    (OUT / 'guard_experiment.json').write_text(json.dumps({'directory': str(directory)}))
    code = guard.guarded_run(guard.capture(pointer['pid']), directory,
                [str(PYTHON), str(Path(__file__).resolve()), 'supervise'],
                'http://10.176.30.103:20027/v1', BASE / 'private/api_key')
    restored = json.loads((directory / 'restored.json').read_text())
    (OUT / 'service_recovery_experiment.json').write_text(json.dumps(restored, indent=2)+'\n')
    if code:
        raise RuntimeError('Priority experiment stopped; API restored')
    with tarfile.open(BASE / 'setup/fusion_v18_experiment_results.tar.gz', 'w:gz') as archive:
        for path in sorted(OUT.rglob('*')):
            if path.is_file() and path.suffix not in ('.lock', '.inflight', '.pt', '.safetensors'):
                archive.add(path, arcname=path.relative_to(OUT).as_posix())
    print(json.dumps({'phase': 'experiment_priority', 'completed': True, 'api_restored': True}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['launch', 'guarded', 'supervise'])
    args = parser.parse_args()
    {'launch': launch, 'guarded': guarded, 'supervise': supervise}[args.action]()
