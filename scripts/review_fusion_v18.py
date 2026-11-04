"""Print small review packets; never automatically accept model agreement."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ab_factcheck import fusion_v18 as f, finetune27b_v2 as c


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start', type=int, default=0); parser.add_argument('--count', type=int, default=5)
    args = parser.parse_args()
    for row in f.data('train')[args.start:args.start + args.count]:
        key = c.record_key(row)
        records = {s: f.check_record(c.read_json(args.output / 'teachers' / s / (key + '.json'))) for s in f.SOURCES}
        print(json.dumps({'key': key, 'evidence': row['evidence'], 'claim': row['claim'], 'gold': row['label'],
                          'original_reviewed_rationale': row['rationale'], 'drafts': {
                              s: {'text': r['text'], 'draft_sha256': r['record_sha256'], 'status': r['status']} for s, r in records.items()}}, ensure_ascii=False))
