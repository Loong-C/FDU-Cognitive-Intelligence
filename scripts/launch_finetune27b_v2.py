"""Run via SSH Python transport; starts the isolated full-model diagnostic."""
import json
import os
from pathlib import Path
import subprocess
import tarfile

base = Path('/root/ab_finetune27b_20261030')
workspace = base / 'revision_2_workspace'
workspace.mkdir(exist_ok=True)
with tarfile.open(base / 'setup/finetune27b_v2.tar.gz') as tar:
    for member in tar.getmembers():
        if not (workspace / member.name).resolve().is_relative_to(workspace.resolve()):
            raise ValueError('Archive escaped workspace')
        if Path(member.name).name == 'test.jsonl':
            raise ValueError('Original test in revision-2 package')
    tar.extractall(workspace, filter='data')
pidfile = base / 'revision_2_probe.pid'
if pidfile.exists() and Path('/proc', pidfile.read_text().strip()).exists():
    raise RuntimeError('Revision-2 probe already running')
env = dict(os.environ)
env['ASCEND_RT_VISIBLE_DEVICES'] = '0'
env['PYTHONPATH'] = str(workspace / 'src')
env['PYTHONUNBUFFERED'] = '1'
command = ('source /usr/local/Ascend/ascend-toolkit/set_env.sh && '
           'exec /root/ab_finetune27b_20261030/venv/bin/python -m ab_factcheck.finetune27b_run_v2 probe '
           '--model /root/ab_finetune27b_20261030/models/Qwen3.8-27B '
           '--output /root/ab_finetune27b_20261030/revision_2_runs/probe')
with (base / 'logs/revision_2_probe.log').open('a') as log:
    process = subprocess.Popen(['bash', '-c', command], cwd=workspace, env=env,
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
pidfile.write_text(str(process.pid))
print(json.dumps({'pid': process.pid, 'phase': 'full_27b_probe', 'device': 0}))
