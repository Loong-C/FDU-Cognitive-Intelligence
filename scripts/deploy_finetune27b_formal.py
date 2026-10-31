"""Remote-only deployment. Keep the running draft workspace byte-for-byte intact."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile

base = Path('/root/ab_finetune27b_20261030')
workspace = base/'revision_2_formal_workspace'
archive = base/'setup/finetune27b_v2.tar.gz'
formal = base/'revision_2_runs/formal'
workspace.mkdir(exist_ok=True)
for proc in Path('/proc').glob('[0-9]*'):
    if proc.name == str(os.getpid()):
        continue
    try:
        active = (proc/'cmdline').read_bytes()
        if b'ab_factcheck.finetune27b_run_v2' in active and (proc/'cwd').resolve() == workspace:
            raise RuntimeError('Formal model process is active; deployment refused')
    except (FileNotFoundError, PermissionError):
        pass

with tarfile.open(archive) as tar:
    members = tar.getmembers()
    for member in members:
        relative = Path(member.name)
        if (not member.isfile() or relative.is_absolute() or '..' in relative.parts
                or not (workspace/relative).resolve().is_relative_to(workspace.resolve())
                or relative.name == 'test.jsonl' or relative.name.startswith('.env')):
            raise ValueError('Forbidden deployment archive member')
        destination = workspace/relative
        if formal.exists() and any(formal.glob('seed-*/identity.json')) and destination.exists():
            if destination.read_bytes() != tar.extractfile(member).read():
                raise RuntimeError('Formal training has started; refuse changing deployed code or freeze')
    tar.extractall(workspace, filter='data')

# The live draft guard still uses its original setup file until service recovery.
guard = base/'private/guard-parallel-drafts'
if (guard/'restored.json').exists():
    for name in ('finetune27b_service_guard.py', 'finetune27b_pipeline_v2.py', 'continue_finetune27b_v2.py'):
        shutil.copyfile(workspace/'scripts'/name, base/'setup'/name)
print(json.dumps({'deployed': str(workspace), 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                  'draft_workspace_untouched': True, 'setup_updated': (guard/'restored.json').exists()}))
