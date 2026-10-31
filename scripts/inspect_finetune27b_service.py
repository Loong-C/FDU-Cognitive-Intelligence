"""Remote read-only service identification without disclosing command credentials."""
import json
from pathlib import Path

for p in Path('/proc').iterdir():
    if not p.name.isdigit():
        continue
    try:
        args = [v.decode() for v in (p/'cmdline').read_bytes().split(b'\0') if v]
        if any('vllm' in v.lower() for v in args[:2]) and any('27b' in v.lower() for v in args):
            env = dict(v.decode().split('=', 1) for v in (p/'environ').read_bytes().split(b'\0') if v)
            print(json.dumps({'pid': int(p.name), 'executable': args[0],
                'visible_devices': {k:v for k,v in env.items() if k in ('ASCEND_RT_VISIBLE_DEVICES','ASCEND_VISIBLE_DEVICES')},
                'has_api_key_arg': '--api-key' in args,
                'port': args[args.index('--port')+1] if '--port' in args else None}))
    except (FileNotFoundError, PermissionError):
        pass
