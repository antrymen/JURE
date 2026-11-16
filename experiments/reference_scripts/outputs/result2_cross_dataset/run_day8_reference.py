"""Independent Day8 NT discovery with unchanged Day6 statistical kernels."""
from pathlib import Path
import sys,json,os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[k]='1'
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from dataclasses import replace
import h5py,numpy as np,pandas as pd
from scipy import sparse
from clue_discovery.v04.config import ScalableConfig
from clue_discovery.v03.data import save_prepared,load_prepared,file_hash
from clue_discovery.v03.artifacts import write_json
from clue_discovery.v02.populations import Population
from clue_discovery.nt_reference import split_nt_twofold
from real_nt_v04_holm.run import run_reference,verify_frozen_engine,compress_csvs
OUT=Path(__file__).resolve().parent/'day8_discovery';OUT.mkdir(exist_ok=True)
SRC=ROOT/'data/replogle_k562_gwps_day8/ReplogleWeissman2022_K562_gwps.h5ad'
config=replace(ScalableConfig(),hvg_pool_size=1000,max_process_rss_mib=4096)
def state(phase,**kw):
 write_json(OUT/'execution_status.json',dict(phase=phase,**kw));print(phase,kw,flush=True)
def main():
 # Original guard hashes the entire expanding package, including unrelated adapters.
 from clue_discovery.v03.artifacts import code_hashes
 old=json.loads((ROOT/'outputs/real_nt_v04_holm_20260927/remote/outputs/real_nt/PROTOCOL_FROZEN.json').read_text())['source_hashes'];new=code_hashes()
 changed=[k for k,v in old.items() if k.startswith('clue_discovery/') and k.endswith('.py') and new.get(k)!=v]
 assert not changed, 'Original scientific kernels changed: '+str(changed)
 write_json(OUT/'kernel_compatibility.json',dict(original_python_kernels_match=True,original_sources=old,current_sources=new,note='Ignore added integration modules and pyproject packaging changes; original discovery kernels checked against Day6 run.'))
 prep=OUT/'prepared_nt';prep.mkdir(exist_ok=True)
 if not (prep/'data_manifest.json').exists():
  state('verify_source');assert file_hash(SRC,'md5')=='13db594f8f1d2ccb88fec44a13e414dc'
  with h5py.File(SRC) as f:
   genes=tuple(f['var/gene_name'].asstr()[:]);cats=f['obs/perturbation/categories'].asstr()[:];codes=f['obs/perturbation/codes'][:];nt=np.flatnonzero(codes==list(cats).index('control'))
   cells=tuple(f['obs/cell_barcode'].asstr()[nt]);batch=f['obs/batch'][:][nt]
   assert len(nt)==75328 and len(set(cells))==len(cells) and len(set(genes))==len(genes)
   dummy=Population(sparse.csr_matrix((len(nt),1)),('__identity__',),cells)
   A,B=split_nt_twofold(dummy,random_seed=config.random_seed,strata=batch.astype(str));aset=set(A.cell_ids);labels=np.array(['A' if c in aset else 'B' for c in cells]);del dummy,A,B,aset
   pd.DataFrame(dict(cell_id=cells,source_row=nt,batch=batch,fold=labels)).to_csv(prep/'nt_fold_membership.csv',index=False)
   write_json(OUT/'PROTOCOL_FROZEN.json',dict(dataset='Day8 GWPS',source_md5='13db594f8f1d2ccb88fec44a13e414dc',config=config.to_dict(),scope='NT-only independent discovery; no Day6 catalogue input',n_nt=len(nt),primary_scale=1000,fold_counts={v:int(sum(labels==v)) for v in ['A','B']},stage2='unchanged ScanConfig; full Day8; candidate family frozen before testing',validation='Day6; full Day8 candidate family Holm<=0.05 and same direction; n>=100, NT per batch>=20, effective NT>=100; unavailable p=1; no validation effect filter'))
   # Column blocks align with HDF5 layout. Read raw blocks, accumulate NT-only moments.
   temp=prep/'nt_all_counts.tmp.npy';mat=np.lib.format.open_memmap(temp,mode='w+',dtype=np.float32,shape=(len(nt),len(genes)))
   tables={v:[] for v in ['A','B']};X=f['X'];width=X.chunks[1]
   for start in range(0,len(genes),width):
    stop=min(start+width,len(genes));block=X[:,start:stop][nt,:]
    assert np.isfinite(block).all() and (block>=0).all() and (block==np.floor(block)).all()
    mat[:,start:stop]=block
    for fold in ['A','B']:
     a=block[labels==fold].astype(float);N=len(a);mean=a.mean(0);var=np.maximum(0,(np.mean(a*a,axis=0)-mean*mean)*N/(N-1));det=np.mean(a>0,axis=0);fano=np.divide(var,mean,out=np.zeros_like(mean),where=mean>0)
     tables[fold].append(pd.DataFrame(dict(gene=genes[start:stop],mean=mean,variance=var,detection_rate=det,fano=fano)))
    if start%(width*20)==0:state('NT_preparation',genes_completed=stop,total_genes=len(genes))
   selected=set();tables={v:pd.concat(t,ignore_index=True) for v,t in tables.items()}
   for fold,t in tables.items():
    eligible=t[(t['mean']>0)&t.detection_rate.between(config.min_detection_rate,config.max_detection_rate)]
    ranked=eligible.sort_values(['fano','gene'],ascending=[False,True]);assert len(ranked)>=1000;selected.update(ranked.head(1000).gene)
   ix=[i for i,g in enumerate(genes) if g in selected];matrix=sparse.csr_matrix(mat[:,ix]);mat.flush()
   save_prepared(prep,matrix,[genes[i] for i in ix],cells,labels.tolist(),dict(real_data_used=True,nt_only=True,n_cells=len(nt),source='Replogle K562 GWPS Day8',source_md5='13db594f8f1d2ccb88fec44a13e414dc',source_shape=list(X.shape),split_seed=config.random_seed,scientific_selection='own-fold sample Fano, same gates as Day6',projected_gene_union=len(ix)),tables)
   del mat,matrix;temp.unlink()
 state('Stage1_discovery_and_crossfold_validation')
 pops,sels,meta=load_prepared(prep,config)
 run_reference(pops,sels,meta,config,OUT/'genes_1000_full')
 compress_csvs(OUT/'genes_1000_full');state('Stage1_complete_stage2_pending')
if __name__=='__main__':
 try:main()
 except Exception as e:state('failed',error=str(e));raise
