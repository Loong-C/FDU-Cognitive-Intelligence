"""Remote bounded five-worker draft job, run inside the service recovery guard."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

base = Path('/root/ab_finetune27b_20261030')
devices = (0, 2, 3, 4, 5)
processes = []


def interrupted(signum, frame):
    raise KeyboardInterrupt('Draft supervisor interrupted')


signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)
try:
    for index, device in enumerate(devices):
        env = dict(os.environ, ASCEND_RT_VISIBLE_DEVICES=str(device), PYTHONUNBUFFERED='1',
                   PYTHONPATH=str(base/'revision_2_workspace/src'))
        cmd = ('source /usr/local/Ascend/ascend-toolkit/set_env.sh && '
               'exec /root/ab_finetune27b_20261030/venv/bin/python -m ab_factcheck.finetune27b_run_v2 draft '
               '--model /root/ab_finetune27b_20261030/models/Qwen3.8-27B '
               '--output /root/ab_finetune27b_20261030/revision_2_runs/rationale_drafts '
               f'--shard-count {len(devices)} --shard-index {index}')
        with (base/f'logs/revision_2_drafts_{index}.log').open('a') as log:
            process = subprocess.Popen(['bash', '-c', cmd], cwd=base/'revision_2_workspace', env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
        print(json.dumps({'worker': index, 'device': device, 'pid': process.pid}), flush=True)
        # Spread 55GB checkpoint loads to avoid simultaneous storage pressure.
        time.sleep(3)
    while any(p.poll() is None for p in processes):
        failed = [p.returncode for p in processes if p.poll() not in (None, 0)]
        if failed:
            raise RuntimeError('Draft worker failed: ' + str(failed))
        time.sleep(5)
    if any(p.returncode != 0 for p in processes):
        raise RuntimeError('Draft worker failed')
    print(json.dumps({'drafts_completed': True}), flush=True)
finally:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
