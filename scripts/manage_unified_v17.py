"""Remote deployment/controller/status for the frozen six-arm comparison."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import time

BASE = Path('/root/ab_finetune27b_20261030')
WORK = BASE/'unified_v17_workspace'
OUT = BASE/'unified_v17_runs'
PYTHON = BASE/'venv/bin/python'


def alive(value):
    try:
        fields = Path('/proc',str(value['pid']),'stat').read_text().rsplit(')',1)[1].split()
        return fields[0] != 'Z' and fields[19] == str(value['start_time'])
    except FileNotFoundError:
        return False


def env_for(device=None):
    smoke = json.loads((BASE/'revision_2_runs/formal/smoke/receipt.json').read_text())['environment']
    env = dict(os.environ, PYTHONPATH=str(WORK/'src'), PYTHONUNBUFFERED='1')
    for key,value in smoke['compute_environment'].items():
        if value is None:
            env.pop(key,None)
        else:
            env[key] = value
    if device is not None:
        env['ASCEND_RT_VISIBLE_DEVICES'] = str(device)
    return env


def launch():
    WORK.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)
    pointer = OUT/'controller.json'
    if pointer.exists() and alive(json.loads(pointer.read_text())):
        raise ValueError('Controller already active')
    if (OUT/'audit.json').exists():
        raise ValueError('Completed experiment already exists')
    with tarfile.open(BASE/'setup/unified_v17.tar.gz') as tar:
        for member in tar.getmembers():
            if not (WORK/member.name).resolve().is_relative_to(WORK.resolve()):
                raise ValueError('Archive path escape')
            if member.name.endswith('/test.jsonl') or '/data/raw/' in member.name:
                raise ValueError('Original test/raw data cannot be deployed')
        tar.extractall(WORK,filter='data')
    with (OUT/'controller.log').open('ab') as log:
        process = subprocess.Popen([str(PYTHON),__file__,'controller'],cwd=WORK,
            env=env_for(),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    start = Path('/proc',str(process.pid),'stat').read_text().rsplit(')',1)[1].split()[19]
    value = {'pid':process.pid,'start_time':start}
    pointer.write_text(json.dumps(value))
    print(json.dumps({'started':value,'output':str(OUT)}))


def controller():
    children = []
    def interrupted(signum,frame):
        raise KeyboardInterrupt('Comparison controller interrupted')
    signal.signal(signal.SIGTERM,interrupted); signal.signal(signal.SIGINT,interrupted)
    try:
        sys.path.insert(0,str(WORK/'src'))
        from ab_factcheck import unified_v17 as u
        from ab_factcheck import finetune27b_v2 as core
        p = u.verify()
        train = core.read_json(WORK/u.OLD/'training_protocol.json')
        manifest = core.read_json(WORK/train['model_manifest'])
        model = BASE/'models/Qwen3.8-27B'
        receipt = core.read_json(model/'verified_download.json')
        if receipt['files'] != manifest['files'] or not receipt['all_verified']:
            raise ValueError('Model manifest differs')
        # Fresh full-byte weight verification before either worker starts.
        checked = []
        for f in manifest['files']:
            path = model/f['Path']
            expected = f.get('SHA256') or f.get('Sha256') or f.get('sha256')
            if expected is None:
                raise ValueError('Model manifest lacks SHA256')
            if path.stat().st_size != f['Size'] or core.sha(path) != expected:
                raise ValueError('Original model file mismatch: '+f['Path'])
            checked.append(f['Path'])
        core.save(OUT/'model_verification.json',{'passed':True,'files':checked,
            'model_manifest_sha256':core.sha(WORK/train['model_manifest'])})
        for worker,device in enumerate(p['devices']):
            command = ('source /usr/local/Ascend/ascend-toolkit/set_env.sh && '
                f'exec {PYTHON} -m ab_factcheck.unified_v17 run --worker {worker} --output {OUT}')
            with (OUT/f'worker-{worker}.log').open('ab') as log:
                child = subprocess.Popen(['bash','-c',command],cwd=WORK,env=env_for(device),
                    stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            children.append(child)
            print(json.dumps({'worker':worker,'device':device,'pid':child.pid}),flush=True)
        while any(c.poll() is None for c in children):
            if any(c.poll() not in (None,0) for c in children):
                raise RuntimeError('A worker failed; received outputs are preserved')
            time.sleep(5)
        if any(c.returncode != 0 for c in children):
            raise RuntimeError('A worker failed')
        u.report(OUT)
        subprocess.run([str(PYTHON),str(WORK/'scripts/audit_unified_v17.py'),str(OUT)],check=True,env=env_for(),cwd=WORK)
        with tarfile.open(BASE/'setup/unified_v17_results.tar.gz','w:gz') as tar:
            for f in sorted(OUT.rglob('*')):
                if f.is_file() and f.suffix not in ('.lock','.inflight'):
                    tar.add(f,arcname=f.relative_to(OUT).as_posix())
        print(json.dumps({'complete':True,'archive':str(BASE/'setup/unified_v17_results.tar.gz')}),flush=True)
    finally:
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL); child.wait()


def status():
    value = {'received':{},'workers':[],'audit_passed':False}
    pointer=OUT/'controller.json'
    value['controller_active']=pointer.exists() and alive(json.loads(pointer.read_text()))
    value['model_verified']=(OUT/'model_verification.json').exists()
    for a in ('baseline','nli','pj_v3','lora42','lora43','lora44'):
        value['received'][a]=len(list((OUT/'records'/a).glob('*.json')))
    for worker in (0,1):
        log=OUT/f'worker-{worker}.log'
        if log.exists():
            lines=log.read_text(errors='replace').splitlines()
            events=[l for l in lines if l.startswith('{"phase":')]
            error=any('Traceback (most recent call last)' in l for l in lines)
            value['workers'].append({'worker':worker,'last':json.loads(events[-1]) if events else 'loading/warmup',
                'error_tail':lines[-8:] if error else []})
    if (OUT/'audit.json').exists():
        value['audit_passed']=json.loads((OUT/'audit.json').read_text())['passed']
    log=OUT/'controller.log'
    if log.exists() and not value['controller_active']:
        value['controller_tail']=log.read_text(errors='replace').splitlines()[-8:]
    print(json.dumps(value))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['launch','controller','status'])
    {'launch':launch,'controller':controller,'status':status}[parser.parse_args().action]()
