"""Remote launch after the real service recovery acceptance has passed."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

base = Path('/root/ab_finetune27b_20261030')
prior = base/'private/guard-failure-check'
receipt = json.loads((prior/'restored.json').read_text())
assert receipt['restored'] and receipt['generation_checked']
service = json.loads((prior/'restored_process.json').read_text())
old = int((base/'revision_2_drafts.pid').read_text())
proc = Path('/proc', str(old))
if proc.exists():
    args = (proc/'cmdline').read_bytes()
    if b'ab_factcheck.finetune27b_run_v2' not in args or b'draft' not in args:
        raise RuntimeError('Old draft PID changed')
    os.kill(old, signal.SIGINT)
    for _ in range(60):
        if not proc.exists() or (proc/'stat').read_text().rsplit(')',1)[1].split()[0] == 'Z':
            break
        time.sleep(1)
    else:
        raise RuntimeError('Old draft process did not stop')
# Only the dispatcher changes; preserve the original engine, tokenizer and model math.
destination = base/'revision_2_workspace/src/ab_factcheck/finetune27b_run_v2.py'
destination.write_bytes((base/'setup/finetune27b_parallel_runner.py').read_bytes())
source = base/'revision_2_runs/rationale_drafts/drafts'
record = {'change':'single worker to five disjoint deterministic shards',
          'preserved_received_drafts': sorted(p.name for p in source.glob('*_e_*.json')),
          'runner_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
          'devices':[0,2,3,4,5], 'original_test_content_read':False}
(base/'revision_2_runs/rationale_drafts/parallel_amendment.json').write_text(json.dumps(record,indent=2))
with (base/'logs/revision_2_parallel.log').open('ab') as log:
    process = subprocess.Popen(['/root/ascend/bin/python', str(base/'setup/finetune27b_service_guard.py'),
        'pause-and-run', '--pid', str(service['pid']), '--directory', str(base/'private/guard-parallel-drafts'),
        '--key-file', str(base/'private/api_key'), '--',
        '/root/ascend/bin/python', str(base/'setup/finetune27b_parallel_drafts.py')],
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
(base/'revision_2_parallel.pid').write_text(str(process.pid))
print(json.dumps({'guard_pid': process.pid, 'devices':record['devices'],
                  'preserved_drafts':len(record['preserved_received_drafts'])}))
