"""Pre-score semantic amendment: explicitly align event and exclusivity scopes."""
import hashlib
from .controlled_v15_data import generate as original_generate, LABELS, MECHANISMS

def generate():
    rows = original_generate()
    amended = 0
    for row in rows:
        if row['dataset'] == 'basic' and row['mechanism'] == 'RELDATE':
            if '/t1/' in row['group']:
                row['evidence'] = 'The package had exactly one arrival in its entire delivery history. ' + row['evidence']
            else:
                row['evidence'] = 'The exhibition had exactly one opening event. ' + row['evidence']
        elif row['dataset'] == 'challenge' and row['mechanism'] == 'AMBIGREF':
            if '/t1/' in row['group']:
                row['evidence'] = row['evidence'].replace('was the sole recipient of that medal on that occasion.', 'was the sole recipient of that medal during that entire year.')
                row['evidence'] = row['evidence'].replace('also received that same medal for the same occasion.', 'also received that same medal during that same year.')
            else:
                row['evidence'] = row['evidence'].replace('was the sole recipient of that medal on that occasion.', 'was the only person ever to receive that medal for that documentary.')
                row['evidence'] = row['evidence'].replace('also received that same medal for the same occasion.', 'also received that same medal for that documentary.')
            # All variants get a common scope sentence, avoiding label-dependent amendment status.
            row['evidence'] += ' The medal mentioned throughout is the same award.'
        else:
            continue
        row['supersedes_id'] = row['id']
        row['id'] = 'ctrl_' + hashlib.sha256((row['evidence'] + '\0' + row['claim']).encode()).hexdigest()[:20]
        amended += 1
    assert amended == 48
    return rows
