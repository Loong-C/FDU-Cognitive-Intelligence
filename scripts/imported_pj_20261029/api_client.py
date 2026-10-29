"""远程模型调用；只使用 Python 标准库，不记录密钥和请求头。"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


class APIError(Exception):
    def __init__(self, kind, status=None):
        self.kind, self.status = kind, status
        super().__init__(f"{kind}" + (f" (HTTP {status})" if status else ""))


def load_config(path=None):
    config = json.loads(Path(path or ROOT / 'config.json').read_text(encoding='utf-8-sig'))
    url = urlsplit(config['base_url'])
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('base_url 必须为不含凭据、查询串或片段的 HTTP(S) 地址')
    config['base_url'] = config['base_url'].rstrip('/')
    if config['temperature'] != 0 or config['chat_template_kwargs'].get('enable_thinking') is not False:
        raise ValueError('Baseline 要求 temperature=0、enable_thinking=false')
    if not isinstance(config['max_tokens'], int) or config['max_tokens'] < 1:
        raise ValueError('max_tokens 必须是正整数')
    if config['timeout_seconds'] <= 0 or config['retries'] < 0 or config['retry_delay_seconds'] < 0:
        raise ValueError('超时必须为正数，重试次数和等待时间不得为负数')
    return config


def load_key(env_path=None):
    key = os.environ.get('QWEN_API_KEY', '').strip()
    if key:
        return key
    path = Path(env_path or ROOT / '.env')
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            name, sep, value = line.partition('=')
            if sep and name.strip() == 'QWEN_API_KEY':
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in '\"\'':
                    value = value[1:-1]
                return value.strip()
    return ''


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise APIError('redirect_refused', code)


class Client:
    def __init__(self, config, key):
        self.config, self.key = config, key
        handlers = [NoRedirect()]
        if not config.get('use_environment_proxy', False):
            handlers.append(urllib.request.ProxyHandler({}))
        self.opener = urllib.request.build_opener(*handlers)

    def redact(self, value):
        if isinstance(value, str):
            return value.replace(self.key, '[REDACTED]') if self.key else value
        if isinstance(value, dict):
            return {k: self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        return value

    def request(self, path, payload=None):
        headers = {'Accept': 'application/json'}
        if self.key:
            headers['Authorization'] = 'Bearer ' + self.key
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(
            self.config['base_url'] + path,
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers=headers,
        )
        started = time.perf_counter()
        try:
            with self.opener.open(request, timeout=self.config['timeout_seconds']) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            # 服务端错误正文可能包含敏感信息，只保留状态码。
            status = exc.code
            exc.close()
            raise APIError('http_error', status) from None
        except APIError:
            raise
        except (TimeoutError, OSError, urllib.error.URLError):
            raise APIError('network_error') from None
        except (ValueError, UnicodeError):
            raise APIError('invalid_json_response') from None
        if not isinstance(data, dict):
            raise APIError('invalid_response_shape')
        return self.redact(data), time.perf_counter() - started

    def models(self):
        data, elapsed = self.request('/models')
        if not isinstance(data.get('data'), list):
            raise APIError('invalid_models_response')
        return [m['id'] for m in data['data'] if isinstance(m, dict) and isinstance(m.get('id'), str)], elapsed

    def chat(self, messages):
        c = self.config
        payload = {'model': c['model'], 'messages': messages, 'temperature': c['temperature'],
                   'max_tokens': c['max_tokens'], 'stream': False,
                   'chat_template_kwargs': c['chat_template_kwargs']}
        started = time.perf_counter()
        failures = []
        for attempt in range(c['retries'] + 1):
            try:
                data, _ = self.request('/chat/completions', payload)
                return data, time.perf_counter() - started, failures
            except APIError as exc:
                failures.append({'kind': exc.kind, 'http_status': exc.status})
                retryable = exc.kind == 'network_error' or exc.status in (408, 429, 500, 502, 503, 504)
                if not retryable or attempt == c['retries']:
                    exc.failures = failures
                    exc.elapsed = time.perf_counter() - started
                    raise
                time.sleep(c['retry_delay_seconds'] * (2 ** attempt))
        raise AssertionError('unreachable')
