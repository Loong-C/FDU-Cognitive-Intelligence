"""Import explicitly authored review decisions; no automatic label-based approval."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root/'src'))
from ab_factcheck import finetune27b_v2 as c

p = argparse.ArgumentParser()
p.add_argument('decisions', type=Path, help='Agent-authored JSON list of id/status/rationale/review_note')
p.add_argument('--amend',action='store_true',help='Explicitly replace reviewed decisions while preserving the previous version')
args = p.parse_args()
train = {r['id']: r for r in c.rows(root/c.EXP/'train.jsonl')}
out = root/'outputs/finetune27b_v2/reviews.jsonl'
existing = c.rows(out) if out.exists() else []
known = {r['id'] for r in existing}
current = {r['id']:r for r in existing}
history_path=out.with_name('reviews_history.jsonl')
history=c.rows(history_path) if history_path.exists() else [
    {'operation':'snapshot_of_prior_reviews','decision':r} for r in existing]
new = []
batch_seen=set()
for decision in c.read_json(args.decisions):
    row = train[decision['id']]
    if row['id'] in batch_seen:
        raise ValueError('Duplicate ID in one decision batch')
    batch_seen.add(row['id'])
    if row['id'] in known and not args.amend:
        raise ValueError('Review already exists; preserve and explicitly amend it')
    known.add(row['id'])
    draft = root/'outputs/finetune27b_v2/drafts'/(c.record_key(row)+'.json')
    if decision['status'] not in ('approved', 'exclude_group') or not decision.get('review_note'):
        raise ValueError('Explicit review decision required')
    if decision['status'] == 'approved' and not 0 < len(decision.get('rationale','').split()) <= 60:
        raise ValueError('Reviewed rationale must contain 1..60 words')
    value={**decision, 'label': row['label'], 'dataset': row['dataset'], 'group': row['group'],
           'reviewer': 'agent', 'draft_sha256': c.sha(draft)}
    history.append({'operation':'amend' if row['id'] in current else 'initial_review',
                    'recorded_utc':datetime.now(timezone.utc).isoformat(),
                    'batch_sha256':c.sha(args.decisions),'previous':current.get(row['id']),'decision':value})
    current[row['id']]=value
    new.append(value)
c.write_rows(history_path,history)
c.write_rows(out,list(current.values()))
print({'reviewed':len(current),'imported_decisions':len(new),'amend':args.amend})
