"""Read-only validation audit; run with the isolated Python and CANN env sourced.

This never generates answers or scores the development holdout.
"""
from collections import Counter
import json
from pathlib import Path
import sys

base=Path('/root/ab_finetune27b_20261030')
sys.path.insert(0,str(base/'revision_2_formal_workspace/src'))
from ab_factcheck import finetune27b_v2 as c
from ab_factcheck import finetune27b_engine as engine
from transformers import AutoTokenizer

p=c.verify_training()
directory=base/'revision_2_runs/formal/validation/baseline'
data=c.rows(c.ROOT/c.EXP/'validation.jsonl')
if len(list(directory.glob('*_e_*.json'))) != len(data):
    print(json.dumps({'ready':False,'expected':len(data)}))
    raise SystemExit(0)
identity=c.read_json(directory/'identity.json')
expected={'training_freeze_sha256':c.sha(c.ROOT/c.EXP/'training_freeze.json'),
          'environment':c.read_json(base/'revision_2_runs/formal/smoke/receipt.json')['environment'],
          'generation':p['generation'],'phase':'validation'}
if identity != expected:
    raise ValueError('Validation baseline identity mismatch')
tokenizer=AutoTokenizer.from_pretrained(base/'models/Qwen3.8-27B',local_files_only=True,trust_remote_code=False)
statuses=Counter()
invalid=thinking=missing=0
for row in data:
    result=c.read_json(directory/(c.record_key(row)+'.json'))
    prefix=engine.encode(row,tokenizer,p,require_target=False,enforce_limit=False)['prefix']
    if (result['identity'] != c.digest(identity)
            or result['input_sha256'] != c.digest(c.messages(row,p['prompt']))
            or result['input_token_sha256'] != c.digest(prefix)):
        raise ValueError('Validation input/identity mismatch')
    raw=result.get('raw_text','').lower()
    generated_thinking='<think' in raw or '</think' in raw
    prediction='INVALID' if generated_thinking else c.parse(result['text'],result['finished'])
    if result['prediction'] != prediction:
        raise ValueError('Stored prediction differs from received answer')
    statuses[result['status']]+=1
    invalid+=prediction == 'INVALID'
    thinking+=generated_thinking
    missing+=not result.get('reason_present',False)
receipt={'passed':True,'rows':len(data),'datasets':dict(Counter(r['dataset'] for r in data)),
         'input_token_hashes_recomputed':True,'received_answer_parse_verified':True,
         'statuses':dict(statuses),'invalid':invalid,'thinking_generated':thinking,
         'missing_reason':missing,'answers_retried_or_modified':False,
         'validation_identity_sha256':c.sha(directory/'identity.json')}
c.save(base/'revision_2_runs/formal/validation_baseline_integrity.json',receipt)
print(json.dumps(receipt))
