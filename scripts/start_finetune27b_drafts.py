"""Launch the already-deployed revision-2 baseline draft job on device zero."""
import json
import os
from pathlib import Path
import subprocess

base = Path('/root/ab_finetune27b_20261030')
pidfile = base / 'revision_2_drafts.pid'
if pidfile.exists() and Path('/proc', pidfile.read_text().strip()).exists():
    raise RuntimeError('Draft job already running')
env = dict(os.environ, ASCEND_RT_VISIBLE_DEVICES='0', PYTHONUNBUFFERED='1',
           PYTHONPATH=str(base / 'revision_2_workspace/src'))
cmd = ('source /usr/local/Ascend/ascend-toolkit/set_env.sh && '
       'exec /root/ab_finetune27b_20261030/venv/bin/python -m ab_factcheck.finetune27b_run_v2 draft '
       '--model /root/ab_finetune27b_20261030/models/Qwen3.8-27B '
       '--output /root/ab_finetune27b_20261030/revision_2_runs/rationale_drafts')
with (base / 'logs/revision_2_drafts.log').open('a') as log:
    process = subprocess.Popen(['bash', '-c', cmd], cwd=base/'revision_2_workspace', env=env,
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
pidfile.write_text(str(process.pid))
print(json.dumps({'pid': process.pid, 'phase': 'training_rationale_drafts', 'n': 902}))
