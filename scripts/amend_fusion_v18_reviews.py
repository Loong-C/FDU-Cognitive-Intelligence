"""Apply explicit, audited pre-freeze review corrections, preserving original bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ab_factcheck import fusion_v18 as f, finetune27b_v2 as c


def apply(path):
    if (ROOT / f.EXP / 'supervision/completion.json').exists():
        raise ValueError('Cannot amend frozen supervision through this authoring helper')
    entries = c.read_json(path)
    if isinstance(entries, dict):
        entries = [entries]
    rows = f.data('train')
    for entry in entries:
        target = (ROOT / entry['original_path']).resolve()
        if not target.is_relative_to((ROOT / f.EXP / 'review_decisions').resolve()):
            raise ValueError('Amendment target outside review decisions')
        before, after = entry['before'], entry['after']
        row = rows[entry['row_index']]
        for key in ('source', 'key', 'draft_sha256', 'row_index', 'reviewer'):
            if before[key] != after[key]:
                raise ValueError('Amendment changes review identity')
        if c.record_key(row) != after['key'] or after['source'] != entry['source']:
            raise ValueError('Wrong row or source')
        if after['decision'] != 'revise' or not 1 <= len(after['rationale'].split()) <= 60:
            raise ValueError('Invalid revised reason')
        if not after['evidence_quote'] or after['evidence_quote'] not in row['evidence']:
            raise ValueError('Quote missing from this evidence')
        if not entry['reason'] or not after['review_note']:
            raise ValueError('Missing explicit correction reason')
        history = ROOT / f.EXP / 'review_amendments' / entry['source'] / after['key'] / entry['original_sha256']
        if c.read_json(target) == after:
            if not (history / 'amendment.json').exists() or c.sha(history / 'original.json') != entry['original_sha256']:
                raise ValueError('Amended file lacks valid preserved history')
            continue
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['original_sha256'] or c.read_json(target) != before:
            raise ValueError('Original review bytes no longer match proposal')
        history.mkdir(parents=True, exist_ok=True)
        original = history / 'original.json'
        if original.exists() and original.read_bytes() != raw:
            raise ValueError('Different original history exists')
        original.write_bytes(raw)
        f.immutable(history / 'amendment.json', entry)
        c.save(target, after)
        f.immutable(history / 'applied.json', {'original_sha256': entry['original_sha256'],
                    'revised_sha256': c.sha(target), 'proposal_sha256': c.sha(path),
                    'fixed_label': row['label'], 'label_changed': False, 'training_started': False})
    print(json.dumps({'applied_or_verified': len(entries), 'original_bytes_preserved': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('proposal', type=Path)
    apply(parser.parse_args().proposal)
