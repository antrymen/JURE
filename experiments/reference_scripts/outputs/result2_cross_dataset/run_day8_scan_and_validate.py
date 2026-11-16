"""Continue only after an independently completed Day8 reference catalogue."""
from pathlib import Path
import sys,json,os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[k]='1'
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import numpy as np,pandas as pd,h5py,anndata as ad
from perturbation_scan.data import plan_metadata,metadata_tables
from perturbation_scan.scan import Counts,scan,ScanConfig
from perturbation_scan.statistics import exact_stratified_test,implicit_holm
from clue_discovery.v03.artifacts import digest,write_json
from clue_discovery.v03.data import file_hash
from scipy.stats import pearsonr,spearmanr
OUT=Path(__file__).resolve().parent/'day8_discovery'
def aggregate_source(source,patterns,dest,day):
 dest.mkdir(exist_ok=True)
 if (dest/'identities.json').exists():return Counts.load(dest)
 with h5py.File(source) as f:
  obs=ad.io.read_elem(f['obs']);genes=tuple(f['var/gene_name'].asstr()[:])
  # Use identical target inclusion/isolation rules as Day6; map Day8 control label only.
  obs['gene']=obs['gene'].astype(str).replace({'control':'non-targeting'})
  isolation=json.loads((ROOT/'dataset_audit/combined_audit.json').read_text())
  plan=plan_metadata(obs,genes,patterns,isolation);metadata_tables(obs,plan,dest/'metadata')
  write_json(dest/'aggregation_protocol.json',dict(day=day,source=str(source),targets=plan['targets'],patterns_digest=digest(patterns),excluded_targets=plan['excluded_targets'],n_allowed=len(plan['rows']),frozen_before_effects=True))
  G=len(plan['pairs']);P=len(patterns);hits=np.zeros((G,P),dtype=np.int64);n=np.bincount(plan['row_groups'],minlength=G).astype(np.int64)
  lookup={g:i for i,g in enumerate(plan['genes'])};idx=np.array([[lookup[g] for g in p['genes']] for p in patterns]);states=np.array([p['states'] for p in patterns],dtype=bool)
  X=f['X'];step=X.chunks[0] if X.chunks else 1024;rows=plan['rows']
  for start in range(0,len(obs),step):
   stop=min(start+step,len(obs));left=np.searchsorted(rows,start);right=np.searchsorted(rows,stop)
   if left==right:continue
   block=X[start:stop,plan['columns']][rows[left:right]-start]
   assert np.isfinite(block).all() and (block>=0).all() and (block==np.floor(block)).all()
   enc=block>0;groups=plan['row_groups'][left:right]
   active,inverse=np.unique(groups,return_inverse=True)
   for j in range(P):hits[active,j]+=np.bincount(inverse,weights=np.all(enc[:,idx[j]]==states[j],axis=1),minlength=len(active)).astype(np.int64)
   if start%(step*50)==0:print('aggregate',day,start,len(obs),flush=True)
  result=Counts(plan['targets'],plan['batches'],np.array([p[0] for p in plan['pairs']]),np.array([p[1] for p in plan['pairs']]),n,hits,patterns,len(genes));result.save(dest);return result

def main():
 cat=OUT/'genes_1000_full/holm_reference_catalogue_frozen.json';doc=json.loads(cat.read_text());assert digest(doc['payload'])==doc['sha256']
 patterns=doc['payload']['records'];assert all(p['order']==3 for p in patterns)
 write_json(OUT/'day8_catalogue_locked.json',dict(catalogue_sha256=file_hash(cat),states=len(patterns),stage2_started=False))
 if not patterns:write_json(OUT/'reverse_summary.json',dict(status='NO_DAY8_REFERENCE_STATES',validation_run=False));return
 counts=aggregate_source(ROOT/'data/replogle_k562_gwps_day8/ReplogleWeissman2022_K562_gwps.h5ad',patterns,OUT/'day8_counts','Day8')
 if not (OUT/'day8_scan/summary.json').exists():scan(counts,OUT/'day8_scan',ScanConfig())
 cp=OUT/'day8_scan/candidates.jsonl';candidates=[json.loads(s) for s in cp.read_text().splitlines()];M=len(candidates)
 write_json(OUT/'day8_candidates_locked_before_day6.json',dict(source=str(cp),sha256=file_hash(cp),n=M,validation_alpha=.05,minimum_target=100,minimum_nt_batch=20,minimum_effective_nt=100,validation_effect_filter=False))
 if not M:write_json(OUT/'reverse_summary.json',dict(status='NO_DAY8_CANDIDATES',validation_run=False));return
 # Day6 mapping based only on names; missing states retained in validation family.
 src=ROOT/'data/replogle_k562_essential_day6/ReplogleWeissman2022_K562_essential.h5ad'
 with h5py.File(src) as f:available=set(f['var/gene_name'].asstr()[:])
 wanted={c['reference_id'] for c in candidates};mapped=[p for p in patterns if p['reference_id'] in wanted and set(p['genes'])<=available]
 dc=aggregate_source(src,mapped,OUT/'day6_validation_counts','Day6');pi={p['reference_id']:i for i,p in enumerate(mapped)};ti={t:i+1 for i,t in enumerate(dc.targets)}
 B=len(dc.batches);nc=np.zeros(B,dtype=np.int64);xc=np.zeros((B,len(mapped)),dtype=np.int64);controls=dc.group_target==0;nc[dc.group_batch[controls]]=dc.n_cells[controls];xc[dc.group_batch[controls]]=dc.hits[controls]
 rows=[]
 for k,c in enumerate(candidates):
  row=dict(clue_id=c['clue_id'],target=c['target'],reference_id=c['reference_id'],pattern=c['pattern'],day8_delta_pp=c['delta_percentage_points'],day6_delta_pp=None,p_value=1.,status='OK')
  if c['reference_id'] not in pi:row['status']='missing_genes'
  elif c['target'] not in ti:row['status']='target_unavailable_after_fixed_cell_rules'
  else:
   ix=np.flatnonzero(dc.group_target==ti[c['target']]);b=dc.group_batch[ix];n=dc.n_cells[ix];N=n.sum();row['day6_n']=int(N)
   if N<100:row['status']='insufficient_target_cells'
   elif (nc[b]<20).any():row['status']='insufficient_batch_nt'
   else:
    w=n/N;ne=1/np.sum(w*w/nc[b]);row['effective_nt']=ne
    if ne<100:row['status']='insufficient_effective_nt'
    else:
     j=pi[c['reference_id']];x=dc.hits[ix,j];y=xc[b,j];row['day6_delta_pp']=float(100*(x.sum()/N-w@(y/nc[b])));row['p_value']=exact_stratified_test(x,n,y,nc[b])['p_value']
  rows.append(row)
  if k%500==0:print('validate',k,M,flush=True)
 d=pd.DataFrame(rows);d['holm']=implicit_holm(d.p_value.to_numpy(),M);d['same_direction']=(np.sign(d.day6_delta_pp)==np.sign(d.day8_delta_pp))&(d.status=='OK');d['supported']=d.same_direction&(d.holm<=.05);d.to_csv(OUT/'day8_to_day6_validation.csv',index=False)
 a=d[d.status=='OK'];summary=dict(locked=M,evaluable=len(a),status_counts=d.status.value_counts().to_dict(),supported=int(d.supported.sum()),supported_fraction_all=float(d.supported.mean()),supported_fraction_evaluable=float(a.supported.mean()) if len(a) else None,direction_agreement=float(a.same_direction.mean()) if len(a) else None,pearson_r=float(pearsonr(a.day8_delta_pp,a.day6_delta_pp).statistic) if len(a)>1 else None)
 write_json(OUT/'reverse_summary.json',summary);print(summary,flush=True)
if __name__=='__main__':main()
