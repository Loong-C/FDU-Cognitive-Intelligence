"""Supply the unchanged shared utility omitted from the deployment allowlist."""
from pathlib import Path
import json
import shutil
import sys

base=Path('/root/ab_finetune27b_20261030')
workspace=base/'revision_2_formal_workspace'
sys.path.insert(0,str(workspace/'src'))
from ab_factcheck import finetune27b_v2 as c

expected='32be3ee4dd589c7aa02c0b9c1d459e227ff25870f10ace901e9acf87231ddba1'
frozen=workspace/c.EXP/'training_freeze.json'
if c.sha(frozen) != '50bea167e2ec5e748ce96c17aa23f74d694272d81cf30deb8cf64324b7f0a4dc':
    raise ValueError('Unexpected training freeze')
names=['finetune27b_v2.py','finetune27b_engine.py','finetune27b_run_v2.py',
       'finetune27b_training_v2.py','metrics.py','common.py']
compute={name:c.sha(workspace/'src/ab_factcheck'/name) for name in names}
source=base/'setup/finetune27b_splitting_dependency.py'
destination=workspace/'src/ab_factcheck/splitting.py'
if c.sha(source) != expected:
    raise ValueError('Dependency differs from the originally tested source hash')
missing=not destination.exists()
if destination.exists() and c.sha(destination) != expected:
    raise ValueError('Refuse replacing a different existing dependency')
if missing:
    temporary=destination.with_suffix('.py.pending')
    shutil.copyfile(source,temporary)
    temporary.replace(destination)
from ab_factcheck import metrics
if tuple(metrics.LABELS) != c.LABELS:
    raise ValueError('Metric label vocabulary differs')
if compute != {name:c.sha(workspace/'src/ab_factcheck'/name) for name in names}:
    raise ValueError('Frozen computation unexpectedly changed')
c.verify_training()
receipt={'passed':True,'previously_missing':missing,'file':'src/ab_factcheck/splitting.py',
         'sha256':c.sha(destination),'matches_pretraining_engineering_source_hash':True,
         'metric_import_passed':True,'frozen_compute_unchanged':True,'compute_sha256':compute,
         'training_freeze_sha256':c.sha(frozen),
         'reason':'Deployment allowlist omitted an existing unchanged transitive dependency'}
c.save(base/'revision_2_runs/formal/package_dependency_repair.json',receipt)
print(json.dumps(receipt))
