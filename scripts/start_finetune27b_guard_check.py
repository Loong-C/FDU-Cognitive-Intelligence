"""Remote real failure-path acceptance: terminate a disposable command, restore service."""
import json
from pathlib import Path
import subprocess

base = Path('/root/ab_finetune27b_20261030')
with (base/'logs/revision_2_guard_check.log').open('ab') as log:
    process = subprocess.Popen(['/root/ascend/bin/python', str(base/'setup/finetune27b_service_guard.py'),
        'pause-and-run', '--pid', '2184516', '--directory', str(base/'private/guard-failure-check'),
        '--key-file', str(base/'private/api_key'), '--', '/bin/sh', '-c', 'exit 17'],
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
(base/'revision_2_guard_check.pid').write_text(str(process.pid))
print(json.dumps({'pid':process.pid, 'failure_path_test':True}))
