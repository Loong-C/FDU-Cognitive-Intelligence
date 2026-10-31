"""Remote read-only package inventory; never serialize environment secrets."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

names = sorted({d.metadata['Name'] for d in importlib.metadata.distributions() if d.metadata['Name']})
inventory = {'python': platform.python_version(), 'executable': sys.executable,
             'platform': platform.platform(),
             'packages': {name: importlib.metadata.version(name) for name in names}}
serialized = json.dumps(inventory, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
receipt = {'inventory': inventory, 'inventory_sha256': hashlib.sha256(serialized).hexdigest(),
           'environment_variables_collected': False, 'packages_modified': False}
path = Path('/root/ab_finetune27b_20261030/revision_2_runs/formal/environment_packages.json')
path.write_text(json.dumps(receipt, sort_keys=True, indent=2)+'\n')
print(json.dumps({'packages': len(names), 'inventory_sha256': receipt['inventory_sha256']}))
