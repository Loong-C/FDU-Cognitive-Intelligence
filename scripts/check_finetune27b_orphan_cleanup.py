"""Remote disposable process check; never stops a serving/model process."""
import importlib.util
import json
from pathlib import Path
import subprocess
import time

base=Path('/root/ab_finetune27b_20261030')
source=base/'setup/guard_v2_candidate.py'
spec=importlib.util.spec_from_file_location('candidate_guard',source)
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
directory=base/f'private/orphan-cleanup-check-{time.time_ns()}'
directory.mkdir(mode=0o700)
program='import subprocess,time; p=subprocess.Popen(["/usr/bin/sleep","60"]); print(p.pid,flush=True); time.sleep(0.3)'
leader=subprocess.Popen(['/usr/bin/python3','-c',program],stdout=subprocess.PIPE,text=True,start_new_session=True)
snapshot={'pid':leader.pid,'start_time':guard.proc_start(leader.pid)}
(directory/'command_process.json').write_text(json.dumps(snapshot))
worker=int(leader.stdout.readline())
leader.wait(timeout=5)
try:
    before=guard.command_members(snapshot)
    if worker not in before:
        raise RuntimeError('Disposable child did not outlive its supervisor')
    guard.stop_command(directory)
    if guard.command_members(snapshot):
        raise RuntimeError('Disposable session still has live processes')
    receipt={'passed':True,'supervisor_exited_before_cleanup':True,'orphan_removed':True,
             'serving_processes_touched':False}
    (base/'revision_2_runs/orphan_cleanup.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt))
finally:
    guard.stop_command(directory)
