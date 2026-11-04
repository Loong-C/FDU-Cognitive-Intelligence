from ab_factcheck.controlled_v15_data import generate as original
from ab_factcheck.controlled_v15a_data import generate

def test_amendment_changes_exactly_prespecified_input_families():
    before, after = original(), generate()
    changes = [(a,b) for a,b in zip(before,after) if a['id'] != b['id']]
    assert len(changes) == 48
    assert len({r['id'] for r in after}) == 336
    for a,b in zip(before,after):
        for key in ('dataset','group','template_family','mechanism','label','semantics','claim'):
            assert a[key] == b[key]
        expected = (a['dataset'],a['mechanism']) in {('basic','RELDATE'),('challenge','AMBIGREF')}
        assert (a['id'] != b['id']) == expected

def test_repetition_and_exclusivity_scopes_are_explicit():
    for r in generate():
        if r['mechanism']=='RELDATE':
            assert 'exactly one arrival' in r['evidence'] or 'exactly one opening event' in r['evidence']
        if r['mechanism']=='AMBIGREF' and r['label']=='REFUTES':
            assert 'during that entire year' in r['evidence'] or 'only person ever' in r['evidence']
