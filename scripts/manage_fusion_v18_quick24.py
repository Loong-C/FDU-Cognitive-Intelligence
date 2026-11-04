"""Two-card quick scheduler with a detached deadline and existing API recovery guard."""
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
OLD = BASE / 'fusion_v18_runs'
OUT = BASE / 'fusion_v18_quick24_runs'
PYTHON = BASE / 'venv/bin/python'
URL = 'http://10.176.30.103:20027/v1'
KEY = BASE / 'private/api_key'


def original():
    spec = importlib.util.spec_from_file_location('old_v18_manager', WORK / 'scripts/manage_fusion_v18.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def quick():
    sys.path.insert(0, str(WORK / 'src'))
    from ab_factcheck import fusion_v18_quick24 as q
    return q


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def read(path):
    return json.loads(path.read_text())


def stop_old():
    q = quick(); q.verify(); q.check_deadline()
    manager = original(); guard = manager.guard_module()
    pointer = read(OLD / 'controller.json')
    if pointer['phase'] != 'experiment_priority' or not guard.matching(pointer):
        raise RuntimeError('Expected live original priority controller')
    directory = Path(read(OLD / 'guard_experiment.json')['directory'])
    command = read(directory / 'command_process.json')
    if not guard.matching(command):
        raise RuntimeError('Old supervisor no longer live')
    argv = Path(f"/proc/{command['pid']}/cmdline").read_bytes()
    if b'manage_fusion_v18_priority.py' not in argv or b'supervise' not in argv:
        raise RuntimeError('Old supervisor identity mismatch')
    destination = OUT / 'transition' / str(time.time_ns())
    save(destination / 'request.json', {'reason': 'User explicitly authorized 24-hour reduced scope',
        'old_controller': pointer, 'old_supervisor': command, 'time_unix': time.time(),
        'original_runtime_unchanged': True, 'up_to_seven_updates_may_be_replayed': True})
    # Only the verified supervisor is signaled. Its existing guard restores the API.
    os.kill(command['pid'], signal.SIGTERM)
    print(json.dumps({'stop_requested': command, 'receipt': str(destination)}), flush=True)


def archive_replay():
    """Preserve step records which the frozen trainer would otherwise overwrite."""
    q = quick(); manager = original()
    if manager.alive(OLD / 'controller.json'):
        raise RuntimeError('Do not archive live training')
    from ab_factcheck.fusion_v18_training import recover_latest
    destination = OUT / 'training_replay' / str(time.time_ns())
    records = []
    for source in q.f.SOURCES:
        for seed in q.f.SEEDS:
            folder = OLD / 'training' / source / f'seed-{seed}'
            if (folder / 'training_complete.json').exists() or not (folder / 'identity.json').exists():
                continue
            latest = recover_latest(folder, read(folder / 'identity.json'))
            cursor = (latest['receipt']['epoch'], latest['receipt']['cursor']) if latest else (0, 0)
            for path in sorted((folder / 'steps').glob('*.json')):
                value = read(path)
                if (value['epoch'], value['cursor']) > cursor:
                    target = destination / source / f'seed-{seed}' / 'steps' / path.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    records.append({'source': source, 'seed': seed, 'file': str(path.relative_to(OLD)),
                                    'preserved': str(target.relative_to(OUT)), 'seconds': value['seconds'],
                                    'checkpoint_cursor': list(cursor), 'sha256': q.c.sha(path)})
                    path.rename(target)
            for path in folder.glob('checkpoint-*.incomplete'):
                if not path.resolve().is_relative_to(folder.resolve()):
                    raise ValueError('Unexpected partial checkpoint path')
                target = destination / source / f'seed-{seed}' / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                path.rename(target)
    save(destination / 'accounting.json', {'replayed_updates': records,
        'uncommitted_partial_update_cost_unknown': True, 'no_received_generation_overwritten': True})
    return records


def launch():
    q = quick(); m, _ = q.verify(); q.check_deadline()
    manager = original(); guard = manager.guard_module()
    if manager.alive(OLD / 'controller.json') or manager.alive(OUT / 'controller.json'):
        raise RuntimeError('Existing controller must finish recovery before quick launch')
    if (OUT / 'delivered.json').exists() or list(OUT.rglob('*.inflight')) or list(OLD.rglob('*.inflight')):
        raise RuntimeError('Completed quick run or unresolved interrupted calls')
    service = read(BASE / 'private/current_service.json')
    if not guard.matching(service): raise RuntimeError('API identity changed')
    guard.health(URL, KEY)
    replay = archive_replay()
    q.import_validation(OLD, OUT)
    save(OUT / 'launch_identity.json', {'schedule_sha256': q.c.sha(q.f.ROOT / q.MANIFEST),
        'deadline_unix': m['deadline_unix'], 'stop_compute_unix': m['stop_compute_unix'],
        'replayed_update_count': len(replay), 'devices': [2, 3]})
    with (OUT / 'controller.log').open('ab') as log:
        child = subprocess.Popen([str(PYTHON), str(Path(__file__).resolve()), 'guarded'],
            cwd=WORK, env=manager.env_for(), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    pointer = {'pid': child.pid, 'start_time': guard.proc_start(child.pid), 'phase': 'quick24'}
    save(OUT / 'controller.json', pointer)
    # Detached from both inference and guard sessions; survives chat/controller exit.
    with (OUT / 'deadline.log').open('ab') as log:
        watcher = subprocess.Popen([str(PYTHON), str(Path(__file__).resolve()), 'deadline'],
            cwd=WORK, env=manager.env_for(), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    watch = {'pid': watcher.pid, 'start_time': guard.proc_start(watcher.pid)}
    save(OUT / 'deadline_process.json', watch)
    print(json.dumps({'started': pointer, 'deadline_watcher': watch,
                      'stop_compute_unix': m['stop_compute_unix'], 'deadline_unix': m['deadline_unix']}), flush=True)


def next_job(training, validation, active):
    """Pure scheduling rule: training first, then ready validation on every free card."""
    busy = {name for name in active}
    for arm in training:
        if not training[arm] and ('train-' + arm) not in busy:
            return 'train-' + arm
    for arm in validation:
        if training[arm] and not validation[arm] and ('validate-' + arm) not in busy:
            return 'validate-' + arm
    return None


def spawn(label, device, argv):
    manager = original(); guard = manager.guard_module()
    command = 'source /usr/local/Ascend/ascend-toolkit/set_env.sh && exec ' + shlex.join([str(PYTHON), *argv])
    with (OUT / (label + '.log')).open('ab') as log:
        child = subprocess.Popen(['bash', '-c', command], cwd=WORK, env=manager.env_for(device),
                                 stdout=log, stderr=subprocess.STDOUT)
    receipt = {'pid': child.pid, 'start_time': guard.proc_start(child.pid), 'job': label, 'device': device}
    save(OUT / 'jobs' / (label + '.json'), receipt)
    print(json.dumps(receipt), flush=True)
    return child


def stop_children(children):
    for _, _, child in children:
        if child.poll() is None: child.terminate()
    for _, _, child in children:
        try: child.wait(timeout=20)
        except subprocess.TimeoutExpired: child.kill(); child.wait()


def train_and_validate():
    q = quick(); children = []
    try:
        while True:
            q.check_deadline()
            for _, label, child in children:
                if child.poll() not in (None, 0):
                    raise RuntimeError('Worker failed: ' + label + ' exit=' + str(child.returncode))
            children = [(d, label, child) for d, label, child in children if child.poll() is None]
            training = {}
            validation = {}
            for arm in q.NEW:
                _, source, seed = arm.split('_')
                training[arm] = (OLD / 'training' / source / f'seed-{seed}/training_complete.json').exists()
                validation[arm] = len(list((OUT / 'validation/direct' / arm).glob('*.json'))) == 259
            if all(training.values()) and all(validation.values()) and not children:
                return
            for device in (2, 3):
                if device in {d for d, _, _ in children}: continue
                label = next_job(training, validation, [name for _, name, _ in children])
                if label is None: continue
                arm = label.split('-', 1)[1]
                if label.startswith('train-'):
                    _, source, seed = arm.split('_')
                    argv = ['-m', 'ab_factcheck.fusion_v18_run', 'train', '--source', source,
                            '--seed', seed, '--output', str(OLD)]
                else:
                    q.snapshot_adapter(OLD, OUT, arm)
                    argv = ['-m', 'ab_factcheck.fusion_v18_quick24', 'worker', '--part', 'validation',
                            '--arm', arm, '--output', str(OUT), '--old-output', str(OLD)]
                children.append((device, label, spawn(label, device, argv)))
            time.sleep(3)
    finally:
        stop_children(children)


def evaluate():
    children = []
    try:
        for worker, device in enumerate((2, 3)):
            label = f'evaluate-{worker}'
            argv = ['-m', 'ab_factcheck.fusion_v18_quick24', 'worker', '--part', 'evaluation',
                    '--worker', str(worker), '--output', str(OUT), '--old-output', str(OLD)]
            children.append((device, label, spawn(label, device, argv)))
        while any(child.poll() is None for _, _, child in children):
            quick().check_deadline()
            for _, label, child in children:
                if child.poll() not in (None, 0): raise RuntimeError('Worker failed: ' + label)
            time.sleep(3)
        if any(child.returncode for _, _, child in children): raise RuntimeError('Evaluation failed')
    finally:
        stop_children(children)


def supervise():
    q = quick(); q.verify()
    def interrupted(signum, frame): raise KeyboardInterrupt('Quick supervisor interrupted')
    signal.signal(signal.SIGTERM, interrupted); signal.signal(signal.SIGINT, interrupted)
    manager = original()
    try:
        save(OUT / 'memory.json', {'passed': True, 'devices': manager.memory_preflight()})
        source = read(WORK / 'experiments/016_finetune_27b/model_source.json')
        for entry in source['files']:
            q.check_deadline()
            expected = entry.get('Sha256') or entry.get('sha256')
            if expected and q.c.sha(BASE / 'models/Qwen3.8-27B' / entry['Path']) != expected:
                raise ValueError('Original model bytes changed')
        save(OUT / 'model_verified.json', {'files': len(source['files']), 'passed': True})
        if not (OUT / 'smoke_receipt.json').exists():
            smoke = spawn('smoke-distill_nli_42', 2, ['-m', 'ab_factcheck.fusion_v18_quick24',
                'worker', '--part', 'validation', '--arm', 'distill_nli_42', '--smoke-count', '3',
                '--output', str(OUT), '--old-output', str(OLD)])
            try:
                while smoke.poll() is None:
                    q.check_deadline(); time.sleep(3)
                if smoke.returncode: raise RuntimeError('New-adapter physical smoke failed')
            finally:
                stop_children([(2, 'smoke-distill_nli_42', smoke)])
        train_and_validate()
        q.check_deadline(); q.report(OUT, 'validation')
        q.check_deadline(); evaluate()
        q.report(OUT, 'evaluation')
        save(OUT / 'inference_complete.json', {'complete': True,
             'evaluation_results_sha256': q.c.sha(OUT / 'evaluation/results.json')})
    except BaseException as error:
        save(OUT / 'worker_failure.json', {'error_type': type(error).__name__, 'message': str(error),
                                         'time_unix': time.time()})
        raise


def archive_unanswered():
    q = quick(); destination = OUT / 'interruptions' / str(time.time_ns())
    records = []
    for path in list(OUT.rglob('*.inflight')):
        relative = path.relative_to(OUT)
        received = path.with_suffix('.json').exists()
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        records.append({'path': relative.as_posix(), 'received_answer_preserved': received,
                        'unanswered_cost_unknown': not received, 'attempt_sha256': q.c.sha(path)})
        path.rename(target.with_suffix('.interrupted.json'))
    if records: save(destination / 'accounting.json', records)


def historical_costs():
    q = quick(); physical = {}; steps = []; replay = []; unknown = 0; smoke_inference = []
    for section in ('teachers', 'smoke'):
        for path in (OLD / section).rglob('*.json'):
            value = read(path)
            if isinstance(value, dict) and 'physical_call' in value:
                physical[(value['identity']['phase'], value['physical_call'])] = value
    for path in (OLD / 'training').glob('*/seed-*/steps/*.json'): steps.append(read(path))
    for path in (OLD / 'training').glob('*/smoke/receipt.json'):
        value = read(path)
        if 'inference_cost' in value: smoke_inference.append(value['inference_cost'])
    for path in (OUT / 'training_replay').glob('*/accounting.json'): replay.extend(read(path)['replayed_updates'])
    for root in (OLD / 'interruptions', OUT / 'interruptions'):
        for path in root.rglob('accounting.json'):
            value = read(path)
            if isinstance(value, list): unknown += sum(v.get('unanswered_cost_unknown', False) for v in value)
    return {'historical_teacher_and_smoke_calls': len(physical),
            'historical_teacher_and_smoke_seconds': sum(v['seconds'] for v in physical.values()),
            'training_updates': len(steps), 'training_step_seconds': sum(v['seconds'] for v in steps),
            'training_smoke_inference': smoke_inference,
            'preserved_replayed_updates': len(replay), 'replayed_step_seconds': sum(v['seconds'] for v in replay),
            'unanswered_attempts_unknown_cost': unknown,
            'uncommitted_training_partial_update_cost_unknown': bool(replay),
            'source_run': str(OLD), 'note': 'Training and teacher costs are separate from quick inference. Original already completed validation calls are counted once as imports.'}


def publish():
    import fcntl
    q = quick()
    with (OUT / 'finalize.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (OUT / 'delivered.json').exists(): return
        directory = Path(read(OUT / 'guard.json')['directory'])
        restored = read(directory / 'restored.json')
        if not restored.get('restored') or not restored.get('generation_checked'):
            raise RuntimeError('API restoration not verified')
        guard = original().guard_module()
        if ((directory / 'command_process.json').exists()
                and guard.command_members(read(directory / 'command_process.json'))):
            raise RuntimeError('Cannot publish while owned computation is still live')
        save(OUT / 'service_recovery.json', restored)
        archive_unanswered()
        status = 'complete' if (OUT / 'inference_complete.json').exists() else (
            'deadline_partial' if (OUT / 'deadline_triggered.json').exists() else 'failed_partial')
        q.finish(OUT, status)
        save(OUT / 'historical_costs.json', historical_costs())
        with tarfile.open(BASE / 'setup/fusion_v18_quick24_results.tar.gz', 'w:gz') as archive:
            for path in sorted(OUT.rglob('*')):
                if path.is_file() and path.suffix not in ('.lock', '.log', '.pt', '.safetensors', '.inflight'):
                    archive.add(path, arcname=path.relative_to(OUT).as_posix(), recursive=False)
        save(OUT / 'delivered.json', {'status': status, 'api_restored': True,
             'archive': str(BASE / 'setup/fusion_v18_quick24_results.tar.gz'), 'time_unix': time.time(),
             'before_deadline': time.time() <= q.verify()[0]['deadline_unix']})


def guarded():
    manager = original(); guard = manager.guard_module()
    ready_until = time.time() + 30
    while time.time() < ready_until:
        if (OUT / 'deadline_ready.json').exists() and (OUT / 'deadline_process.json').exists():
            watch = read(OUT / 'deadline_process.json')
            if read(OUT / 'deadline_ready.json')['pid'] == watch['pid'] and guard.matching(watch): break
        time.sleep(.2)
    else:
        raise RuntimeError('Independent deadline must be armed before API pause')
    pointer = read(BASE / 'private/current_service.json')
    directory = BASE / 'private' / f'guard-fusion-v18-quick24-{time.time_ns()}'
    save(OUT / 'guard.json', {'directory': str(directory)})
    try:
        guard.guarded_run(guard.capture(pointer['pid']), directory,
                         [str(PYTHON), str(Path(__file__).resolve()), 'supervise'], URL, KEY)
    finally:
        # guarded_run restores and checks the service before reaching here.
        if (directory / 'restored.json').exists(): publish()


def deadline():
    q = quick(); manifest, _ = q.verify(); guard = original().guard_module()
    save(OUT / 'deadline_ready.json', {'independent': True, 'pid': os.getpid(),
        'stop_compute_unix': manifest['stop_compute_unix'], 'deadline_unix': manifest['deadline_unix']})
    while not (OUT / 'delivered.json').exists():
        pointer = read(OUT / 'controller.json')
        if time.time() >= manifest['stop_compute_unix']:
            if not (OUT / 'deadline_triggered.json').exists():
                save(OUT / 'deadline_triggered.json', {'time_unix': time.time(), 'controller': pointer})
                if guard.matching(pointer): os.kill(pointer['pid'], signal.SIGTERM)
            break
        if not guard.matching(pointer): break
        time.sleep(min(10, max(0.01, manifest['stop_compute_unix'] - time.time())))
    while not (OUT / 'delivered.json').exists():
        if (OUT / 'guard.json').exists():
            directory = Path(read(OUT / 'guard.json')['directory'])
            if (directory / 'restored.json').exists():
                publish(); return
            pointer = read(OUT / 'controller.json')
            if not guard.matching(pointer) and (directory / 'snapshot.private.json').exists():
                # Existing watchdog and this fallback serialize on restore.lock.
                guard.stop_command(directory)
                guard.restore(read(directory / 'snapshot.private.json'), directory, URL, KEY)
                publish(); return
        time.sleep(5)


def status():
    manager = original(); guard = manager.guard_module()
    result = {'observed_unix': time.time(), 'running': manager.alive(OUT / 'controller.json')}
    for name in ('controller', 'launch_identity', 'deadline_process', 'deadline_ready', 'memory',
                 'worker_failure', 'smoke_receipt', 'quick_recommendation', 'deadline_triggered', 'service_recovery', 'delivered'):
        path = OUT / (name + '.json')
        result[name] = read(path) if path.exists() else None
    result['deadline_alive'] = bool(result['deadline_process'] and guard.matching(result['deadline_process']))
    result['active_jobs'] = [r for p in (OUT / 'jobs').glob('*.json') if guard.matching(r := read(p))]
    q = quick()
    result['coverage'] = q.coverage(OUT)
    result['training'] = {}
    for arm in q.NEW:
        _, source, seed = arm.split('_'); folder = OLD / 'training' / source / f'seed-{seed}'
        steps = list((folder / 'steps').glob('*.json'))
        result['training'][arm] = {'complete': (folder / 'training_complete.json').exists(), 'steps': len(steps),
                                  'latest_unix': max((p.stat().st_mtime for p in steps), default=None)}
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['stop-old', 'launch', 'guarded', 'supervise', 'deadline', 'status', 'publish'])
    args = parser.parse_args()
    {'stop-old': stop_old, 'launch': launch, 'guarded': guarded, 'supervise': supervise,
     'deadline': deadline, 'status': status, 'publish': publish}[args.action]()
