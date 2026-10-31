"""Show complete inputs plus draft for explicit agent review; never auto-approve."""
import argparse
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root/'src'))
from ab_factcheck import finetune27b_v2 as c

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
p = argparse.ArgumentParser()
p.add_argument('--start', type=int, default=0)
p.add_argument('--count', type=int, default=20)
p.add_argument('--pending', action='store_true', help='Show only available drafts not yet explicitly reviewed')
args = p.parse_args()
data = c.rows(root/c.EXP/'train.jsonl')
drafts = root/'outputs/finetune27b_v2/drafts'
review_file = root/'outputs/finetune27b_v2/reviews.jsonl'
reviewed = {r['id'] for r in c.rows(review_file)} if review_file.exists() else set()
shown = 0
for index, row in enumerate(data[args.start:], args.start):
    path = drafts/(c.record_key(row)+'.json')
    if args.pending and (row['id'] in reviewed or not path.exists()):
        continue
    if shown >= args.count:
        break
    shown += 1
    if not path.exists():
        print(json.dumps({'index': index, 'id': row['id'], 'draft': 'PENDING'}))
        continue
    value = c.read_json(path)
    print(json.dumps({'index': index, **{k: row[k] for k in ('id', 'group', 'mechanism', 'evidence', 'claim', 'label')},
                      'draft': value['text'], 'prediction': value['prediction']}, ensure_ascii=False))
