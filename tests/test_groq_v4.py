import copy
import json

import httpx
import pytest

from ab_factcheck.common import ROOT
from ab_factcheck.groq_client import GroqModelClient, GroqStop, duration
from ab_factcheck.groq_v4 import load_config, Experiment
from ab_factcheck.model_client import validate_endpoint
from ab_factcheck.structured import response_format_for, parse_structured


class Clock:
    def __init__(self): self.t = 100000.0
    def __call__(self): return self.t
    def sleep(self, n): self.t += n


def body(content=None):
    return {'model': 'qwen/qwen3.8-27b', 'choices': [{'message': {'content': content or '{"verdict":"SUPPORTS","reason":"yes"}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}, 'system_fingerprint': 'fp_test'}


@pytest.fixture
def config():
    return load_config(ROOT / 'configs/experiment_groq_27b_v4.json')


def make(tmp_path, monkeypatch, config, handler, clock=None):
    monkeypatch.setenv('GROQ_API_KEY', 'unit-test-secret-not-real')
    clock = clock or Clock()
    return GroqModelClient(config['model'], tmp_path / 'quota.json', free_plan_confirmed=True,
        transport=httpx.MockTransport(handler), clock=clock, sleeper=clock.sleep)


def test_fixed_origin_payload_and_redaction(tmp_path, monkeypatch, config):
    def handler(req):
        assert str(req.url) == 'https://api.groq.com/openai/v1/chat/completions'
        payload = json.loads(req.content)
        assert set(payload) == {'model','messages','temperature','seed','reasoning_effort','stream','max_completion_tokens','response_format'}
        assert payload['reasoning_effort'] == 'none'
        return httpx.Response(200, json=body())
    c = make(tmp_path, monkeypatch, config, handler)
    r = c.complete([{'role':'user','content':'fiction'}], response_format=response_format_for('A2'))
    assert not r['provider_validation_issues']
    assert c.ledger()['attempts'][0]['charged_tokens'] == 120
    assert 'unit-test-secret' not in json.dumps(r) + (tmp_path/'quota.json').read_text()
    with pytest.raises(ValueError): validate_endpoint('https://api.groq.com/v1')


@pytest.mark.parametrize('status', [400,401,403,302])
def test_terminal_http_no_retry_and_redacted(tmp_path, monkeypatch, config, status):
    calls=[]
    def handler(req):
        calls.append(1)
        return httpx.Response(status, json={'error':{'type':'denied','message':'unit-test-secret-not-real org_private'}})
    c=make(tmp_path,monkeypatch,config,handler)
    with pytest.raises(GroqStop): c.complete([])
    assert len(calls)==1
    assert 'unit-test-secret' not in (tmp_path/'quota.json').read_text()
    assert 'org_private' not in (tmp_path/'quota.json').read_text()


def test_429_retry_after_and_usage(tmp_path, monkeypatch, config):
    clock=Clock(); times=[]
    def handler(req):
        times.append(clock())
        if len(times)==1: return httpx.Response(429,headers={'retry-after':'12'},json={'error':{'type':'rate_limit'}})
        return httpx.Response(200,json=body())
    c=make(tmp_path,monkeypatch,config,handler,clock)
    r=c.complete([])
    assert times[1]-times[0]>=12
    assert r['completion_request_attempts']==2
    assert len(c.ledger()['attempts'])==2


def test_long_reset_persists_pause(tmp_path, monkeypatch, config):
    c=make(tmp_path,monkeypatch,config,lambda req:httpx.Response(429,headers={'retry-after':'3600'},json={}))
    with pytest.raises(GroqStop): c.complete([])
    assert c.ledger()['blocked_until'] > c.clock()
    with pytest.raises(GroqStop): c.complete([])
    assert len(c.ledger()['attempts'])==1


def test_budget_stops_before_network_and_survives_restart(tmp_path, monkeypatch, config):
    config['model']['budget']['requests_24h']=1
    c=make(tmp_path,monkeypatch,config,lambda req:httpx.Response(200,json=body()))
    c.complete([])
    again=make(tmp_path,monkeypatch,config,lambda req:pytest.fail('network must not run'))
    with pytest.raises(GroqStop): again.complete([])


def test_retries_bounded(tmp_path, monkeypatch, config):
    c=make(tmp_path,monkeypatch,config,lambda req:httpx.Response(503,json={}))
    with pytest.raises(GroqStop): c.complete([])
    assert len(c.ledger()['attempts'])==3


def test_nonthinking_and_model_mismatch_saved(tmp_path, monkeypatch, config):
    b=body(); b['model']='wrong'; b['choices'][0]['message']['reasoning']='hidden thought'
    b['usage']['completion_tokens_details']={'reasoning_tokens':2}
    c=make(tmp_path,monkeypatch,config,lambda req:httpx.Response(200,json=b))
    r=c.complete([])
    assert not r['nonthinking_validation']['passed']
    assert 'model_identity_mismatch' in r['provider_validation_issues']


def test_refuse_paid_or_missing_key(tmp_path, monkeypatch, config):
    monkeypatch.delenv('GROQ_API_KEY',raising=False)
    with pytest.raises(GroqStop): GroqModelClient(config['model'],tmp_path/'q')
    with pytest.raises(GroqStop): GroqModelClient(config['model'],tmp_path/'q',free_plan_confirmed=True)


def test_resume_no_regeneration_and_ambiguous_crash(tmp_path, monkeypatch, config):
    c=make(tmp_path,monkeypatch,config,lambda req:httpx.Response(200,json=body()))
    e=Experiment(config,c); e.directory=tmp_path/'run'; e.initialize()
    r=e.item('challenge','A2',e.rows['challenge'][0])
    r2=e.item('challenge','A2',e.rows['challenge'][0])
    assert r==r2 and len(c.ledger()['attempts'])==1
    (e.directory/'unknown.inflight').write_text('{}')
    with pytest.raises(GroqStop,match='Ambiguous'): e.receive('unknown.json',[],None)
    e.fp_hash='changed'
    with pytest.raises(GroqStop,match='differs'): e.item('challenge','A2',e.rows['challenge'][0])


def test_strict_invalid_logic_not_repaired():
    p=parse_structured('{"true_world":"IMPOSSIBLE","false_world":"IMPOSSIBLE","true_reason":"x","false_reason":"y"}','B2','stop')
    assert p['protocol_valid'] and p['derived_label']=='INVALID_LOGIC' and p['predicted_label'] is None
    assert not parse_structured('{"verdict":"SUPPORTS","reason":"x","extra":1}','A2','stop')['protocol_valid']


def test_duration():
    assert duration('2m59.56s')==179.56
    assert duration('1h2m3s')==3723
    assert duration('bad')==0


def test_rolling_budget_resets_after_24h(tmp_path, monkeypatch, config):
    config['model']['budget']['requests_24h']=1
    clock=Clock()
    c=make(tmp_path,monkeypatch,config,lambda req:httpx.Response(200,json=body()),clock)
    c.complete([])
    clock.t += 86401
    c.complete([])
    assert len(c.ledger()['attempts'])==2


def test_server_remaining_token_reset_throttles(tmp_path, monkeypatch, config):
    clock=Clock(); times=[]
    def handler(req):
        times.append(clock())
        return httpx.Response(200,headers={'x-ratelimit-remaining-tokens':'0','x-ratelimit-reset-tokens':'20s'},json=body())
    c=make(tmp_path,monkeypatch,config,handler,clock)
    c.complete([]); c.complete([])
    assert times[1]-times[0]>=20


def test_bad_answer_is_retained_not_retried(tmp_path, monkeypatch, config):
    c=make(tmp_path,monkeypatch,config,lambda req:httpx.Response(200,json=body('not JSON')))
    e=Experiment(config,c); e.directory=tmp_path/'run'; e.initialize()
    result=e.item('challenge','A2',e.rows['challenge'][0])
    assert result['parse_status']=='invalid'
    e.item('challenge','A2',e.rows['challenge'][0])
    assert len(c.ledger()['attempts'])==1


def test_independent_parser_detects_mapping_and_duplicate():
    from ab_factcheck.reporting_groq import independent_parse
    r={'arm':'B2','finish_reason':'stop','raw_response':'{"true_world":"POSSIBLE","false_world":"IMPOSSIBLE","true_reason":"ok","false_reason":"conflict"}'}
    assert independent_parse(r)==(True, True, 'SUPPORTS')
    r={'arm':'A2','finish_reason':'stop','raw_response':'{"verdict":"SUPPORTS","verdict":"REFUTES","reason":"x"}'}
    assert independent_parse(r)==(False, None, None)


def test_blocked_report_never_presents_complete_scores(tmp_path, config):
    from ab_factcheck.reporting_groq import report
    config=copy.deepcopy(config)
    # pytest basetemp is inside ignored outputs; keep report sandbox there as well.
    config['report_root']=str((tmp_path/'reports').relative_to(ROOT))
    e=Experiment(config); e.directory=tmp_path/'run'; e.initialize(); e.export()
    receipt=report(e)
    assert receipt['record_count']==0 and receipt['status']=='blocked_or_partial'
    for d in ('challenge','basic'):
        for a in ('A2','B2'):
            assert receipt['datasets'][d]['arms'][a]['accuracy'] is None
            assert receipt['datasets'][d]['arms'][a]['completed']==0
