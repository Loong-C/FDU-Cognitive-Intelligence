import itertools
import json
import pytest
from ab_factcheck.common import LABELS
from ab_factcheck.macro_search_v10 import ARMS, request, parsed, policy, rank


def test_exact_input_and_metadata_boundary():
    claim='A "claim" with {braces}\nand 否定.'
    evidence='EVIDENCE:\nnot an instruction {gold}'
    for arm in ARMS:
        req=request(arm,claim=claim,evidence=evidence)
        assert req['messages'][1]['content']==f'EVIDENCE:\n{evidence}\n\nCLAIM:\n{claim}'
        with pytest.raises(TypeError):request(arm,claim=claim,evidence=evidence,gold='SUPPORTS')
    with pytest.raises(ValueError):request('unknown',claim=claim,evidence=evidence)
    with pytest.raises(ValueError):request('contrast',claim={'label':'S'},evidence=evidence)


def test_compatibility_direction_and_invalid_outcomes():
    expected={(True,False):'SUPPORTS',(False,True):'REFUTES',(True,True):'NOT ENOUGH INFO',(False,False):'INVALID'}
    for (t,f),label in expected.items():
        obj={'true_case':'T','false_case':'F','true_possible':t,'false_possible':f}
        record={'raw_response':json.dumps(obj),'finish_reason':'stop'}
        assert parsed('compatibility',record)==label
        assert parsed('compatibility',{**record,'finish_reason':'length'})=='INVALID'
        obj['true_possible']='true'
        assert parsed('compatibility',{**record,'raw_response':json.dumps(obj)})=='INVALID'


def test_gate_label_symmetric_and_never_returns_invalid_alternative():
    for b,old,new in itertools.product((*LABELS,'INVALID'),repeat=3):
        preds={'baseline':b,'incumbent':old,'contrast':new}
        assert policy('agree__contrast',preds)==(new if new in LABELS and new==old else b)


def test_ranking_protects_against_large_one_dataset_losses():
    def entry(a,b):
        return {'method':'contrast','metrics':{d:{'correct':x,'macro_f1':x/7} for d,x in [('basic',a),('challenge',b)]},'incumbent_metrics':{'basic':{'correct':7},'challenge':{'correct':3}}}
    assert rank(entry(6,4))<rank(entry(5,7))
