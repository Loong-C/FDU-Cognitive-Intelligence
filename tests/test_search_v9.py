import itertools
import pytest
from ab_factcheck.search_v9 import ARMS, request, policy, rank
from ab_factcheck.macro_v7.inference import messages, schema
from ab_factcheck.common import LABELS


def test_transforms_preserve_exact_text_and_do_not_add_samples():
    c='A "quoted" claim\nwith {braces}.';e='First evidence.\nSecond evidence.'
    for arm,base in [('repeat_nli','nli'),('repeat_baseline','baseline')]:
        original=messages(base,claim=c,evidence=e)
        new=request(arm,claim=c,evidence=e)
        assert new['messages']==[original[0],{'role':'user','content':original[1]['content']+'\n\n'+original[1]['content']}]
        assert new['response_format']==schema(base)
    order=request('claim_first_nli',claim=c,evidence=e)
    assert order['messages'][1]['content']==f'HYPOTHESIS:\n{c}\n\nPREMISE:\n{e}'
    reason=request('reason_first_nli',claim=c,evidence=e)
    assert reason['messages']==messages('nli',claim=c,evidence=e)
    assert list(reason['response_format']['json_schema']['schema']['properties'])==['justification','relation']


def test_no_gold_or_metadata_accepted():
    with pytest.raises(TypeError):request('repeat_nli',claim='C',evidence='E',gold='SUPPORTS')
    with pytest.raises(ValueError):request('unknown',claim='C',evidence='E')


def test_all_label_symmetric_consensus_outcomes_and_invalids():
    for b,p,x in itertools.product((*LABELS,'INVALID'),repeat=3):
        pred={'baseline':b,'nli':p,'repeat_nli':x}
        expected=p if p in LABELS and p==x else b
        assert policy('agree__repeat_nli',pred)==expected


def test_rank_does_not_hide_large_dataset_loss_behind_average():
    def e(a,b):
        return {'method':'repeat_nli','metrics':{'basic':{'correct':a,'accuracy':a/7,'macro_f1':a/7},'challenge':{'correct':b,'accuracy':b/7,'macro_f1':b/7}},'baseline_metrics':{'basic':{'correct':7,'accuracy':1},'challenge':{'correct':3,'accuracy':3/7}}}
    assert rank(e(6,4))<rank(e(5,7))
