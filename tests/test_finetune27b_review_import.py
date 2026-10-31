"""An explicit amendment must retain the prior Agent decision and original draft."""
import shutil
import subprocess
import sys

from ab_factcheck import finetune27b_v2 as c


def test_review_import_and_explicit_amendment_preserve_history(tmp_path):
    for name in ('scripts/append_finetune27b_reviews.py', 'src/ab_factcheck/finetune27b_v2.py',
                 'src/ab_factcheck/__init__.py'):
        target=tmp_path/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(c.ROOT/name,target)
    row={'id':'test_only','dataset':'basic','group':'fixture_group','label':'REFUTES'}
    c.write_rows(tmp_path/c.EXP/'train.jsonl',[row])
    drafts=tmp_path/'outputs/finetune27b_v2/drafts'
    c.save(drafts/(c.record_key(row)+'.json'),{'text':'Synthetic original draft.'})
    decision={'id':row['id'],'status':'approved','rationale':'Synthetic explanation.',
              'review_note':'TEST FIXTURE, not a real annotation.'}
    batch=tmp_path/'batch.json'
    c.save(batch,[decision])
    command=[sys.executable,str(tmp_path/'scripts/append_finetune27b_reviews.py'),str(batch)]
    subprocess.run(command,check=True,capture_output=True)
    output=tmp_path/'outputs/finetune27b_v2/reviews.jsonl'
    first=c.rows(output)[0]
    assert subprocess.run(command,capture_output=True).returncode != 0
    assert c.rows(output)==[first]
    amended=dict(decision,status='exclude_group',rationale='',review_note='Explicit ambiguity review in test fixture.')
    c.save(batch,[amended])
    subprocess.run(command+['--amend'],check=True,capture_output=True)
    history=c.rows(output.with_name('reviews_history.jsonl'))
    assert len(history)==2 and history[1]['operation']=='amend'
    assert history[1]['previous']==first
    assert history[1]['decision']==c.rows(output)[0]
    assert history[1]['decision']['draft_sha256']==first['draft_sha256']
    assert history[1]['batch_sha256']==c.sha(batch)
