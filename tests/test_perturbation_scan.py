import json
from types import SimpleNamespace
import h5py
import numpy as np
import pandas as pd
import pytest
from scipy.stats import hypergeom
from perturbation_scan.statistics import exact_stratified_test,implicit_holm
from perturbation_scan.scan import Counts,scan
from perturbation_scan.data import plan_metadata,aggregate,load_catalogue

PATTERNS=[dict(reference_id='R1',genes=['A','B','C'],states=[1,1,1],pattern='A+ B+ C+')]

@pytest.mark.parametrize('xp,n,xc,m',[(0,20,15,30),(18,20,3,30),(5,10,9,18),(0,100,0,100),(100,100,100,100)])
def test_single_batch(xp,n,xc,m):
    rv=hypergeom(n+m,xp+xc,n)
    expected=min(1,2*min(rv.cdf(xp),rv.sf(xp-1)))
    assert exact_stratified_test([xp],[n],[xc],[m])['p_value']==pytest.approx(expected,rel=2e-9)


def test_two_batch_enumeration():
    xp=[1,4];ns=[4,5];xc=[4,2];ms=[6,8]
    lo=hi=0.
    for a in range(5):
        for b in range(6):
            prob=hypergeom.pmf(a,10,5,4)*hypergeom.pmf(b,13,6,5)
            if a+b<=sum(xp):lo+=prob
            if a+b>=sum(xp):hi+=prob
    assert exact_stratified_test(xp,ns,xc,ms)['p_value']==pytest.approx(min(1,2*min(lo,hi)),rel=2e-9)


def test_extreme_tail_and_holm():
    p=exact_stratified_test([300],[300],[0],[300])['p_value']
    assert 0<p<1e-100
    actual=implicit_holm([.001,.02,1.],10)
    extended=implicit_holm([.001,.02]+[1.]*8,10)
    assert np.allclose(actual,extended[:3])
    assert actual.tolist()==pytest.approx([.01,.18,1])


def test_batch_confounding_and_zero_depletion(tmp_path):
    # pooled NT=50%, target=82%; within each batch rates are exactly equal.
    c=Counts(('COMPOSITION','DEPLETION','SMALL'),('a','b'),
        np.array([0,0,1,1,2,3]),np.array([0,1,0,1,0,0]),
        np.array([1000,1000,900,100,300,20]),np.array([[900],[100],[810],[10],[0],[0]]),PATTERNS,3)
    summary=scan(c,tmp_path/'out')
    with np.load(tmp_path/'out/statistics.npz') as d:
        assert d['delta'][0,0]==pytest.approx(0)
        assert not d['tested'][0,0]
        assert d['candidate'][1,0]
        assert not d['tested'][2,0]
    family=json.loads((tmp_path/'out/testing_family_frozen.json').read_text())
    assert family['family_size']==3
    assert not family['confirmatory']
    case=json.loads((tmp_path/'out/first_case.json').read_text())['case']
    assert case['target']=='DEPLETION'
    assert case['perturbation_hits']==0
    assert not case['eligible_as_confirmed_clue']
    assert summary['confirmed_clues']==0


def test_missing_nt_not_tested(tmp_path):
    c=Counts(('T',),('a','b'),np.array([0,1]),np.array([0,1]),np.array([1000,300]),np.array([[100],[200]]),PATTERNS,3)
    assert scan(c,tmp_path/'out')['exact_tests']==0


def test_allowed_only_aggregation_dense_hdf5_and_duplicate_states(tmp_path):
    obs=pd.DataFrame({'gene':['non-targeting','T','LOCKED','T','non-targeting'],
        'nperts':[0,1,1,1,0],'batch':['1']*5,'guide_id':['nt','t','l','t','nt']},index=list('abcde'))
    plan=plan_metadata(obs,['A','B','C','UNUSED'],PATTERNS,{'aliases':{},'rows':[{'canonical':'LOCKED'}]})
    matrix=np.array([[1,1,1,5],[0,1,1,2],[9,9,9,9],[1,1,1,7],[0,0,0,2]])
    class Guard:
        def __getitem__(self,key):
            sl,cols=key
            assert 2 not in range(sl.start,sl.stop)
            assert 3 not in cols
            return matrix[sl][:,cols]
    c=aggregate(SimpleNamespace(X=Guard()),plan,PATTERNS,4,chunk_rows=2)
    assert c.n_cells.tolist()==[2,2]
    assert c.hits.tolist()==[[1],[1]]
    with h5py.File(tmp_path/'test.h5','w') as f:
        d=f.create_dataset('X',data=matrix)
        got=aggregate(SimpleNamespace(X=d),plan,PATTERNS,4)
        assert np.array_equal(got.hits,c.hits)
    c.save(tmp_path/'counts');assert np.array_equal(Counts.load(tmp_path/'counts').hits,c.hits)


def test_bad_raw_counts_rejected():
    obs=pd.DataFrame(dict(gene=['non-targeting'],nperts=[0],batch=['b'],guide_id=['nt']))
    plan=plan_metadata(obs,['A','B','C'],PATTERNS,{'aliases':{},'rows':[]})
    with pytest.raises(ValueError,match='raw counts'):
        aggregate(SimpleNamespace(X=np.array([[.5,0,0]])),plan,PATTERNS,3)


def test_catalogue_tamper(tmp_path):
    from pathlib import Path
    source=Path('outputs/real_nt_v04_holm_20260927/remote/outputs/real_nt/genes_1000_full/holm_reference_catalogue_frozen.json')
    assert len(load_catalogue(source))==341
    doc=json.loads(source.read_text());doc['payload']['records'][0]['states'][0]^=1
    dest=tmp_path/'bad.json';dest.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='hash mismatch'):load_catalogue(dest)
