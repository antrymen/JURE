from pathlib import Path
import sys,json,hashlib
import numpy as np,pandas as pd,h5py
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from perturbation_scan.statistics import exact_stratified_test,implicit_holm
from scipy.stats import pearsonr,spearmanr
OUT=Path(__file__).resolve().parent
SRC=ROOT/'data/replogle_k562_gwps_day8/ReplogleWeissman2022_K562_gwps.h5ad'
CAND=ROOT/'outputs/perturbation_scan_day6_v01_20260927/EXPLORATORY_CANDIDATES.csv'
def sha(p,algo='sha256'):
 h=hashlib.new(algo)
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
 return h.hexdigest()
def decode(a):return np.array([v.decode() if isinstance(v,bytes) else str(v) for v in a])
print('Checking Day8 checksum',flush=True)
assert sha(SRC,'md5')=='13db594f8f1d2ccb88fec44a13e414dc'
c=pd.read_csv(CAND);assert len(c)==6129 and not c.duplicated(['target','pattern']).any()
(OUT/'forward_inputs_frozen.json').write_text(json.dumps({str(p):sha(p) for p in [CAND,OUT/'PROTOCOL.md',Path(__file__)]},indent=2))
patterns={p:([(s[:-1]) for s in p.split()],[int(s[-1]=='+') for s in p.split()]) for p in c.pattern.unique()}
wanted=sorted({g for gs,_ in patterns.values() for g in gs})
with h5py.File(SRC) as f:
 g=decode(f['var/gene_name'][:]);assert len(set(g))==len(g)
 cats=decode(f['obs/perturbation/categories'][:]);codes=f['obs/perturbation/codes'][:];assert (codes>=0).all()
 labels=cats[codes];b=f['obs/batch'][:];batches,bi=np.unique(b,return_inverse=True)
 targets=['control']+sorted(c.target.unique());tm={t:i for i,t in enumerate(targets)};ti=np.array([tm.get(t,-1) for t in labels]);valid=ti>=0;B=len(batches);T=len(targets)
 group=ti*B+bi;n=np.bincount(group[valid],minlength=T*B).reshape(T,B)
 missing=set(wanted)-set(g);present=[x for x in wanted if x not in missing];pos=sorted([int(np.where(g==x)[0][0]) for x in present]);names=g[pos];wi={x:i for i,x in enumerate(names)}
 cache=OUT/'day8_candidate_detection.npy';meta=OUT/'extraction.json'
 if not (cache.exists() and meta.exists()):
  encoded=np.lib.format.open_memmap(cache,mode='w+',dtype='uint8',shape=(len(labels),len(pos)))
  x=f['X'];step=x.chunks[0]
  for start in range(0,len(labels),step):
   a=x[start:start+step,pos];assert np.isfinite(a).all() and (a>=0).all() and (a==np.floor(a)).all()
   encoded[start:start+len(a)]=a>0
   if start%(step*50)==0:print('extract',start,len(labels),flush=True)
  encoded.flush();meta.write_text(json.dumps({'genes':names.tolist(),'shape':list(encoded.shape),'source_md5':'13db594f8f1d2ccb88fec44a13e414dc','encoding':'raw integer counts >0','missing_genes':sorted(missing)},indent=2))
 else:
  assert json.loads(meta.read_text())['genes']==names.tolist()
 encoded=np.load(cache,mmap_mode='r');hits={}
 for pattern,(gs,states) in patterns.items():
  if set(gs)&missing:continue
  mask=np.all(encoded[:,[wi[x] for x in gs]]==states,axis=1)&valid
  hits[pattern]=np.bincount(group[mask],minlength=T*B).reshape(T,B)
 rows=[]
 for idx,r in c.iterrows():
  t=tm[r.target];used=n[t]>0;np_=n[t,used];nc=n[0,used];N=int(np_.sum());status='OK';ne=None
  if r.pattern not in hits:status='missing_genes'
  elif N==0:status='target_absent'
  elif N<100:status='insufficient_target_cells'
  elif (nc<20).any():status='insufficient_batch_nt'
  else:
   w=np_/N;ne=1/np.sum(w*w/nc)
   if ne<100:status='insufficient_effective_nt'
  row=r.to_dict();row.update(day8_status=status,day8_n=N,day8_effective_nt=ne,day8_delta_pp=None,day8_p_value=1.,day8_matched_nt_frequency=None,day8_perturbation_frequency=None)
  if status=='OK':
   h=hits[r.pattern];xp=h[t,used];xc=h[0,used];p=xp.sum()/N;q=w@(xc/nc)
   row.update(day8_delta_pp=float((p-q)*100),day8_perturbation_frequency=float(p),day8_matched_nt_frequency=float(q),day8_p_value=exact_stratified_test(xp,np_,xc,nc)['p_value'])
  rows.append(row)
  if idx%500==0:print('tested',idx,flush=True)
d=pd.DataFrame(rows);d['day8_holm']=implicit_holm(d.day8_p_value.to_numpy(),6129);d['same_direction']=(np.sign(d.day8_delta_pp)==np.sign(d.delta_percentage_points))&(d.day8_status=='OK');d['validation_supported']=d.same_direction&(d.day8_holm<=.05)
d.to_csv(OUT/'day6_to_day8_validation.csv',index=False)
a=d[d.day8_status=='OK'];summary={'direction':'Day6_to_Day8','locked':6129,'evaluable':len(a),'status_counts':d.day8_status.value_counts().to_dict(),'supported':int(d.validation_supported.sum()),'supported_fraction_all':float(d.validation_supported.mean()),'supported_fraction_evaluable':float(a.validation_supported.mean()),'direction_agreement_evaluable':float(a.same_direction.mean()),'pearson_r':float(pearsonr(a.delta_percentage_points,a.day8_delta_pp).statistic),'spearman_r':float(spearmanr(a.delta_percentage_points,a.day8_delta_pp).statistic),'reverse_status':'NOT_RUN'}
(OUT/'day6_to_day8_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
