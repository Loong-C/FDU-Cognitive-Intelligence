"""User-authorized intranet endpoint; immutable receipts and no ambiguous retries."""
import json
import os
from pathlib import Path
import time

import httpx

from .common import atomic_json, frozen_json, now
from .macro_v7.inference import digest
from .model_client import nonthinking_check

ENDPOINT = 'http://10.176.30.103:20027/v1'
MODEL = 'qwen38-27b'
KEY_FILE = 'C:/Users/hp/Documents/WeChat Files/wxid_f369scgx0twr12/FileStorage/File/2026-10/key.txt'


def key_value():
    key = os.getenv('QWEN_API_KEY', '').strip() or Path(os.getenv('QWEN_API_KEY_FILE', KEY_FILE)).read_text(encoding='utf-8-sig').strip()
    if not key or '\n' in key or '\r' in key: raise ValueError('Invalid server credential format')
    return key


class ServerStop(RuntimeError):
    pass


class Client:
    def __init__(self, *, key=None, transport=None):
        self.key = key if key is not None else key_value()
        self.http = httpx.Client(base_url=ENDPOINT+'/', trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(180, connect=15), transport=transport)

    def close(self):
        self.http.close()

    def receive(self, path, payload, freeze_hash):
        if payload.get('model') != MODEL or payload.get('chat_template_kwargs') != {'enable_thinking':False} or payload.get('stream') is not False:
            raise ServerStop('Model or nonthinking request mismatch')
        if path.exists():
            r = json.loads(path.read_text(encoding='utf-8'))
            assert r['record_sha256'] == digest({k:v for k,v in r.items() if k != 'record_sha256'})
            assert r['request_payload'] == payload and r['freeze_sha256'] == freeze_hash
            return r
        inflight=path.with_suffix('.inflight')
        if inflight.exists():raise ServerStop('Ambiguous unfinished request; no automatic resend')
        frozen_json(inflight, {'request_sha256':digest(payload), 'started':now()})
        attempts=[]
        for i in range(3):
            attempt={'requested_at':now()};attempts.append(attempt);start=time.perf_counter()
            try:
                response=self.http.post('chat/completions',headers={'Authorization':'Bearer '+self.key},json=payload)
            except httpx.TransportError as exc:
                definite=isinstance(exc,(httpx.ConnectError,httpx.ConnectTimeout,httpx.PoolTimeout))
                attempt.update(error_type=type(exc).__name__,ambiguous=not definite)
                atomic_json(path.with_suffix('.error.json'),{'attempts':attempts})
                if not definite:raise ServerStop('Ambiguous transport; receipt retained') from None
                if i==2:
                    inflight.unlink();raise ServerStop('Bounded connection retries exhausted') from None
                time.sleep(2**i);continue
            attempt.update(http_status=response.status_code,responded_at=now(),latency=time.perf_counter()-start)
            if response.status_code != 200:
                attempt['body']=response.text[:2000].replace(self.key,'[REDACTED]')
                atomic_json(path.with_suffix('.error.json'),{'attempts':attempts})
                if response.status_code in (429,500,502,503,504) and i<2:
                    delay=response.headers.get('retry-after','2')
                    try:delay=float(delay)
                    except ValueError:delay=2
                    if delay<=60:time.sleep(max(delay,2**i));continue
                inflight.unlink();raise ServerStop('HTTP '+str(response.status_code)+'; response retained')
            try:body=response.json()
            except ValueError:raise ServerStop('Unparseable received response; no resend') from None
            body=json.loads(json.dumps(body,ensure_ascii=False).replace(self.key,'[REDACTED]'))
            check=nonthinking_check(body)
            choice=body.get('choices',[{}])[0]; usage=body.get('usage',{})
            issues=[]
            if body.get('model') != MODEL:issues.append('MODEL_MISMATCH')
            if not check['passed']:issues.append('THINKING_OBSERVED')
            if len(body.get('choices',[]))!=1:issues.append('CHOICE_COUNT')
            if not isinstance(choice.get('message',{}).get('content'),str):issues.append('MISSING_CONTENT')
            if not all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens','total_tokens')):issues.append('BAD_USAGE')
            elif usage['prompt_tokens']+usage['completion_tokens']!=usage['total_tokens']:issues.append('BAD_USAGE_SUM')
            r={'request_payload':payload,'freeze_sha256':freeze_hash,'requested_at':attempts[0]['requested_at'],
                'response_json':body,'raw_response':choice.get('message',{}).get('content'),'finish_reason':choice.get('finish_reason'),
                'actual_model_id':body.get('model'),'system_fingerprint':body.get('system_fingerprint'),
                'usage':usage,'nonthinking_validation':check,'provider_validation_issues':issues,'attempts':attempts}
            r['record_sha256']=digest(r);frozen_json(path,r);inflight.unlink()
            if issues:raise ServerStop('Provider validation failure; received record retained')
            return r
        raise ServerStop('No response')
