"""Create an isolated overlay environment without modifying the serving environment."""
import json
from pathlib import Path
import subprocess
import sys

base = Path('/root/ab_finetune27b_20261030')
venv = base / 'venv'
if not (venv / 'bin/python').exists():
    subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True)
site = next((venv / 'lib').glob('python*/site-packages'))
(site / 'serving_dependencies.pth').write_text('/root/ascend/lib/python3.12/site-packages\n')
subprocess.run([str(venv / 'bin/python'), '-m', 'pip', 'install', '--no-deps',
                '--index-url', 'https://pypi.org/simple', 'peft==0.21.0'], check=True)
print(json.dumps({'environment': str(venv), 'serving_environment_modified': False}))
