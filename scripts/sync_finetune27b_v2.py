"""Pull immutable draft receipts only; never fetch credentials or benchmark tests."""
import json
import argparse
import hashlib
import shlex
from pathlib import Path
import paramiko

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--verify-all', action='store_true', help='Compare every local receipt with its remote SHA-256 before freezing')
args = parser.parse_args()
settings = dict(line.split('=', 1) for line in Path('F:/Personal/Code/A_B/.env.ssh.local').read_text().splitlines())
client = paramiko.SSHClient()
client.load_host_keys(str(root/'configs/server_ssh_known_hosts'))
source = '/root/ab_finetune27b_20261030/revision_2_runs/rationale_drafts/drafts'
target = root/'outputs/finetune27b_v2/drafts'
target.mkdir(parents=True, exist_ok=True)
try:
    client.connect(settings['AB_SSH_HOST'], port=int(settings['AB_SSH_PORT']), username=settings['AB_SSH_USER'],
                   password=settings['AB_SSH_PASSWORD'], look_for_keys=False, allow_agent=False, timeout=15)
    count = 0
    with client.open_sftp() as sftp:
        for item in sftp.listdir_attr(source):
            if not item.filename.endswith('.json'):
                continue
            dest = target/item.filename
            if dest.exists():
                if dest.stat().st_size != item.st_size:
                    raise ValueError('Immutable remote draft changed')
                continue
            temp = dest.with_suffix('.partial')
            sftp.get(source+'/'+item.filename, str(temp))
            json.loads(temp.read_text(encoding='utf-8'))
            temp.rename(dest)
            count += 1
    verified = 0
    if args.verify_all:
        program = ('import pathlib,hashlib,json; p=pathlib.Path('+repr(source)+'); '
                   'print(json.dumps({f.name:hashlib.sha256(f.read_bytes()).hexdigest() '
                   'for f in p.glob("*.json")}))')
        stdin, stdout, stderr = client.exec_command('/usr/bin/python3 -c '+shlex.quote(program), timeout=60)
        stdin.close()
        hashes = json.loads(stdout.read().decode())
        if stdout.channel.recv_exit_status() != 0:
            raise RuntimeError('Remote draft hashing failed')
        for name, expected in hashes.items():
            local = target/name
            if not local.exists():
                continue  # A new atomic receipt may have arrived after this sync.
            if hashlib.sha256(local.read_bytes()).hexdigest() != expected:
                raise ValueError('Immutable draft hash mismatch: '+name)
            verified += 1
    print(json.dumps({'downloaded': count, 'drafts_available': len(list(target.glob('*_e_*.json'))),
                      'remote_hashes_verified': verified}))
finally:
    client.close()
