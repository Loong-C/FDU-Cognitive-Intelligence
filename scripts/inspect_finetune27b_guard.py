"""Read lifecycle status and a key-redacted tail, never its private snapshot."""
import json
import os
from pathlib import Path

base = Path('/root/ab_finetune27b_20261030')
guard_name = os.environ.get('AB_GUARD_NAME', 'guard-parallel-drafts')
if '/' in guard_name or not guard_name.startswith('guard-'):
    raise ValueError('Expected a private guard directory name')
directory = base/'private'/guard_name
key = (base/'private/api_key').read_text().strip()
for name in ('guard_process.json', 'restored_process.json', 'restored.json'):
    path = directory/name
    if path.exists():
        value = json.loads(path.read_text())
        if 'pid' in value:
            value['running'] = Path('/proc', str(value['pid'])).exists()
        print(json.dumps({name: value}))
log = directory/'restored_service.log'
if log.exists():
    tail = log.read_text(errors='replace').splitlines()[-20:]
    for line in tail:
        if 'api_key' in line.lower() or 'api-key' in line.lower():
            continue
        print(line.replace(key, '[REDACTED]'))
