"""Lossless review packets and explicit Agent-authored decisions, not auto-review.

An input decision must explicitly address each of the three sources for each row.
The helper only binds IDs/hashes and validates formatting; it never decides semantic
acceptance from label agreement. This local review aid is outside the frozen runner.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ab_factcheck import fusion_v18 as f, finetune27b_v2 as c

REVIEW_DIR = ROOT / f.EXP / 'review_decisions'


def context():
    receipt = c.read_json(ROOT / 'outputs/fusion_v18_collection/latest_teachers.json')
    if not receipt['verified'] or not receipt['api_restored']:
        raise ValueError('Verified teacher collection required')
    return f.data('train'), Path(receipt['received'])


def draft_text(record):
    return '\n'.join(record['text'].strip().splitlines()[:-1]).strip()


def packet(start, count):
    rows, received = context()
    for i in range(start, min(start + count, len(rows))):
        row = rows[i]; key = c.record_key(row)
        print(f"\n=== ROW {i} | {key} | {row['mechanism']} ===")
        print('E:', row['evidence']); print('C:', row['claim']); print('G:', row['label'])
        print('Original reviewed reason:', row['rationale'])
        for source in f.SOURCES:
            r = f.check_record(c.read_json(received / 'teachers' / source / (key + '.json')))
            print(f"{source} ({len(draft_text(r).split())} reason words; {r['status']}):\n{r['text']}")


def append(path):
    rows, received = context()
    decisions = c.read_json(path)
    built = []
    for entry in decisions:
        index = entry['index']; row = rows[index]; key = c.record_key(row)
        quote = entry['quote']
        if not quote or quote not in row['evidence']:
            raise ValueError(f'Quote does not occur in row {index}')
        for source in f.SOURCES:
            decision = entry[source]
            record = f.check_record(c.read_json(received / 'teachers' / source / (key + '.json')))
            mode = decision['decision']
            reason = (draft_text(record) if mode == 'accept' else row['rationale'] if mode == 'fallback'
                      else decision['rationale'].strip())
            if mode not in ('accept', 'revise', 'fallback') or not 1 <= len(reason.split()) <= 60:
                raise ValueError(f'Bad decision/length in {index}/{source}: {len(reason.split())}')
            if mode == 'accept' and record['prediction'] != row['label']:
                raise ValueError('Cannot accept incorrect/invalid teacher output')
            note = decision['note'].strip()
            if not note or 'Verdict:' in reason:
                raise ValueError('Missing review note or malformed reason')
            value = {'source': source, 'key': key, 'draft_sha256': record['record_sha256'], 'decision': mode,
                     'rationale': reason, 'evidence_quote': quote, 'review_note': note,
                     'reviewer': 'Codex Agent: direct per-item evidence and full draft review', 'row_index': index}
            built.append((REVIEW_DIR / source / (key + '.json'), value))
    # Validate every decision before publishing any of this batch.
    for target, value in built:
        if target.exists() and c.read_json(target) != value:
            raise ValueError('Existing review differs; preserve it and document an amendment')
    for target, value in built:
        f.immutable(target, value)
    print(json.dumps({'written_or_verified': len(built), 'rows': [r['index'] for r in decisions]}))


def status(export=False):
    rows, _ = context()
    values = [c.read_json(p) for p in REVIEW_DIR.rglob('*.json')]
    identities = {(r['source'], r['key']) for r in values}
    if len(identities) != len(values):
        raise ValueError('Duplicate review identity')
    complete = [i for i, r in enumerate(rows) if all((s, c.record_key(r)) in identities for s in f.SOURCES)]
    if export:
        if len(values) != 2184 or len(complete) != 728:
            raise ValueError('All 728 rows and three sources must be reviewed before export')
        c.write_rows(ROOT / f.EXP / 'reviews.jsonl', sorted(values, key=lambda r: (r['row_index'], r['source'])))
    print(json.dumps({'decisions': len(values), 'complete_rows': len(complete),
                      'first_pending': next((i for i in range(728) if i not in complete), None),
                      'counts': dict(Counter(r['decision'] for r in values))}))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(); p.add_argument('action', choices=['packet', 'append', 'status', 'export'])
    p.add_argument('--start', type=int, default=0); p.add_argument('--count', type=int, default=8)
    p.add_argument('--file', type=Path); a = p.parse_args()
    if a.action == 'packet': packet(a.start, a.count)
    elif a.action == 'append': append(a.file)
    else: status(a.action == 'export')
