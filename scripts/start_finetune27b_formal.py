"""Remote launch/resume after the reviewed training freeze and draft recovery."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

base=Path('/root/ab_finetune27b_20261030')
workspace=base/'revision_2_formal_workspace'
sys.path.insert(0,str(workspace/'src'))
from ab_factcheck import finetune27b_v2 as c
c.verify_training()
recovered=json.loads((base/'private/guard-parallel-drafts/restored.json').read_text())
if not recovered.get('restored') or not recovered.get('generation_checked'):
    raise RuntimeError('Drafting service recovery has not passed')
spec=importlib.util.spec_from_file_location('guard',base/'setup/finetune27b_service_guard.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
pointer=base/'private/formal_controller.json'
if pointer.exists() and guard.matching(json.loads(pointer.read_text())):
    raise RuntimeError('Formal controller is already running')
env=dict(os.environ,PYTHONUNBUFFERED='1')
with (base/'logs/revision_2_formal_controller.log').open('ab') as log:
    process=subprocess.Popen(['/root/ascend/bin/python',str(base/'setup/continue_finetune27b_v2.py')],
        cwd=workspace,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
value={'pid':process.pid,'start_time':guard.proc_start(process.pid)}
pointer.write_text(json.dumps(value))
print(json.dumps({'started_formal_controller':value,'log':'logs/revision_2_formal_controller.log'}))
