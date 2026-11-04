"""Persistently collect, independently recompute, and publish completed V17 results.

No model calls, no service control, no original test/raw benchmark reads.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import warnings

warnings.filterwarnings('ignore')
import paramiko

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT/'outputs/unified_v17_collection'
REMOTE = '/root/ab_finetune27b_20261030'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(path)


def connect():
    settings={}
    credential=Path(os.environ.get('AB_SSH_ENV_FILE','F:/Personal/Code/A_B/.env.ssh.local'))
    for line in credential.read_text(encoding='utf-8-sig').splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            name,value=line.split('=',1);settings[name.strip()]=value
    client=paramiko.SSHClient()
    client.load_host_keys(str(ROOT/'configs/server_ssh_known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(settings['AB_SSH_HOST'],port=int(settings['AB_SSH_PORT']),username=settings['AB_SSH_USER'],
        password=settings['AB_SSH_PASSWORD'],look_for_keys=False,allow_agent=False,
        timeout=15,banner_timeout=15,auth_timeout=15)
    return client


def status(client):
    command=f'{REMOTE}/venv/bin/python {REMOTE}/setup/manage_unified_v17.py status'
    stdin,stdout,stderr=client.exec_command(command,timeout=30)
    stdin.close()
    text=stdout.read().decode();code=stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError('Remote status command failed')
    value=json.loads(text)
    value['checked_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    value['total_received']=sum(value['received'].values())
    save(LOCAL/'status.json',value)
    return value


def collect(client):
    archive=LOCAL/'received.tar.gz'
    with client.open_sftp() as sftp:
        sftp.get(REMOTE+'/setup/unified_v17_results.tar.gz',str(archive.with_suffix('.part')))
    archive.with_suffix('.part').replace(archive)
    received=LOCAL/'received'
    received.mkdir(exist_ok=True)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            target=(received/member.name).resolve()
            if not target.is_relative_to(received.resolve()) or not member.isfile():
                raise ValueError('Unsafe result archive member')
            content=tar.extractfile(member).read()
            if target.exists() and target.read_bytes() != content:
                raise ValueError('Received artifact would change')
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():
                target.write_bytes(content)
    manifest={p.relative_to(received).as_posix():sha(p) for p in received.rglob('*') if p.is_file()}
    save(LOCAL/'received_manifest.json',manifest)
    copied=LOCAL/'local_recompute'
    shutil.copytree(received,copied,dirs_exist_ok=True)
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src'))
    subprocess.run([sys.executable,'-m','ab_factcheck.unified_v17','report','--output',str(copied)],cwd=ROOT,env=env,check=True)
    subprocess.run([sys.executable,str(ROOT/'scripts/audit_unified_v17.py'),str(copied)],cwd=ROOT,env=env,check=True)
    expected=json.loads((received/'results.json').read_text(encoding='utf-8'))
    actual=json.loads((copied/'results.json').read_text(encoding='utf-8'))
    if expected != actual:
        raise ValueError('Local recomputation differs from server')
    if any(sha(received/name)!=digest for name,digest in manifest.items()):
        raise ValueError('Received original artifact changed')
    interruptions=[]
    for receipt_path in sorted((received/'interruptions').glob('*/resumption.json')):
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        for name,expected_hash in receipt['received_hashes'].items():
            if sha(received/name)!=expected_hash:
                raise ValueError('Pre-interruption answer was changed')
        interruptions.append(receipt)
    publish=ROOT/'experiments/017_unified_comparison/results'
    publish.mkdir(exist_ok=True)
    for name in ('RESULTS.md','results.json','predictions.csv','audit.json','model_verification.json',
                 'worker-0-identity.json','worker-1-identity.json'):
        shutil.copyfile(copied/name,publish/name)
    if interruptions:
        save(publish/'interruptions.json',interruptions)
        count=sum(len(v['interrupted_without_response']) for v in interruptions)
        with (publish/'RESULTS.md').open('a',encoding='utf-8') as stream:
            stream.write('\n## 暂停与恢复披露\n\n'
                '用户曾要求缩减评测，原任务暂停后又要求恢复原规模；缩减版没有执行。'
                f'暂停前已收到的回答均经哈希核验保持原字节。另有 {count} 次中断请求没有收到回答，'
                '原尝试记录保留、用量未知；恢复后仅为缺失评分单元生成回答。'
                '本轮存在暂停与恢复，不能描述为从未中断。详见 interruptions.json。\n')
            if any(v.get('kind')=='resource_oom' for v in interruptions):
                stream.write('评测中发生一次显存不足，收到的失败记录作为 INVALID 保留计错。'
                    '经用户许可暂停原 API 后，两个 worker 改用同型号设备 2/3 恢复，推理代码、参数、数据与适配器不变。'
                    '前后设备资源负载不同，耗时不应外推为纯模型速度差异。\n')
    recovery=received/'resource_service_recovery.json'
    if recovery.exists():
        restored=json.loads(recovery.read_text())
        if not restored.get('restored') or not restored.get('generation_checked'):
            raise ValueError('API recovery is not verified')
        shutil.copyfile(recovery,publish/'resource_service_recovery.json')
    warmup=[json.loads(p.read_text()) for p in (received/'warmup').glob('*.json')]
    completion={'completed':True,'independent_local_recompute_passed':True,'received_files':len(manifest),
        'received_bytes_unchanged':True,'archive_sha256':sha(archive),
        'results_sha256':sha(publish/'results.json'),
        'server_results_sha256':sha(received/'results.json'),
        'server_and_local_results_semantically_equal':True,
        'freeze_sha256':sha(ROOT/'experiments/017_unified_comparison/freeze.json'),
        'collector_sha256':sha(__file__),'completed_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'recorded_interruptions':len(interruptions),
        'resource_interruptions':sum(v.get('kind')=='resource_oom' for v in interruptions),
        'interrupted_attempts_unknown_cost':sum(len(v['interrupted_without_response']) for v in interruptions),
        'pre_interruption_received_answers_verified_unchanged':True,
        'warmup':{'calls':len(warmup),'input_tokens':sum(r['input_tokens'] for r in warmup),
                  'output_tokens':sum(r['output_tokens'] for r in warmup)},
        'report':str(publish/'RESULTS.md')}
    save(publish/'completion.json',completion);save(LOCAL/'completion.json',completion)
    print(json.dumps(completion),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    LOCAL.mkdir(parents=True,exist_ok=True)
    if (LOCAL/'completion.json').exists():
        print((LOCAL/'completion.json').read_text());return
    while True:
        client=None
        try:
            client=connect();value=status(client)
            if not value['controller_active']:
                if value['audit_passed']:
                    collect(client);return
                save(LOCAL/'attention.json',{'reason':'Remote controller stopped before audit completion','status':value})
                raise RuntimeError('Remote run requires attention; no generation retried')
            print(json.dumps({'received':value['total_received'],'total':1566,'checked_utc':value['checked_utc']}),flush=True)
        except (paramiko.SSHException,OSError,TimeoutError) as exc:
            # No sensitive exception text; retry transport only, never model answers.
            save(LOCAL/'transport_retry.json',{'exception_type':type(exc).__name__,'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
            if args.once:
                raise RuntimeError('Connection unavailable') from None
        finally:
            if client:
                client.close()
        if args.once:
            return
        time.sleep(60)


if __name__ == '__main__':
    main()
