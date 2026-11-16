"""Failure modes that would misstate stability, identity, matching or coverage."""
import json
import numpy as np
import pandas as pd
import pytest
from broad_screening.analysis import choose_core,correlation,cluster
from broad_screening.config import Config
from broad_screening.sensitivity import align_modules,resample_schedule,bootstrap_partitions
from broad_screening.coverage import evaluate_case_set_coverage


def test_core_requires_every_pair_and_does_not_count_singletons():
    co=np.array([[1,.95,.3],[.95,1,.75],[.3,.75,1]])
    refs=np.array(['a','b','c'])
    core=choose_core(co,[0,1,2],refs,.8,2)
    assert set(core)=={0,1}
    assert len(choose_core(co,[2],refs,.8,2))==0
    assert len(choose_core(np.full((3,3),np.nan),[0,1,2],refs,.8,2))==0


def test_gene_only_OR_erases_contrasting_state_profiles():
    x=np.array([[1,-1],[2,-2],[-1,1],[-2,2]],float)
    mask=np.array([[1,0],[1,0],[0,1],[0,1]],bool)
    assert correlation(x)[0,1]==pytest.approx(-1)
    collapsed=mask.any(1)
    assert collapsed.all()
    # The collapse is constant, so correlation is undefined, not assigned zero.
    assert np.isnan(correlation(collapsed[:,None].astype(float))[0,0])
    groups,_=cluster(collapsed[:,None].astype(float),[4],['abc'])
    assert groups[0]=='unclustered'


def test_alignment_uses_membership_not_module_names_and_allows_merges():
    rng=np.random.default_rng(7);x=rng.normal(size=(20,4));refs=np.array(list('abcd'))
    reference=np.array(['M01','M01','M02','M02'])
    alternative=np.array(['M02','M02','M01','M01'])
    matched=align_modules(x,reference,alternative,{'M01':[0,1],'M02':[2,3]},
                          {'M01':0,'M02':2},refs,'permuted')
    assert (matched.membership_jaccard==1).all()
    assert matched.set_index('reference_module').loc['M01','matched_module']=='M02'
    merged=align_modules(x,reference,np.array(['X']*4),{'M01':[0,1],'M02':[2,3]},
                         {'M01':0,'M02':2},refs,'merged')
    assert (merged.membership_jaccard==.5).all()
    assert (merged.n_reference_modules_sharing_match==2).all()


def test_matched_bootstrap_is_reproducible_and_tracks_constant_profiles():
    rng=np.random.default_rng(9);x=rng.normal(size=(12,4));x[:,3]=0
    cfg=Config(bootstrap_repetitions=4)
    schedule=resample_schedule(12,np.array(['a','a','b','b']),4,cfg.seed)
    first,labels=bootstrap_partitions(x,np.ones(4),np.array(list('abcd')),cfg,schedule)
    second,_=bootstrap_partitions(x,np.ones(4),np.array(list('abcd')),cfg,schedule)
    np.testing.assert_array_equal(first,second)
    assert (labels[:,3]=='unclustered').all()
    assert first[3].sum()==0


def test_coverage_is_not_selection_and_rejects_unknown_or_duplicate_ids(tmp_path):
    table=pd.DataFrame([dict(case_id='c1',module_id='M1',direction='enrichment',target_cluster='T1',target='A',
        redundancy_group_id='b1',core_or_boundary='stable_core',strata=json.dumps(['core','positive'])),
        dict(case_id='c2',module_id='M2',direction='depletion',target_cluster='T1',target='A',
        redundancy_group_id='b2',core_or_boundary='boundary',strata=json.dumps(['negative']))])
    p=tmp_path/'pool.csv';table.to_csv(p,index=False)
    result=evaluate_case_set_coverage(['c1'],p)
    assert result['modules']['fraction']==.5 and result['stable_cores']['covered']==1
    assert result['selected_for_deep'] is False
    assert evaluate_case_set_coverage([],p)['modules']['covered']==0
    with pytest.raises(ValueError):evaluate_case_set_coverage(['missing'],p)
    with pytest.raises(ValueError):evaluate_case_set_coverage(['c1','c1'],p)


def test_config_rejects_unassessable_stable_core_definition():
    with pytest.raises(ValueError):Config(stable_core_min_size=1).validate()
    with pytest.raises(ValueError):Config(bootstrap_repetitions=1).validate()
