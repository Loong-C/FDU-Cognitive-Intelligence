"""Read-only remote experiment progress; run through remote_finetune.py python.

This observer is not part of the frozen inference/training runtime.
It reads only V18 run artifacts and this experiment's process identities.
"""
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import time

BASE = Path('/root/ab_finetune27b_20261030')
OUT = BASE / 'fusion_v18_runs'


def read(path):
    return json.loads(path.read_text())


def progress(folder, pattern, expected):
    paths = list(folder.glob(pattern))
    recent = sorted(paths, key=lambda p: p.stat().st_mtime)[-40:]
    records = [read(p) for p in recent]
    seconds = [r['seconds'] for r in records if 'seconds' in r]
    return {'completed': len(paths), 'expected': expected,
            'latest_unix': max((p.stat().st_mtime for p in paths), default=None),
            'recent_n': len(records), 'recent_mean_seconds': statistics.mean(seconds) if seconds else None,
            'recent_invalid': sum(r.get('prediction') == 'INVALID' for r in records)}


def main():
    quick = BASE / 'fusion_v18_quick24_runs/controller.json'
    if quick.exists():
        # The reduced scope was explicitly authorized; do not restart the old full schedule.
        subprocess.run([str(BASE / 'venv/bin/python'),
                        str(BASE / 'fusion_v18_workspace/scripts/manage_fusion_v18_quick24.py'),
                        'status'], check=True)
        return
    spec = importlib.util.spec_from_file_location('guard', BASE / 'fusion_v18_workspace/scripts/finetune27b_service_guard.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    controller = read(OUT / 'controller.json')
    result = {'observed_unix': time.time(), 'controller': controller, 'running': guard.matching(controller),
              'memory': read(OUT / 'memory_experiment.json') if (OUT / 'memory_experiment.json').exists() else None,
              'model_bytes_verified': (OUT / 'model_verified_experiment.json').exists(),
              'experiment_complete': (OUT / 'experiment_complete.json').exists(),
              'recommendation_frozen': (OUT / 'recommendation.json').exists(),
              'worker_failure': read(OUT / 'worker_failure.json') if (OUT / 'worker_failure.json').exists() else None,
              'api_recovery': read(OUT / 'service_recovery_experiment.json') if (OUT / 'service_recovery_experiment.json').exists() else None}
    result['baseline_validation'] = progress(OUT / 'validation/direct/base_a0', '*.json', 259)
    result['checkpoint_validation'] = progress(OUT / 'checkpoint_validation', '*/*/*/*.json', 6993)
    for part, n in (('validation', 259), ('evaluation', 261)):
        result[part] = {kind: progress(OUT / part / kind, '*/*.json', count*n)
                        for kind, count in (('direct', 25), ('fusion', 37))}
        result[part]['audit_passed'] = read(OUT / part / 'audit.json').get('passed') if (OUT / part / 'audit.json').exists() else None
    result['training'] = {}
    for source in ('nli', 'pj', 'joint'):
        folder = OUT / 'training' / source
        smoke = folder / 'smoke/receipt.json'
        entry = {'smoke_passed': read(smoke).get('passed') if smoke.exists() else False}
        for seed in (42, 43, 44):
            run = folder / f'seed-{seed}'
            entry[str(seed)] = {'complete': (run / 'training_complete.json').exists(),
                                'selected': (run / 'selection.json').exists(),
                                'steps': progress(run / 'steps', '*.json', 138)}
        result['training'][source] = entry
    stage_order = ('seed42', 'three_seeds', 'direct_all', 'fusion_all')
    result['priority'] = {'stages': {stage: {
        'complete': (OUT / 'priority' / stage / 'audit.json').exists(),
        'report': str(OUT / 'priority' / stage / 'RESULTS.md')}
        for stage in stage_order},
        'first_stage_calls': {arm: progress(OUT / 'validation/direct' / arm, '*.json', 259)
            for arm in ('base_a0', 'old_a0_42', 'old_np_42')}}
    if (OUT / 'memory_priority.json').exists():
        result['memory_priority'] = read(OUT / 'memory_priority.json')
    log = OUT / ('priority_controller.log' if controller.get('phase') == 'experiment_priority' else 'experiment_controller.log')
    result['controller_log_tail'] = log.read_text(errors='replace').splitlines()[-12:] if log.exists() else []
    result['inflight_calls'] = len(list(OUT.rglob('*.inflight')))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
