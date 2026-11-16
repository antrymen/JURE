"""Batch-conditional tests and implicit-universe multiplicity accounting."""
import math
import numpy as np
from scipy.special import gammaln


def _integer_counts(value):
    a=np.asarray(value)
    if a.ndim!=1 or not np.isfinite(a).all() or (a<0).any() or (a!=np.floor(a)).any():
        raise ValueError('counts must be finite nonnegative integer vectors')
    return a.astype(np.int64)


def exact_stratified_test(xp,np_,xc,nc):
    """Inclusive doubled-smaller-tail exact conditional test of sum of hits.

    Independent batch hypergeometrics are convolved directly with nonnegative
    long-double arithmetic; no FFT or subtraction of a nearly-one CDF.
    """
    xp,np_,xc,nc=map(_integer_counts,(xp,np_,xc,nc))
    if not (xp.shape==np_.shape==xc.shape==nc.shape) or (xp>np_).any() or (xc>nc).any():
        raise ValueError('invalid stratified 2x2 counts')
    used=np_>0
    if not used.any() or (nc[used]<=0).any(): raise ValueError('missing matched controls')
    distribution=np.ones(1,dtype=np.longdouble);offset=0
    observed=int(xp[used].sum());mean=0.
    for a,n,b,m in zip(xp[used],np_[used],xc[used],nc[used]):
        total=int(n+m);hits=int(a+b);n=int(n)
        lo=max(0,n-(total-hits));hi=min(n,hits)
        values=np.arange(lo,hi+1,dtype=np.float64)
        def logchoose(N,k):return gammaln(N+1)-gammaln(k+1)-gammaln(N-k+1)
        logprob=logchoose(hits,values)+logchoose(total-hits,n-values)-logchoose(total,n)
        pmf=np.exp(logprob.astype(np.longdouble)-np.max(logprob))
        pmf/=pmf.sum()
        distribution=np.convolve(distribution,pmf)
        distribution/=distribution.sum()
        offset+=lo;mean+=n*hits/total
    index=observed-offset
    if not 0<=index<len(distribution):raise ArithmeticError('observation outside conditional support')
    tail=min(distribution[:index+1].sum(),distribution[index:].sum())
    p=min(np.longdouble(1),2*tail)
    # A positive floor is conservative for floating underflow at extreme tails.
    value=max(1e-300,min(1.,float(p)*(1+1e-10)))
    return dict(p_value=value,conditional_expected_hits=mean,observed_hits=observed,
                conditional_support_size=len(distribution),method='stratified_hypergeometric_doubled_inclusive_tail')


def implicit_holm(pvalues,family_size):
    p=np.asarray(pvalues,dtype=float)
    if (p.ndim!=1 or not np.isfinite(p).all() or ((p<0)|(p>1)).any()
        or not isinstance(family_size,int) or family_size<len(p)):
        raise ValueError('invalid p values or implicit family size')
    if not len(p):return p.copy()
    order=np.argsort(p,kind='stable')
    adjusted=np.minimum(1.,np.maximum.accumulate(p[order]*(family_size-np.arange(len(p)))))
    result=np.empty_like(adjusted);result[order]=adjusted
    return result


def universe_size(n_genes,n_targets):
    if not isinstance(n_genes,int) or n_genes<3 or not isinstance(n_targets,int) or n_targets<1:
        raise ValueError('invalid prespecified universe')
    return n_targets*8*math.comb(n_genes,3)


def simultaneous_delta_radius(np_,nc,family_size,alpha=.05):
    np_,nc=map(_integer_counts,(np_,nc))
    if np_.shape!=nc.shape or not np_.sum() or (nc[np_>0]==0).any():
        raise ValueError('missing matched cells')
    used=np_>0;w=np_[used]/np_.sum()
    variance_bound=1/np_.sum()+np.sum(w*w/nc[used])
    return min(2.,math.sqrt(variance_bound*math.log(2*family_size/alpha)/2))
