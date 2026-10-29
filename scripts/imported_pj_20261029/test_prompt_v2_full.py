import contextlib
import io
import json
import unittest
from unittest.mock import patch

import prompt_v2_full as full
from benchmark import messages_for
from test_baseline import test_area


class V2Tests(unittest.TestCase):
    def test_frozen_full_scope_config_and_input_isolation(self):
        with test_area() as path:
            rows,manifest=full.prepare(path/'run')
            self.assertEqual(len(rows),885)
            self.assertEqual(len({r['id'] for r in rows}),885)
            draft=json.loads((full.DRAFT/'draft-manifest.json').read_text(encoding='utf-8'))
            settings=manifest['settings']
            self.assertEqual(settings['prompt_sha256'],draft['prompt_sha256'])
            self.assertEqual(settings['config'],draft['config_proposal'])
            self.assertEqual(settings['calls_per_sample'],1)
            self.assertFalse(settings['uses_cached_predictions'])
            row=dict(rows[0]);expected=messages_for(row,settings['prompt_template'])
            for k in row:
                if k not in ('evidence','claim'):row[k]='LEAK_SENTINEL'
            self.assertEqual(messages_for(row,settings['prompt_template']),expected)
            self.assertNotIn('LEAK_SENTINEL',json.dumps(expected))

    def test_draft_or_config_tampering_rejected(self):
        with test_area() as path:
            fake=path/'draft';fake.mkdir()
            (fake/'draft-manifest.json').write_bytes((full.DRAFT/'draft-manifest.json').read_bytes())
            (fake/'prompt-v2.txt').write_text('changed',encoding='utf-8')
            with patch.object(full,'DRAFT',fake):
                with self.assertRaises(ValueError):full.prepare(path/'bad')
            config=full.load_config(full.ROOT/'config-4096.json');config['max_tokens']=1024
            with patch.object(full,'load_config',return_value=config):
                with self.assertRaises(ValueError):full.prepare(path/'bad-config')

    def test_execute_fresh_resume_and_comparison_identity(self):
        with test_area() as path:
            out=path/'pipeline';rows,manifest=full.prepare(out)
            small=rows[:4]
            def fake(row,previous,config,key,prompt):
                return {'id':row['id'],'gold':row['label'],'status':'ok','prediction':row['label'],
                        'timestamp':full.stamp(),'evaluation_attempt':1,'latency_seconds':1,'failed_request_attempts':[]}
            with patch.object(full,'evaluate_one',side_effect=fake) as call,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(full.execute(out,small,manifest,'offline-test'),0)
                self.assertEqual(call.call_count,4)
                self.assertEqual(full.execute(out,small,manifest,'offline-test'),0)
                self.assertEqual(call.call_count,4)
            result=json.loads((out/'summary.json').read_text(encoding='utf-8'))
            self.assertTrue(result['complete'])
            self.assertEqual(result['scores']['prompt_v2']['correct'],4)
            for c in result['comparisons'].values():
                t=c['transitions'];self.assertEqual(t['paired_samples'],4)
                self.assertEqual(c['correct_delta'],t['wrong_to_correct']-t['correct_to_wrong'])
            records=full.read_unique(out/'challenge.jsonl')
            self.assertTrue(all(r['prompt_version']=='prompt-v2-frozen' for r in records.values()))

    def test_duplicate_ids_not_silently_accepted(self):
        with test_area() as path:
            p=path/'duplicate.jsonl';p.write_text('{"id":"a"}\n{"id":"a"}\n',encoding='utf-8')
            with self.assertRaises(ValueError):full.read_unique(p)

    def test_failures_remain_in_full_denominator(self):
        with test_area() as path:
            out=path/'failure';rows,manifest=full.prepare(out);small=rows[:3]
            def fake(row,previous,config,key,prompt):
                return {'id':row['id'],'gold':row['label'],'status':'parse_error','prediction':None,
                        'parse_error':'truncated','timestamp':full.stamp(),'evaluation_attempt':1,
                        'latency_seconds':1,'failed_request_attempts':[]}
            with patch.object(full,'evaluate_one',side_effect=fake),contextlib.redirect_stdout(io.StringIO()):
                full.execute(out,small,manifest,'offline-test')
            result=json.loads((out/'summary.json').read_text(encoding='utf-8'))
            score=result['scores']['prompt_v2']
            self.assertEqual(score['count'],3);self.assertEqual(score['accuracy'],0)
            self.assertEqual(score['status_counts']['parse_error'],3)
            self.assertEqual(result['operations']['error_counts']['truncated'],3)


if __name__=='__main__':unittest.main(verbosity=2)
