"""评分边界、输入隔离、断点续跑与HTTP重试的离线校验。"""
import argparse
import contextlib
import copy
import io
import json
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import baseline_eval
from api_client import APIError, Client, ROOT, load_config, load_key
from benchmark import LABELS, grouped_scores, messages_for, parse_response, read_sources, sample_rows, score


def response(content='理由。\nVerdict: SUPPORTS', finish='stop', **message):
    return {'choices': [{'finish_reason': finish, 'message': {'content': content, **message}}]}


@contextlib.contextmanager
def test_area():
    # Windows上的TemporaryDirectory私有ACL会挡住受限运行账户，使用普通继承权限。
    path = ROOT / 'work' / ('test-' + uuid.uuid4().hex)
    path.mkdir(parents=True)
    yield path


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.datasets, cls.prompt, cls.audit = read_sources()

    def test_original_data_and_prompt(self):
        self.assertEqual([len(self.datasets[k]) for k in ('challenge', 'basic')], [885, 900])
        self.assertEqual(self.audit['cross_dataset_group_overlap'], 0)
        self.assertEqual(self.audit['cross_dataset_id_overlap'], 0)
        self.assertEqual(self.audit['challenge']['duplicate_input_count'], 0)
        self.assertEqual(self.audit['basic']['duplicate_input_count'], 0)

    def test_messages_never_use_management_or_gold(self):
        row = dict(self.datasets['challenge'][0])
        before = messages_for(row, self.prompt)
        for key in list(row):
            if key not in ('evidence', 'claim'):
                row[key] = 'LEAK_SENTINEL'
        self.assertEqual(before, messages_for(row, self.prompt))
        self.assertNotIn('LEAK_SENTINEL', json.dumps(before))
        self.assertEqual(before[0]['content'], 'You are a meticulous professional fact-checker.')

    def test_placeholder_in_evidence_is_not_replaced_again(self):
        row = {'evidence': 'literal {claim} and {evidence}', 'claim': 'CLAIM_VALUE'}
        text = messages_for(row, self.prompt)[1]['content']
        self.assertIn('literal {claim} and {evidence}', text)
        self.assertEqual(text.count('CLAIM_VALUE'), 1)

    def test_sampling_repeatable_and_covers_mechanisms(self):
        rows = self.datasets['challenge']
        chosen = sample_rows(rows, 20, 20261027)
        self.assertEqual(chosen, sample_rows(rows, 20, 20261027))
        self.assertEqual(len({r['id'] for r in chosen}), 20)
        self.assertEqual(len({r['mechanism'] for r in chosen}), 7)
        self.assertEqual({r['label'] for r in chosen}, set(LABELS))
        with self.assertRaises(ValueError):
            sample_rows(rows, 0, 1)

    def test_parser_requires_exact_final_line(self):
        for label in LABELS:
            self.assertEqual(parse_response(response('理由\nVerdict: ' + label))[0], label)
        for text in ('SUPPORTS', 'Verdict: supports', 'Verdict: SUPPORTS\n附言', 'Verdict: REFUTES 或 SUPPORTS', ''):
            self.assertIsNone(parse_response(response(text))[0])

    def test_truncation_reasoning_and_bad_shape(self):
        self.assertEqual(parse_response(response(finish='length'))[1], 'truncated')
        self.assertEqual(parse_response(response(reasoning_content='reasoning'))[1], 'thinking_not_disabled')
        self.assertEqual(parse_response({'choices': []})[1], 'invalid_response_shape')
        self.assertEqual(parse_response(response(content=None))[1], 'non_text_content')

    def test_metrics_keep_failures_and_pending_in_denominator(self):
        rows = [{'id': str(i), 'label': label} for i, label in enumerate((LABELS[0], LABELS[0], LABELS[1], LABELS[2], LABELS[2]))]
        records = {
            '0': {'status': 'ok', 'prediction': LABELS[0], 'latency_seconds': 1},
            '1': {'status': 'ok', 'prediction': LABELS[1], 'latency_seconds': 2},
            '2': {'status': 'parse_error', 'prediction': None, 'latency_seconds': 3},
            '3': {'status': 'request_error', 'prediction': None, 'latency_seconds': 4},
        }
        m = score(rows, records)
        self.assertEqual(m['accuracy'], 1 / 5)
        self.assertEqual(m['accuracy_on_valid_only'], 1 / 2)
        self.assertEqual(m['per_class'][LABELS[0]]['recall'], 1 / 2)
        self.assertEqual(m['per_class'][LABELS[0]]['f1'], 2 / 3)
        self.assertEqual(m['macro_f1'], 2 / 9)
        self.assertEqual(m['parse_failure_rate'], 1 / 4)
        self.assertEqual(m['request_failure_rate'], 1 / 4)
        self.assertEqual(m['confusion_matrix'][LABELS[2]]['PENDING'], 1)
        self.assertEqual(sum(sum(r.values()) for r in m['confusion_matrix'].values()), 5)

    def test_no_nei_support_is_not_zero_recall(self):
        self.assertIsNone(score([{'id': 'x', 'label': LABELS[0]}], {})['per_class'][LABELS[2]]['recall'])

    def test_grouped_total_matches_data(self):
        rows = self.datasets['challenge']
        m = grouped_scores(rows, {})
        self.assertEqual(sum(v['count'] for v in m['by_mechanism'].values()), 885)
        self.assertEqual(sum(v['count'] for v in m['by_evidence_condition'].values()), 885)

    def test_local_key_quotes_and_env_priority(self):
        with test_area() as temp:
            path = Path(temp) / '.env'
            path.write_text('QWEN_API_KEY="local-test-key"\n', encoding='utf-8')
            with patch.dict('os.environ', {'QWEN_API_KEY': ''}):
                self.assertEqual(load_key(path), 'local-test-key')
            with patch.dict('os.environ', {'QWEN_API_KEY': 'env-test-key'}):
                self.assertEqual(load_key(path), 'env-test-key')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.payloads, self.mode = 0, [], 'ok'
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if owner.mode == 'redirect':
                    self.send_response(302)
                    self.send_header('Location', '/other')
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'data': [{'id': 'qwen38-27b'}]}).encode())

            def do_POST(self):
                owner.calls += 1
                owner.payloads.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                if owner.mode == 'unauthorized' or owner.mode == 'retry' and owner.calls == 1:
                    self.send_response(401 if owner.mode == 'unauthorized' else 503)
                    self.end_headers()
                    self.wfile.write(b'not logged mock-secret-test')
                    return
                self.send_response(200)
                self.end_headers()
                body = response('mock-secret-test\nVerdict: SUPPORTS')
                self.wfile.write(json.dumps(body).encode())

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = load_config()
        self.config.update(base_url=f'http://127.0.0.1:{self.server.server_port}', retries=1, retry_delay_seconds=0)
        self.client = Client(self.config, 'mock-secret-test')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_http_payload_redaction_and_no_label_leak(self):
        data, _, failures = self.client.chat([{'role': 'user', 'content': 'example'}])
        self.assertNotIn('mock-secret-test', json.dumps(data))
        self.assertEqual(failures, [])
        self.assertEqual(self.payloads[0]['chat_template_kwargs'], {'enable_thinking': False})
        self.assertEqual(set(self.payloads[0]), {'model', 'messages', 'temperature', 'max_tokens', 'stream', 'chat_template_kwargs'})

    def test_retry_transient_failure(self):
        self.mode = 'retry'
        _, _, failures = self.client.chat([])
        self.assertEqual(self.calls, 2)
        self.assertEqual(failures, [{'kind': 'http_error', 'http_status': 503}])

    def test_no_retry_on_auth_error_or_redirect(self):
        self.mode = 'unauthorized'
        with self.assertRaises(APIError) as caught:
            self.client.chat([])
        self.assertEqual(self.calls, 1)
        self.assertNotIn('mock-secret-test', str(caught.exception))
        self.mode = 'redirect'
        with self.assertRaises(APIError) as caught:
            self.client.models()
        self.assertEqual(caught.exception.kind, 'redirect_refused')

    def test_pipeline_resume_and_config_mismatch(self):
        with test_area() as temp:
            args = argparse.Namespace(dataset='all', limit=2, phase='smoke', seed=20261027,
                                      out=str(temp), resume=False, retry_failed=False)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(baseline_eval.run(args, self.config, 'mock-secret-test'), 0)
                self.assertEqual(self.calls, 4)
                args.resume = True
                self.assertEqual(baseline_eval.run(args, self.config, 'mock-secret-test'), 0)
            self.assertEqual(self.calls, 4)
            summary = json.loads((Path(temp) / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(set(summary['datasets']), {'challenge', 'basic'})
            changed = copy.deepcopy(self.config)
            changed['max_tokens'] += 1
            with self.assertRaises(ValueError):
                baseline_eval.run(args, changed, 'mock-secret-test')


if __name__ == '__main__':
    unittest.main(verbosity=2)
