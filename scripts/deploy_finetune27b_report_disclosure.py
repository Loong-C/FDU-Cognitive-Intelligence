"""Remote report-only disclosure correction; frozen computation is untouched."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

base=Path('/root/ab_finetune27b_20261030')
workspace=base/'revision_2_formal_workspace'
sys.path.insert(0,str(workspace/'src'))
from ab_factcheck import finetune27b_v2 as c

before_hash='3828dde269950edbf8a6c1dc97ba7e7abc96c5a0213eb6a5f6949293e84ab72e'
after_hash='21c8c0e907844fb91012d6794c5c8e73966aaf323e5ebe44a08273b79a33e9cb'
disclosure_hash='9205d6d417111d90c1f55f161392f8ff9592ad9c541f12914de32da36ea8f834'
c.verify_training()
frozen=workspace/c.EXP/'training_freeze.json'
if c.sha(frozen) != '50bea167e2ec5e748ce96c17aa23f74d694272d81cf30deb8cf64324b7f0a4dc':
    raise ValueError('Unexpected training freeze')
names=['finetune27b_v2.py','finetune27b_engine.py','finetune27b_run_v2.py',
       'finetune27b_training_v2.py','metrics.py','common.py']
compute={name:c.sha(workspace/'src/ab_factcheck'/name) for name in names}
live=workspace/'scripts/audit_finetune27b_v2.py'
pending=base/'setup/audit_finetune27b_v2_disclosure.py'
access_pending=base/'setup/finetune27b_data_access_audit.json'
if c.sha(live) != before_hash or c.sha(pending) != after_hash or c.sha(access_pending) != disclosure_hash:
    raise ValueError('Report-only patch identity mismatch')
archive=workspace/c.EXP/'report_revisions/audit_before_access_disclosure.py.txt'
archive.parent.mkdir(parents=True,exist_ok=True)
if archive.exists() and c.sha(archive) != before_hash:
    raise ValueError('Existing report archive differs')
shutil.copyfile(live,archive)
shutil.copyfile(access_pending,workspace/c.EXP/'data_access_audit.json')
pending.replace(live)
if compute != {name:c.sha(workspace/'src/ab_factcheck'/name) for name in names}:
    raise ValueError('Frozen computation unexpectedly changed')
c.verify_training()
receipt={'report_only':True,'reason':'Disclose historical engineering-test reads of original benchmark data',
         'previous_audit_sha256':before_hash,'current_audit_sha256':c.sha(live),
         'data_access_disclosure_sha256':disclosure_hash,'training_freeze_sha256':c.sha(frozen),
         'frozen_compute_unchanged':True,'compute_sha256':compute,
         'training_selection_parsing_metrics_or_statistical_rules_changed':False}
c.save(base/'revision_2_runs/formal/report_disclosure_revision.json',receipt)
print(json.dumps(receipt))
