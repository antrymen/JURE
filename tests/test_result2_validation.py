import numpy as np
import pytest
from stage2_validation.result2 import projections,effect,validation,STATES


def test_independent_and_parity():
    p=np.prod(np.where(STATES==1,[.2,.4,.7],[.8,.6,.3]),axis=1)[None,:]
    sm,ind,q,ok,err,con=projections(p,1000000,.1)
    assert ok.all() and err<1e-8 and con<1e-7
    assert np.max(abs(sm-q))<1e-6
    parity=np.where(STATES.sum(1)%2, .24,.01)[None,:]
    sm,ind,q,ok,err,con=projections(parity,1000000,.1)
    assert np.max(abs(q-.125))<1e-8
    assert np.max(abs(sm-q))>.1


def test_pairwise_only_and_mixture():
    logits=STATES@np.array([.2,-.4,.7])+1.2*STATES[:,0]*STATES[:,1]-.7*STATES[:,1]*STATES[:,2]
    p=np.exp(logits-logits.max());p/=p.sum()
    sm,ind,q,ok,err,con=projections(p[None,:],1e9,.1)
    assert np.max(abs(p-q))<1e-8
    def independent(r):return np.prod(np.where(STATES==1,r,1-r),axis=1)
    mixture=.2*independent(.05)+.8*independent(.8)
    sm,ind,q,ok,err,con=projections(mixture[None,:],1e9,.1)
    assert np.max(abs(sm-q))>.001 # mixtures can themselves create apparent high-order residual


def test_sparse_smoothed_marginals():
    p=np.array([[1,0,0,0,0,0,0,0],[0,0,.5,0,.5,0,0,0]])
    for alpha in (.1,.5,1.):
        sm,ind,q,ok,err,con=projections(p,50,alpha)
        assert ok.all() and err<1e-8 and con<1e-7
        signs=(-1.)**STATES.sum(1)
        assert np.allclose((sm-q)*signs,((sm-q)*signs)[:,0,None])


def test_matched_baseline_and_validation_no_effect_prefilter(tmp_path):
    table=np.zeros((2,2,2,1,8),dtype=np.uint16)
    n=np.array([[[1000,1000],[100,100]],[[1000,1000],[100,100]]])
    for f in (0,1):
        table[f,0,:,0,7]=[900,100];table[f,0,:,0,0]=[100,900]
        table[f,1,:,0,7]=[90,10];table[f,1,:,0,0]=[10,90]
    d,b,*_=effect(table,n,1,1,np.array([0]),np.array([7]));assert d[0]==0
    locked=[dict(target_index=1,pattern_index=0,target='T',reference_id='R',discovery_delta=.2,direction=1)]
    frame,s=validation(tmp_path,100,0,locked,table,n,np.array([0]),np.array([7]))
    assert len(frame)==1 and frame.evaluable.iloc[0]
    assert frame.p_accounting.iloc[0]>.99 and not frame.validated.iloc[0]
    assert s['locked']==1


def test_empty_validation(tmp_path):
    frame,s=validation(tmp_path,100,0,[],None,None,None,None)
    assert s['locked']==0 and s['replication_rate'] is None
