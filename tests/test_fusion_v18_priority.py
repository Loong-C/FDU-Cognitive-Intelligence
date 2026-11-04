from pathlib import Path
from types import SimpleNamespace

import pytest

from ab_factcheck import finetune27b_v2 as c, fusion_v18 as f
from ab_factcheck import fusion_v18_priority as priority
from ab_factcheck import fusion_v18_run as run


def test_priority_covers_all_old_methods_without_changing_recipes():
    p = f.verify()
    steps = priority.stages(p)
    assert list(steps) == ['seed42', 'three_seeds', 'direct_all', 'fusion_all']
    assert steps['seed42'] == {'direct': ['base_a0', 'old_a0_42', 'old_np_42'], 'fusion': []}
    assert len(steps['three_seeds']['direct']) == 7
    selected = priority.subset(p, 'fusion_all')
    assert len(selected['direct']) == 16 and len(selected['fusion']) == 10
    assert not any(a.startswith('distill_') for a in selected['direct'])
    for kind in ('direct', 'fusion'):
        for name, recipe in selected[kind].items():
            assert recipe == p[kind][name]
    assert len(p['direct']) == 25 and len(p['fusion']) == 37


def test_priority_calls_original_functions_and_restores_catalogue(monkeypatch):
    p = f.verify()
    rt = SimpleNamespace(p=p, args=SimpleNamespace(part='validation', arm='base_a0'))
    observed = []
    monkeypatch.setattr(run, 'direct', lambda rt: observed.append(('direct', rt.args.arm)))
    monkeypatch.setattr(run, 'fusion', lambda rt: observed.append(('fusion', list(rt.p['fusion']))))
    priority.execute(rt, 'seed42')
    assert observed == [('direct', a) for a in priority.stages(p)['seed42']['direct']]
    observed.clear()
    priority.execute(rt, 'fusion_all')
    assert observed[-1] == ('fusion', priority.stages(p)['fusion_all']['fusion'])
    assert rt.p is p and len(rt.p['fusion']) == 37


def test_stage_report_requires_complete_rows_and_never_recommends(tmp_path, monkeypatch):
    p = f.verify()
    monkeypatch.setattr(priority, 'verify', lambda: ({}, p))
    # Tiny isolated balanced rows keep this report test independent of benchmark labels.
    rows = [dict(dataset=d, id=str(i), group=d, mechanism='synthetic', label=label,
                 evidence='Synthetic evidence.', claim='Synthetic claim.')
            for d in ('basic', 'challenge') for i, label in enumerate(c.LABELS)]
    monkeypatch.setattr(f, 'data', lambda part: rows if part == 'validation' else (_ for _ in ()).throw(AssertionError('Unexpected partition')))
    selected = priority.subset(p, 'seed42')
    prompts = c.read_json(f.ROOT / f.EXP / 'prompts.json')
    for arm, spec in selected['direct'].items():
        for row in rows:
            key = c.record_key(row)
            # Fusion repairs one wrong incumbent prediction and has one invalid output.
            pred = row['label']
            if arm == 'old_a0_42' and row['id'] == '0': pred = 'REFUTES'
            finished = not (arm == 'old_np_42' and row['dataset'] == 'basic' and row['id'] == '1')
            text = 'A reason.\nVerdict: '+pred
            identity = {'freeze': c.sha(f.ROOT / f.EXP / 'freeze.json'),
                'adapter_sha256': p['old_adapters']['42']['adapter_sha256'] if spec['adapter'] else None}
            record = f.seal_record({'dataset': row['dataset'], 'id': row['id'], 'text': text,
                'raw_text': text, 'prediction': pred if finished else 'INVALID', 'finished': finished,
                'status': 'completed' if finished else 'truncated', 'reason_present': True,
                'identity': identity, 'input_sha256': c.digest(c.messages(row, prompts[spec['prompt']]))})
            f.immutable(tmp_path / 'validation/direct' / arm / (key+'.json'), record)
    result = priority.report(tmp_path, 'seed42')
    assert result['descriptive_only'] and result['no_final_recommendation']
    assert result['scores']['basic']['old_np_42']['invalid'] == 1
    assert result['corrections']['challenge']['old_np_42']['old_a0_42']['rescued'] == 1
    assert result['families']['challenge']['old_np']['all_seeds_present'] is False
    assert result['per_arm_guardrails']['old_np_42']['passed'] is False
    assert not (tmp_path / 'recommendation.json').exists()
    assert not (tmp_path / 'validation/results.json').exists()
    assert not (tmp_path / 'evaluation').exists()
    # Resume verifies the same results, not additional model generations.
    assert priority.report(tmp_path, 'seed42') == result
    missing = tmp_path / 'validation/direct/old_np_42/basic_0.json'
    missing.unlink()
    with pytest.raises(FileNotFoundError):
        priority.report(tmp_path, 'seed42')
