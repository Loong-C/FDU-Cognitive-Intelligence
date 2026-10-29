import json
import math
import httpx
import pytest
from ab_factcheck.common import LABELS
from ab_factcheck.intranet_client import Client, MODEL, ServerStop
from ab_factcheck.server_search_v11 import request, parse, prediction, CHOICES, MAPS, FLIP


def record(letter,probs):
    return {'raw_response':letter,'provider_validation_issues':[],'finish_reason':'stop',
        'response_json':{'choices':[{'logprobs':{'content':[{'token':letter,'top_logprobs':[{'token':k,'logprob':math.log(v)} for k,v in zip('ABC',probs)]}]}}]}}


def test_choice_mapping_rotation_and_polarity():
    for index in range(3):
        for j,label in enumerate(MAPS[index]):
            probs=[.1,.1,.1];probs[j]=.8
            pred,p=parse('pos'+str(index),record('ABC'[j],probs))
            assert pred==label and max(p,key=p.get)==label
    for label in LABELS:
        values={a:('unused',{l:(.8 if l==(FLIP[label] if a.startswith('neg') else label) else .1) for l in LABELS}) for a in CHOICES}
        assert prediction('signed_pool',values)==label
        assert prediction('neg_pool',values)==label


def test_missing_logprobs_is_invalid_not_fabricated_confidence():
    r=record('A',[.8,.1,.1]);r['response_json']['choices'][0]['logprobs']['content'][0]['top_logprobs'].pop()
    assert parse('pos0',r)==('INVALID',None)
    assert prediction('pos_pool',{a:('INVALID',None) for a in CHOICES})=='INVALID'


def test_input_boundary_and_nonthinking():
    c='A {claim} "X"';e='E\n中'
    for arm in ('baseline','nli','contrast','normalize','negative',*CHOICES):
        p=request(arm,claim=c,evidence=e)
        assert p['model']==MODEL and p['chat_template_kwargs']=={'enable_thinking':False}
        assert e in p['messages'][1]['content']
        with pytest.raises(TypeError):request(arm,claim=c,evidence=e,gold='SUPPORTS')


def test_cache_and_auth_are_separate(tmp_path):
    attempts=[]
    def handle(req):
        assert req.headers['authorization']=='Bearer private-test-key'
        attempts.append(1)
        return httpx.Response(200,json={'model':MODEL,'choices':[{'message':{'content':'A','reasoning':None},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}})
    c=Client(key='private-test-key',transport=httpx.MockTransport(handle));p=request('pos0',claim='C',evidence='E');path=tmp_path/'r.json'
    first=c.receive(path,p,'freeze');assert c.receive(path,p,'freeze')==first
    assert len(attempts)==1 and 'private-test-key' not in path.read_text()
    c.close()


def test_ambiguous_timeout_never_retried(tmp_path):
    calls=[]
    def handle(req):calls.append(1);raise httpx.ReadTimeout('unknown outcome')
    c=Client(key='private-test-key',transport=httpx.MockTransport(handle));path=tmp_path/'r.json';p=request('pos0',claim='C',evidence='E')
    with pytest.raises(ServerStop):c.receive(path,p,'freeze')
    assert path.with_suffix('.inflight').exists()
    with pytest.raises(ServerStop):c.receive(path,p,'freeze')
    assert len(calls)==1
    c.close()
