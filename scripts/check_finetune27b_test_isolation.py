"""Run revision_2 engineering tests in a copy with development data only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

root=Path(__file__).resolve().parents[1]
sandbox=root/'outputs/finetune27b_v2/test_without_original'
sandbox.mkdir(parents=True,exist_ok=True)
tests=['test_finetune27b_v2.py','test_finetune27b_receipts.py','test_finetune27b_review_import.py',
       'test_finetune27b_service_guard.py','test_finetune27b_offline_audit.py']
sources=['__init__.py','common.py','metrics.py','splitting.py','finetune27b_v2.py','finetune27b_engine.py',
         'finetune27b_run_v2.py','finetune27b_training_v2.py']
scripts=['audit_finetune27b_v2.py','recompute_finetune27b_v2.py','append_finetune27b_reviews.py',
         'finetune27b_service_guard.py','package_finetune27b_v2.py']
names=[f'tests/{n}' for n in tests]+[f'src/ab_factcheck/{n}' for n in sources]+[f'scripts/{n}' for n in scripts]
names+=['prompts/v1/A0_system.txt','prompts/v1/A0_user.txt',
        'data/splits/v1/basic/dev.jsonl','data/splits/v1/challenge/dev.jsonl',
        'experiments/016_finetune_27b/model_source.json']
revision=root/'experiments/016_finetune_27b/revision_2'
names += [p.relative_to(root).as_posix() for p in revision.rglob('*')
          if p.is_file() and '__pycache__' not in p.parts]
for name in names:
    if '/test.jsonl' in name or name.startswith('data/raw/'):
        raise ValueError('Original benchmark data are forbidden in this copy')
    destination=sandbox/name
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(root/name,destination)
if list((sandbox/'data').rglob('test.jsonl')) or (sandbox/'data/raw').exists():
    raise ValueError('Isolation workspace contains original benchmark files')
(sandbox/'pytest.ini').write_text('[pytest]\ntestpaths = tests\npythonpath = src\n',encoding='utf-8')
environment=dict(os.environ,PYTHONPATH=str(sandbox/'src'),PYTHONIOENCODING='utf-8',PYTHONUTF8='1')
temporary=(sandbox/('pytest-temp-'+uuid.uuid4().hex)).resolve()
if not temporary.is_relative_to(sandbox.resolve()) or temporary.exists():
    raise ValueError('Pytest temporary directory must be new and stay in the isolated workspace')
arguments=['-q','-c',str(sandbox/'pytest.ini'),'--confcutdir',str(sandbox),
           '--basetemp',str(temporary),*[f'tests/{n}' for n in tests]]
driver=('from pathlib import Path; from ab_factcheck import finetune27b_v2 as c; '
        'assert c.ROOT == Path.cwd(); import pytest; raise SystemExit(pytest.main('+repr(arguments)+'))')
result=subprocess.run([sys.executable,'-c',driver],cwd=sandbox,env=environment,capture_output=True)
log=root/'outputs/finetune27b_v2/isolated_tests.log'
log.write_bytes(result.stdout+result.stderr)
output=result.stdout.decode('utf-8',errors='replace')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
receipt={'passed':result.returncode==0,'test_files':tests,'original_test_files_present':False,
         'raw_benchmark_present':False,'import_root_verified':True,
         'summary':output.strip().splitlines()[-1] if output.strip() else '',
         'log_sha256':sha(log),'compute_sha256':{name:sha(sandbox/f'src/ab_factcheck/{name}') for name in sources},
         'scope':'This run only; does not erase the earlier full-suite data-access deviation'}
(revision/'acceptance/no_original_files_tests.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
if hasattr(sys.stdout,'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
print(output[-5000:])
print(json.dumps(receipt,indent=2))
raise SystemExit(result.returncode)
