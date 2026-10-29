import json

from ab_factcheck.semantic_binary_v14 import request, decide, parse, SCHEMA


def test_direct_contradiction_keeps_original_hypothesis_and_nonthinking():
    p=request('direct_contrad',claim='Original hypothesis.',evidence='Given premise.')
    assert p['messages'][1]['content']=='PREMISE:\nGiven premise.\n\nHYPOTHESIS:\nOriginal hypothesis.'
    assert p['chat_template_kwargs']=={'enable_thinking':False} and p['max_tokens']==4
    assert p['structured_outputs']=={'choice':['A','B']}


def test_proof_pair_all_states_and_invalid_fallback():
    p={'baseline':'REFUTES','nli':'SUPPORTS'}
    for a,b,label in [(True,False,'SUPPORTS'),(False,True,'REFUTES'),(False,False,'NOT ENOUGH INFO'),(True,True,'SUPPORTS'),(None,False,'SUPPORTS')]:
        assert decide('proof_pair',p|{'proof_entail':a,'proof_contrad':b})==label
    assert decide('proof_gate',p|{'proof_entail':False,'proof_contrad':False})=='REFUTES'


def test_proof_schema_does_not_coerce_invalid_answer():
    r={'finish_reason':'stop','provider_validation_issues':[],'raw_response':json.dumps({'justification':'A brief explanation.','answer':'YES'})}
    assert parse('proof_entail',r) is True
    r['raw_response']=json.dumps({'justification':'A brief explanation.','answer':True})
    assert parse('proof_entail',r) is None
