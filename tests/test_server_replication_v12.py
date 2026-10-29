import itertools
from ab_factcheck.server_replication_v12 import exact_p


def test_exact_integer_convolution_matches_full_sign_enumeration():
    for values in ([0]*14,[3,2,2,2,1,1,-1]+[0]*7,[1]*6+[0]*15,[2,-3,1,0,2,-1]):
        nonzero=[v for v in values if v]
        observed=sum(values)
        distribution=[sum(v*s for v,s in zip(nonzero,signs)) for signs in itertools.product((-1,1),repeat=len(nonzero))]
        expected=sum(x>=observed for x in distribution)/len(distribution)
        assert exact_p(values)==expected
    assert exact_p([1]*6+[0]*15)==1/64
