"""Collect completed experiment artifacts with SHA-256 verification.

Only experiment outputs and explicitly named stage logs are eligible. Model
weights, optimizer caches, credentials and serving snapshots are never fetched.
The three selected LoRA files are kept under the ignored outputs directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import sys

REMOTE_MANIFEST = r'''
import hashlib, json, re
from datetime import datetime, timezone
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
base = Path('/root/ab_finetune27b_20261030')
run = base/'revision_2_runs/formal'
audit = json.loads((run/'audit.json').read_text())
assert audit['passed'] and (run/'RESULTS.md').is_file()
assert hashlib.sha256((run/'results.json').read_bytes()).hexdigest() == audit['results_sha256']
files = {}
def include(path, destination):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing or linked output: '+str(destination))
    if not path.resolve().is_relative_to(base.resolve()):
        raise ValueError('Output escaped experiment directory')
    files[destination] = {'source':str(path), 'bytes':path.stat().st_size,
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
for path in run.rglob('*'):
    if path.suffix in ('.json', '.jsonl', '.csv', '.md') and '.incomplete' not in str(path):
        include(path, 'formal/'+path.relative_to(run).as_posix())
for seed in (42,43,44):
    folder = run/f'seed-{seed}'
    assert json.loads((folder/'training_complete.json').read_text())['epochs'] == 3
    selection = json.loads((folder/'selection.json').read_text())['selected']
    name = selection['checkpoint']
    assert re.fullmatch(r'checkpoint-e\d+-c\d+', name)
    adapter = folder/name/'adapter_model.safetensors'
    assert hashlib.sha256(adapter.read_bytes()).hexdigest() == selection['adapter_sha256']
    include(adapter, 'formal/'+adapter.relative_to(run).as_posix())
for arm in ('baseline','42','43','44'):
    assert len(list((run/'holdout'/arm).glob('*_e_*.json'))) == 261
for action, seeds in [('smoke',(42,)),('train',(42,43,44)),('validate-baseline',(42,)),
                      ('select',(42,43,44)),('evaluate',(42,))]:
    for seed in seeds:
        name = f'revision_2_{action}_{seed}.log'
        include(base/'logs'/name, 'logs/'+name)
guards = sorted((base/'private').glob('guard-formal-*'), key=lambda p:p.stat().st_mtime)
assert guards
restored = json.loads((guards[-1]/'restored.json').read_text())
assert restored['restored'] and restored['generation_checked']
spec = spec_from_file_location('service_guard',base/'setup/finetune27b_service_guard.py')
guard = module_from_spec(spec)
spec.loader.exec_module(guard)
current = json.loads((base/'private/current_service.json').read_text())
assert guard.matching(current)
guard.health('http://10.176.30.103:20027/v1',base/'private/api_key')
# Return only the public health booleans, never snapshot/argv/env/key contents.
print(json.dumps({'files':files, 'service_recovery':{
    'restored':True, 'generation_checked':True, 'models_checked':True,
    'checked_again_after_final_evaluation':True,
    'health_check_utc':datetime.now(timezone.utc).isoformat(),
    'guard_directory':guards[-1].name}}))
'''


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def destination(root, relative):
    name = PurePosixPath(relative)
    if name.is_absolute() or '..' in name.parts or '\\' in relative or ':' in relative:
        raise ValueError('Unsafe artifact name')
    target = (root/Path(*name.parts)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('Artifact escaped local output directory')
    return target


def main():
    import paramiko
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true', help='Copy verified text reports to the experiment documentation')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root/'outputs/finetune27b_v2/completed'
    credentials = Path(os.environ.get('AB_SSH_ENV_FILE','F:/Personal/Code/A_B/.env.ssh.local'))
    settings = dict(line.split('=',1) for line in credentials.read_text(encoding='utf-8-sig').splitlines()
                    if line.strip() and not line.startswith('#'))
    client = paramiko.SSHClient()
    client.load_host_keys(str(root/'configs/server_ssh_known_hosts'))
    try:
        client.connect(settings['AB_SSH_HOST'], port=int(settings['AB_SSH_PORT']),
            username=settings['AB_SSH_USER'], password=settings['AB_SSH_PASSWORD'],
            timeout=15, banner_timeout=15, auth_timeout=15, look_for_keys=False, allow_agent=False)
        stdin, stdout, stderr = client.exec_command('/usr/bin/python3 -c '+shlex.quote(REMOTE_MANIFEST), timeout=240)
        stdin.close()
        content, error = stdout.read(), stderr.read()
        if stdout.channel.recv_exit_status():
            raise RuntimeError('Experiment is incomplete or remote artifact verification failed: '+
                               error.decode(errors='replace').replace(settings['AB_SSH_PASSWORD'],'[REDACTED]'))
        manifest = json.loads(content)
        count = 0
        with client.open_sftp() as sftp:
            for relative, item in sorted(manifest['files'].items()):
                dest = destination(target, relative)
                if dest.exists():
                    if sha(dest) != item['sha256']:
                        raise ValueError('Previously collected artifact changed: '+relative)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                partial = dest.with_name(dest.name+'.partial')
                sftp.get(item['source'], str(partial))
                if partial.stat().st_size != item['bytes'] or sha(partial) != item['sha256']:
                    raise ValueError('Transfer checksum mismatch: '+relative)
                if partial.suffix != '.safetensors' and dest.suffix != '.safetensors':
                    if settings['AB_SSH_PASSWORD'].encode() in partial.read_bytes():
                        raise ValueError('Credential unexpectedly present in output; collection stopped')
                partial.replace(dest)
                count += 1
                if count % 250 == 0:
                    print(json.dumps({'downloaded':count}), flush=True)
        # Paths are relative in the portable manifest; private snapshot paths are absent.
        portable = {'files':{name:{k:v for k,v in item.items() if k != 'source'}
                             for name,item in manifest['files'].items()},
                    'service_recovery':manifest['service_recovery']}
        target.mkdir(parents=True, exist_ok=True)
        (target/'manifest.json').write_text(json.dumps(portable,indent=2)+'\n',encoding='utf-8')
        if args.publish:
            public = root/'experiments/016_finetune_27b/revision_2/results'
            public.mkdir(parents=True, exist_ok=True)
            for name in ('RESULTS.md','results.json','audit.json','predictions.csv'):
                shutil.copyfile(target/'formal'/name, public/name)
            for seed in (42,43,44):
                shutil.copyfile(target/f'formal/seed-{seed}/selection.json', public/f'selection-{seed}.json')
            shutil.copyfile(target/'manifest.json', public/'artifact_manifest.json')
            (public/'service_recovery.json').write_text(json.dumps(manifest['service_recovery'],indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'verified_files':len(portable['files']), 'downloaded':count,
                          'destination':str(target), 'published':args.publish}))
    finally:
        client.close()


if __name__ == '__main__':
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
