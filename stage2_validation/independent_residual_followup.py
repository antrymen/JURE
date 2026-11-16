"""Supplement: paired residuals and conditional cell-bootstrap intervals."""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
import json,hashlib,time
import numpy as np
import pandas as pd
from scipy.stats import pearsonr,spearmanr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1];SRC=ROOT/'outputs/result2_preliminary_20261012';OUT=ROOT/'outputs/result2_independent_residual_20261013'
STATES=np.array([[int(v) for v in f'{i:03b}'] for i in range(8)])
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
inputs=[SRC/'eight_state_counts.npz',SRC/'identities.json',OUT/'PROTOCOL.md',Path(__file__)]
locks={}
for cohort in [100,50]:
 for direction in ['A_to_B','B_to_A']:
  p=SRC/f'lower_order/locked_candidates_n{cohort}_{direction}.csv.gz';inputs.append(p);locks[cohort,direction]=pd.read_csv(p)
(OUT/'INPUTS_FROZEN.json').write_text(json.dumps({str(p.relative_to(ROOT)):sha(p) for p in inputs},indent=2))
audit=json.loads((SRC/'COUNTS_AUDIT.json').read_text());assert sha(SRC/'eight_state_counts.npz')==audit['counts_sha256']
z=np.load(SRC/'eight_state_counts.npz');table=z['table'];n=z['n'];mapping=z['mapping'];codes=z['codes'];ids=json.loads((SRC/'identities.json').read_text())
assert np.array_equal(table.sum(-1),np.broadcast_to(n[...,None],table.shape[:-1]))
start=time.time();cache={}
def calc(pp,pn,N,ne,alpha):
 sp=(pp*N+alpha)/(N+8*alpha);sn=(pn*ne+alpha)/(ne+8*alpha)
 def ind(p):
  marg=p@STATES
  return np.prod(np.where(STATES==1,marg[...,None,:],1-marg[...,None,:]),axis=-1)
 obs=pp-pn;di=ind(sp)-ind(sn);smooth=sp-sn
 return obs,di,obs-di,smooth-di

def point(f,t,j,alpha):
 key=(f,t,j,alpha)
 if key not in cache:
  used=n[f,t]>0;nt=n[f,0,used];counts=n[f,t,used];N=counts.sum();w=counts/N;ne=1/np.sum(w*w/nt)
  pp=table[f,t,:,j,:].sum(0)/N;pn=w@(table[f,0,used,j,:]/nt[:,None])
  cache[key]=calc(pp,pn,N,ne,alpha)
 return cache[key]
paired=[];summaries=[]
def metrics(a,b):
 return dict(pearson=float(pearsonr(a,b).statistic),spearman=float(spearmanr(a,b).statistic),same_sign=float(np.mean(np.sign(a)==np.sign(b))),median_abs_discovery_pp=float(np.median(abs(a))*100),median_abs_validation_pp=float(np.median(abs(b))*100),validation_mae_pp=float(np.mean(abs(b))*100),median_abs_fold_difference_pp=float(np.median(abs(a-b))*100))
for (cohort,direction),df in locks.items():
 f=0 if direction=='A_to_B' else 1
 for alpha in [.5,.1,1.,0.]:
  rows=[]
  for r in df.itertuples():
   t=int(r.target_index);pi=int(r.pattern_index);j=int(mapping[pi]);code=int(codes[pi]);a=point(f,t,j,alpha);b=point(1-f,t,j,alpha)
   assert ids['targets'][t]==r.target and ids['patterns'][pi]['reference_id']==r.reference_id
   assert np.isclose(a[0][code],r.discovery_delta,atol=1e-12) and np.isclose(b[0][code],r.validation_delta,atol=1e-12)
   if alpha==.5:assert np.isclose(b[2][code],r.residual_independent,atol=1e-12)
   rows.append(dict(cohort=cohort,direction=direction,alpha=alpha,target=r.target,reference_id=r.reference_id,target_index=t,triplet_index=j,code=code,discovery_delta=a[0][code],validation_delta=b[0][code],discovery_ind=a[1][code],validation_ind=b[1][code],discovery_residual=a[2][code],validation_residual=b[2][code],discovery_smoothed_residual=a[3][code],validation_smoothed_residual=b[3][code]))
  d=pd.DataFrame(rows);paired.append(d)
  for mode in ['raw','smoothed']:
   ac='discovery_residual' if mode=='raw' else 'discovery_smoothed_residual';bc='validation_residual' if mode=='raw' else 'validation_smoothed_residual'
   for subset,mask in [('all',np.ones(len(d),bool)),('discovery_abs_ge_1pp',abs(d[ac])>=.01)]:
    q=d[mask];summaries.append(dict(cohort=cohort,direction=direction,alpha=alpha,residual_type=mode,subset=subset,n=len(q),**metrics(q[ac].to_numpy(),q[bc].to_numpy())))
allpairs=pd.concat(paired,ignore_index=True);allpairs.to_csv(OUT/'paired_residuals.csv.gz',index=False);pd.DataFrame(summaries).to_csv(OUT/'paired_summary.csv',index=False)
print('Paired summaries complete',flush=True)
# All main candidates, both folds; bootstrap each target-triplet once.
main=allpairs[(allpairs.cohort==100)&(allpairs.alpha==.5)].copy()
keys=sorted(set(zip(main.target_index,main.triplet_index)));boot={};draws=1000
for ki,(t,j) in enumerate(keys):
 for f in [0,1]:
  used=n[f,t]>0;nc=n[f,0,used];np_=n[f,t,used];N=int(np_.sum());w=np_/N;ne=1/np.sum(w*w/nc)
  seed=int.from_bytes(hashlib.sha256(f'20261013:{f}:{t}:{j}'.encode()).digest()[:8],'little');rng=np.random.default_rng(seed)
  pp=np.zeros((draws,8));pn=np.zeros((draws,8))
  cp=table[f,t,used,j,:];cn=table[f,0,used,j,:]
  for k in range(len(np_)):
   pp+=rng.multinomial(int(np_[k]),cp[k]/np_[k],size=draws)/N
   pn+=w[k]*rng.multinomial(int(nc[k]),cn[k]/nc[k],size=draws)/nc[k]
  assert np.allclose(pp.sum(1),1) and np.allclose(pn.sum(1),1)
  result=calc(pp,pn,N,ne,.5)
  boot[f,t,j]=(np.quantile(result[2],[.025,.975],axis=0),np.quantile(result[3],[.025,.975],axis=0))
 if ki%100==0:print(f'Bootstrap {ki+1}/{len(keys)} target-triplets; elapsed {time.time()-start:.1f}s',flush=True)
rows=[]
for r in main.itertuples():
 f=0 if r.direction=='A_to_B' else 1;row=r._asdict();row.pop('Index',None)
 for mode,idx in [('raw',0),('smoothed',1)]:
  for role,fold in [('discovery',f),('validation',1-f)]:
   lo,hi=boot[fold,r.target_index,r.triplet_index][idx][:,r.code];row[f'{role}_{mode}_lo']=lo;row[f'{role}_{mode}_hi']=hi
  disc=r.discovery_residual if mode=='raw' else r.discovery_smoothed_residual
  lo=row[f'validation_{mode}_lo'];hi=row[f'validation_{mode}_hi']
  row[f'{mode}_validation_interval_excludes_zero']=(lo>0 or hi<0)
  row[f'{mode}_validation_interval_in_discovery_direction']=(disc>0 and lo>0) or (disc<0 and hi<0)
 rows.append(row)
bd=pd.DataFrame(rows);bd.to_csv(OUT/'bootstrap_intervals.csv.gz',index=False)
bs=[]
for direction,d in bd.groupby('direction'):
 for mode in ['raw','smoothed']:
  ac='discovery_residual' if mode=='raw' else 'discovery_smoothed_residual'
  for subset,mask in [('all',np.ones(len(d),bool)),('discovery_abs_ge_1pp',abs(d[ac])>=.01)]:
   q=d[mask];bs.append(dict(direction=direction,mode=mode,subset=subset,n=len(q),interval_excludes_zero=int(q[f'{mode}_validation_interval_excludes_zero'].sum()),interval_in_discovery_direction=int(q[f'{mode}_validation_interval_in_discovery_direction'].sum()),fraction_in_discovery_direction=float(q[f'{mode}_validation_interval_in_discovery_direction'].mean())))
pd.DataFrame(bs).to_csv(OUT/'bootstrap_summary.csv',index=False)
# Descriptive figures with real computed points; no significance labels.
os.environ.setdefault('MPLCONFIGDIR','/tmp/jure-mpl');plt.rcParams.update({'pdf.fonttype':42,'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,axs=plt.subplots(1,2,figsize=(10,4.4))
for ax,(direction,d) in zip(axs,main.groupby('direction')):
 x=d.discovery_residual*100;y=d.validation_residual*100;lim=max(abs(x).max(),abs(y).max())*1.05
 ax.scatter(x,y,s=9,alpha=.35,color='#8065A6',edgecolors='none',rasterized=True);ax.plot([-lim,lim],[-lim,lim],'--',color='gray',lw=1);ax.axhline(0,color='#cccccc',lw=.6);ax.axvline(0,color='#cccccc',lw=.6)
 ax.set(xlim=(-lim,lim),ylim=(-lim,lim),title=f'{direction} | n={len(d)} | r={pearsonr(x,y).statistic:.3f}',xlabel='Discovery residual (pp)',ylabel='Validation residual (pp)')
fig.tight_layout()
for ext in ['png','pdf']:fig.savefig(OUT/f'residual_crossfold.{ext}',dpi=300)
plt.close(fig)
(OUT/'RUN_AUDIT.json').write_text(json.dumps(dict(seconds=time.time()-start,bootstrap_draws=draws,unique_main_target_triplets=len(keys),source_point_estimates_match=True,count_conservation=True,seed_rule='SHA256 20261013:fold:target_index:triplet_index',all_inputs_unchanged=all(sha(ROOT/p)==h for p,h in json.loads((OUT/'INPUTS_FROZEN.json').read_text()).items())),indent=2))
print('COMPLETE',time.time()-start,flush=True)
