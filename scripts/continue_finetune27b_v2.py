"""Remote foreground controller; launch under nohup only after all review files are frozen.

Stages are restartable by their immutable identities. Existing service is restored
before the one-handle, sequential, four-arm holdout evaluation on device zero.
"""
import json
from pathlib import Path
import subprocess
import sys
import time

base=Path('/root/ab_finetune27b_20261030')
sys.path.insert(0,str(base/'revision_2_formal_workspace/src'))
from ab_factcheck import finetune27b_v2 as c

p=c.verify_training()
if p['training']['world_size'] != 1:
    raise RuntimeError('This independent-seed launcher requires the frozen single-device topology')
out=base/'revision_2_runs/formal'
controller=['/root/ascend/bin/python',str(base/'setup/finetune27b_pipeline_v2.py')]
if not (out/'smoke/receipt.json').exists():
    subprocess.run(controller+['smoke'],check=True)
if not all((out/f'seed-{seed}/selection.json').exists() for seed in c.SEEDS):
    previous=base/'private/guard-parallel-drafts'
    restored=json.loads((previous/'restored.json').read_text())
    if not restored['restored'] or not restored['generation_checked']:
        raise RuntimeError('Draft service recovery must pass before the next pause')
    current=base/'private/current_service.json'
    service=json.loads((current if current.exists() else previous/'restored_process.json').read_text())
    from importlib.util import spec_from_file_location, module_from_spec
    guard=base/'setup/finetune27b_service_guard.py'
    spec=spec_from_file_location('service_guard',guard)
    module=module_from_spec(spec);spec.loader.exec_module(module)
    if not module.matching(service):
        raise RuntimeError('Saved service PID/start time changed; inspect before stopping anything')
    subprocess.run(['/root/ascend/bin/python',str(guard),'pause-and-run',
        '--pid',str(service['pid']),'--directory',str(base/f'private/guard-formal-{time.time_ns()}'),
        '--key-file',str(base/'private/api_key'),'--',*controller,'train-select'],check=True)
subprocess.run(controller+['evaluate'],check=True)
subprocess.run(['/root/ascend/bin/python',str(base/'revision_2_formal_workspace/scripts/audit_finetune27b_v2.py'),
                str(out)],check=True)
print(json.dumps({'formal_pipeline_complete':True}),flush=True)
