"""Read-only verification of actual published training checkpoints."""
import json
from pathlib import Path
import sys

base = Path('/root/ab_finetune27b_20261030')
sys.path.insert(0, str(base/'revision_2_formal_workspace/src'))
from ab_factcheck import finetune27b_v2 as core
from ab_factcheck.finetune27b_training_v2 import identity, recover_latest

protocol = core.verify_training()
run = base/'revision_2_runs/formal'
environment = core.read_json(run/'smoke/receipt.json')['environment']
entries = []
for seed in core.SEEDS:
    folder = run/f'seed-{seed}'
    expected = identity(protocol, environment, seed)
    if core.read_json(folder/'identity.json') != expected:
        raise ValueError('Seed identity differs from accepted environment')
    latest = recover_latest(folder, expected)
    if latest is None:
        print(json.dumps({'ready':False, 'waiting_for_seed':seed}))
        raise SystemExit(0)
    receipt = latest['receipt']
    if not 1 <= receipt['epoch'] <= 3 or not 0 < receipt['cursor'] <= sum(
            v['rows'] for v in protocol['reviewed_training_summary'].values()):
        raise ValueError('Checkpoint cursor outside frozen dataset')
    entries.append({'seed':seed, 'checkpoint':latest['checkpoint'],
                    'epoch':receipt['epoch'], 'cursor':receipt['cursor'],
                    'receipt_sha256':core.sha(folder/latest['checkpoint']/'receipt.json'),
                    'adapter_sha256':receipt['adapter_sha256'],
                    'adapter_config_sha256':receipt['adapter_config_sha256'],
                    'optimizer_sha256':receipt['optimizer_sha256']})
result={'passed':True, 'checks':'Published adapter/config/optimizer hashes, frozen identity, data cursor',
        'checkpoints':entries, 'checkpoint_files_modified':False}
core.save(run/'checkpoint_integrity.json',result)
print(json.dumps(result))
