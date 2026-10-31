"""Remote training/selection supervisor; invoke inside the service lifecycle guard.

Every seed stays on one 910B3. Validation baseline is generated once on device 0.
The frozen training world size must be one; FULL_SHARD requires its separate acceptance.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

BASE = Path('/root/ab_finetune27b_20261030')


def spawn(action, device, seed=42):
    env = dict(os.environ, ASCEND_RT_VISIBLE_DEVICES=str(device), PYTHONUNBUFFERED='1',
               PYTHONPATH=str(BASE/'revision_2_formal_workspace/src'))
    command = ('source /usr/local/Ascend/ascend-toolkit/set_env.sh && '
        'exec /root/ab_finetune27b_20261030/venv/bin/python -m ab_factcheck.finetune27b_run_v2 '
        f'{action} --seed {seed} --model /root/ab_finetune27b_20261030/models/Qwen3.8-27B '
        '--output /root/ab_finetune27b_20261030/revision_2_runs/formal')
    with (BASE/f'logs/revision_2_{action}_{seed}.log').open('ab') as log:
        child = subprocess.Popen(['bash','-c',command], cwd=BASE/'revision_2_formal_workspace', env=env,
                                 stdout=log, stderr=subprocess.STDOUT)
    print(json.dumps({'action':action,'seed':seed,'device':device,'pid':child.pid}),flush=True)
    return child


def wait_all(children):
    while any(child.poll() is None for child in children):
        if any(child.poll() not in (None,0) for child in children):
            raise RuntimeError('A pipeline stage failed; inspect its immutable receipts and log')
        time.sleep(5)
    if any(child.returncode != 0 for child in children):
        raise RuntimeError('A pipeline stage failed')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['smoke','train-select','evaluate'])
    args=parser.parse_args()
    children=[]
    def interrupted(signum,frame):
        raise KeyboardInterrupt('Pipeline interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGINT,interrupted)
    try:
        if args.phase == 'train-select':
            children=[spawn('validate-baseline',0)]
            for seed,device in ((42,2),(43,3),(44,4)):
                children.append(spawn('train',device,seed))
                time.sleep(3)
            wait_all(children)
            children=[spawn('select',device,seed) for seed,device in ((42,2),(43,3),(44,4))]
            wait_all(children)
        else:
            children=[spawn(args.phase,0)]
            wait_all(children)
        print(json.dumps({'phase':args.phase,'completed':True}),flush=True)
    finally:
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait()


if __name__ == '__main__':
    main()
