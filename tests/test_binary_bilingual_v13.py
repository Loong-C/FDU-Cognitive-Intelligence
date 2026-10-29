import json
import math
import pytest
from ab_factcheck.binary_bilingual_v13 import request,parse,prediction
from ab_factcheck.negation_v8.inference import negate


def test_exact_input_boundary_and_no_gold():
    c='Quoted "C" {x}\nA and B.';e='Original E\nunchanged.'
    for a in ('binary_pos','binary_neg','zh_nli'):
        r=request(a,claim=c,evidence=e)
        assert r['chat_template_kwargs']=={'enable_thinking':False}
        assert e in r['messages'][1]['content']
        with pytest.raises(TypeError):request(a,claim=c,evidence=e,label='SUPPORTS')
    assert request('binary_neg',claim=c,evidence=e)['messages'][1]['content']==f'PREMISE:\n{e}\n\nHYPOTHESIS:\n{negate(c)}'


def test_symmetric_threshold_all_four_cases_and_invalid():
    for method in ('binary_50','binary_65','binary_80','binary_90'):
        for a,b,expected in [(1,0,'SUPPORTS'),(0,1,'REFUTES'),(0,0,'NOT ENOUGH INFO'),(1,1,'fallback'),(None,1,'fallback')]:
            assert prediction(method,{'binary_pos':a,'binary_neg':b,'nli':'fallback'})==expected
    assert prediction('binary_80',{'binary_pos':.8,'binary_neg':.79,'nli':'fallback'})=='SUPPORTS'


def test_probability_requires_both_real_token_scores():
    r={'finish_reason':'stop','provider_validation_issues':[],'raw_response':'A','response_json':{'choices':[{'logprobs':{'content':[{'token':'A','top_logprobs':[{'token':'A','logprob':math.log(.8)},{'token':'B','logprob':math.log(.2)}]}]}}]}}
    assert abs(parse('binary_pos',r)-.8)<1e-12
    r['response_json']['choices'][0]['logprobs']['content'][0]['top_logprobs'].pop()
    assert parse('binary_pos',r) is None
