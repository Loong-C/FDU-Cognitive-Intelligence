"""Explicitly approved API downtime recovery; inspect is read-only to services.

Never call launch until the user approves pausing the shared Qwen HTTP API.
Frozen inference code, prompts, records and scoring are not modified.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

BASE=Path('/root/ab_finetune27b_20261030')
WORK=BASE/'unified_v17_workspace'
OUT=BASE/'unified_v17_runs'
PYTHON=BASE/'venv/bin/python'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def inspect():
    guard=module('recovery_guard',BASE/'setup/finetune27b_service_guard.py')
    service=json.loads((BASE/'private/current_service.json').read_text())
    assert guard.matching(service),'Saved service identity no longer matches'
    snapshot=guard.capture(service['pid'])
    guard.health('http://10.176.30.103:20027/v1',BASE/'private/api_key')
    state={'service_pid':snapshot['pid'],'service_start_time':snapshot['start_time'],'service_matches':True,
           'health_passed':True,'worker_devices':{'0':2,'1':3},'requires_explicit_user_approval':True}
    (OUT/'resource_recovery_preflight.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state));return state


def supervise():
    # The guard runs this supervisor and all its workers in ONE process group.
    # Its independent watchdog can therefore remove orphan workers before restore.
    manager=module('original_manager',BASE/'setup/manage_unified_v17.py')
    sys.path.insert(0,str(WORK/'src'))
    from ab_factcheck import unified_v17 as u
    from ab_factcheck import finetune27b_v2 as c
    u.verify()
    # Wait for the stopped API's workers to release HBM before loading two BF16 copies.
    memory=None
    for attempt in range(20):
        output=subprocess.check_output(['bash','-c',
            'export LD_LIBRARY_PATH=/usr/local/Ascend/driver/lib64/common:/usr/local/Ascend/driver/lib64/driver:$LD_LIBRARY_PATH; npu-smi info'],text=True)
        memory={};current=None
        for line in output.splitlines():
            match=re.match(r'^\|\s*(\d+)\s+910B3\b',line)
            if match:current=int(match[1])
            values=re.search(r'(\d+)\s*/\s*(\d+)\s*\|\s*$',line)
            if current is not None and values:
                used,total=map(int,values.groups());memory[current]={'used_mib':used,'total_mib':total}
        if all(d in memory and memory[d]['total_mib']-memory[d]['used_mib']>=58000 for d in (2,3)):break
        time.sleep(3)
    else:raise RuntimeError('Insufficient free HBM after stopping API; restore service')
    c.save(OUT/'resource_memory_preflight.json',{'passed':True,'devices':{str(d):memory[d] for d in (2,3)}})
    children=[]
    def interrupted(signum,frame):raise KeyboardInterrupt('Resource recovery interrupted')
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    try:
        for worker,device in ((0,2),(1,3)):
            command=('source /usr/local/Ascend/ascend-toolkit/set_env.sh && '
                f'exec {PYTHON} -m ab_factcheck.unified_v17 run --worker {worker} --output {OUT}')
            with (OUT/f'worker-{worker}.log').open('ab') as log:
                child=subprocess.Popen(['bash','-c',command],cwd=WORK,env=manager.env_for(device),
                    stdout=log,stderr=subprocess.STDOUT)
            children.append(child)
            print(json.dumps({'worker':worker,'actual_device':device,'pid':child.pid}),flush=True)
        while any(c.poll() is None for c in children):
            if any(c.poll() not in (None,0) for c in children):raise RuntimeError('Recovery worker failed')
            time.sleep(5)
        if any(c.returncode for c in children):raise RuntimeError('Recovery worker failed')
        u.report(OUT)
        subprocess.run([str(PYTHON),str(WORK/'scripts/audit_unified_v17.py'),str(OUT)],cwd=WORK,env=manager.env_for(),check=True)
    finally:
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        for child in children:
            if child.poll() is None:child.terminate()
        for child in children:
            try:child.wait(timeout=20)
            except subprocess.TimeoutExpired:child.kill();child.wait()


def guarded():
    import tarfile
    guard=module('recovery_guard',BASE/'setup/finetune27b_service_guard.py')
    state=json.loads((OUT/'resource_recovery_preflight.json').read_text())
    snapshot=guard.capture(state['service_pid'])
    assert snapshot['start_time']==state['service_start_time']
    directory=BASE/f'private/guard-unified-v17-{time.time_ns()}'
    (OUT/'resource_recovery_guard.json').write_text(json.dumps({'directory':str(directory)}))
    code=guard.guarded_run(snapshot,directory,[str(PYTHON),__file__,'supervise'],
                           'http://10.176.30.103:20027/v1',BASE/'private/api_key')
    restored=json.loads((directory/'restored.json').read_text())
    (OUT/'resource_service_recovery.json').write_text(json.dumps(restored,indent=2)+'\n')
    if code:raise RuntimeError('Evaluation stopped; API restoration attempted')
    with tarfile.open(BASE/'setup/unified_v17_results.tar.gz','w:gz') as tar:
        for f in sorted(OUT.rglob('*')):
            if f.is_file() and f.suffix not in ('.lock','.inflight'):tar.add(f,arcname=f.relative_to(OUT).as_posix())


def launch(approval):
    if approval!='user-approved-api-pause':raise ValueError('Explicit API downtime approval required')
    manager=module('original_manager',BASE/'setup/manage_unified_v17.py')
    guard=module('recovery_guard',BASE/'setup/finetune27b_service_guard.py')
    pointer=OUT/'controller.json'
    assert not manager.alive(json.loads(pointer.read_text())),'Controller already active'
    inspect()
    # Account for the received OOM as INVALID. Only unresolved peer attempts are archived.
    sys.path.insert(0,str(WORK/'src'))
    from ab_factcheck import finetune27b_v2 as c
    from ab_factcheck import unified_v17 as u
    u.verify()
    archive=OUT/'interruptions'/f'resource_recovery_{time.time_ns()}'
    archive.mkdir(parents=True)
    received={f.relative_to(OUT).as_posix():c.sha(f) for f in (OUT/'records').rglob('*.json')}
    inflight=sorted((OUT/'records').rglob('*.inflight'))
    receipt={'kind':'resource_oom','reason':'OOM stopped original worker; user approved pausing API and remapping workers to cards 2/3. Keep received failure as INVALID; do not regenerate it.',
        'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'received_hashes':received,
        'received_cells_preserved':len(received),'worker_devices':{'0':2,'1':3},'compute_unchanged':True,
        'interrupted_without_response':[{'path':f.relative_to(OUT).as_posix(),'sha256':c.sha(f)} for f in inflight]}
    c.save(archive/'resumption.json',receipt)
    for f in inflight:
        assert not f.with_suffix('.json').exists()
        target=archive/f.relative_to(OUT);target.parent.mkdir(parents=True,exist_ok=True);f.rename(target)
    with (OUT/'resource_recovery_controller.log').open('ab') as log:
        process=subprocess.Popen([str(PYTHON),__file__,'guarded'],cwd=WORK,env=manager.env_for(),
            stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    pointer.write_text(json.dumps({'pid':process.pid,'start_time':guard.proc_start(process.pid)}))
    print(json.dumps({'started':process.pid,'devices':[2,3],'api_restore_guard':True}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['inspect','launch','guarded','supervise'])
    parser.add_argument('--approval',default='')
    args=parser.parse_args()
    if args.action=='launch':launch(args.approval)
    else:{'inspect':inspect,'guarded':guarded,'supervise':supervise}[args.action]()
