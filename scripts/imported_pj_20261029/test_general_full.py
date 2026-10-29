"""验证失败恢复不会按答案正误筛选或覆盖有效预测。"""
import unittest
from general_full import recovery_targets, merged_records


class RecoveryTests(unittest.TestCase):
    def test_only_network_failures_selected(self):
        rows = [{'id': i} for i in ['valid', 'network', 'parse', 'auth']]
        records = {'valid': {'status': 'ok', 'prediction': 'REFUTES'},
                   'network': {'status': 'request_error', 'error_kind': 'network_error'},
                   'parse': {'status': 'parse_error'},
                   'auth': {'status': 'request_error', 'error_kind': 'http_error'}}
        self.assertEqual([r['id'] for r in recovery_targets(rows, records)], ['network'])

    def test_failed_recovery_preserves_original(self):
        primary = {'a': {'status': 'request_error', 'prediction': None}}
        retry = {'a': {'status': 'parse_error', 'prediction': None}}
        self.assertEqual(merged_records(primary, retry), primary)

    def test_valid_recovery_is_used_without_gold_selection(self):
        primary = {'a': {'status': 'request_error', 'prediction': None},
                   'b': {'status': 'ok', 'prediction': 'SUPPORTS'}}
        retry = {'a': {'status': 'ok', 'prediction': 'REFUTES', 'gold': 'NOT ENOUGH INFO'}}
        result = merged_records(primary, retry)
        self.assertEqual(result['a']['prediction'], 'REFUTES')
        self.assertEqual(result['b'], primary['b'])
        self.assertIsNone(primary['a']['prediction'])


if __name__ == '__main__':
    unittest.main()
