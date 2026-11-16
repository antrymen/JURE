"""Frozen CPU-only Result 2 experiments."""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):os.environ[k]='1'
import argparse,json,time,resource,sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import pearsonr,spearmanr
from clue_discovery.v03.artifacts import digest,write_json
from clue_discovery.v03.data import file_hash
from clue_discovery.v03.lower_order_null import LowerOrderNullModel
from perturbation_scan.data import load_catalogue
from perturbation_scan.statistics import exact_stratified_test,implicit_holm

ROOT=Path(__file__).resolve().parents[1]
SPLIT=ROOT/'outputs/stage2_day6_ab_split_v1_20261007'
STORE=ROOT/'data/day6_tool_store'
CAT=ROOT/'outputs/real_nt_v04_holm_20260927/remote/outputs/real_nt/genes_1000_full/holm_reference_catalogue_frozen.json'
STATES=np.array([[int(c) for c in f'{i:03b}'] for i in range(8)])


def correlations(a,b):
    a=np.asarray(a,dtype=float);b=np.asarray(b,dtype=float);ok=np.isfinite(a)&np.isfinite(b);a=a[ok];b=b[ok]
    if len(a)<3 or np.std(a)==0 or np.std(b)==0:return dict(pearson=None,spearman=None)
    return dict(pearson=float(pearsonr(a,b).statistic),spearman=float(spearmanr(a,b).statistic))


def prepare(out):
    patterns=load_catalogue(CAT)
    sm=json.loads((SPLIT/'SPLIT_MANIFEST.json').read_text())
    assert file_hash(SPLIT/'cell_fold_assignment.csv.gz')==sm['assignment_sha256']
    manifest=json.loads((STORE/'manifest.json').read_text())
    for name,h in manifest['files'].items():assert file_hash(STORE/name)==h
    meta=pd.read_csv(STORE/'cells.csv.gz',dtype={'cell_id':str,'scan_target':str,'batch':str})
    split=pd.read_csv(SPLIT/'cell_fold_assignment.csv.gz',dtype={'cell_id':str,'scan_target':str,'batch':str})
    assert meta.cell_id.is_unique and split.cell_id.is_unique and set(meta.cell_id)==set(split.cell_id)
    split=split.set_index('cell_id').loc[meta.cell_id].reset_index()
    for col in ('source_row','scan_target','batch','guide_id'):assert np.array_equal(meta[col].to_numpy(),split[col].to_numpy())
    isolation=json.loads((ROOT/'dataset_audit/combined_audit.json').read_text())
    excluded={r['canonical'] for r in isolation['rows']}|set(isolation['aliases'])
    assert not set(meta.scan_target)&excluded
    targets=['non-targeting']+sorted(set(meta.scan_target)-{'non-targeting'})
    batches=sorted(meta.batch.unique());tmap={v:i for i,v in enumerate(targets)};bmap={v:i for i,v in enumerate(batches)}
    ti=meta.scan_target.map(tmap).to_numpy();bi=meta.batch.map(bmap).to_numpy();fi=(split.fold=='B').to_numpy().astype(int)
    N,B=len(targets),len(batches);groups=(fi*N+ti)*B+bi
    n=np.bincount(groups,minlength=2*N*B).reshape(2,N,B)
    cohorts={str(m):np.flatnonzero((n.sum(2)>=m).all(0)&(np.arange(N)>0)) for m in (100,50)}
    assert len(cohorts['100'])==386 and len(cohorts['50'])==1242
    triplets=sorted({tuple(p['genes']) for p in patterns});tl={g:i for i,g in enumerate(triplets)}
    mapping=np.array([tl[tuple(p['genes'])] for p in patterns]);codes=np.array([np.dot(p['states'],[4,2,1]) for p in patterns])
    cfg=dict(cohorts={k:[targets[i] for i in v] for k,v in cohorts.items()},patterns=[p['reference_id'] for p in patterns],
        discovery_alpha=.05,validation_alpha_per_direction=.025,min_abs_delta=.10,min_directional_support=10,
        min_nt_batch=20,min_effective_nt=100,lower_order_alphas=[.5,.1,1.],nt_selection_adjusted=False,
        confirmatory=False,split=sm,store_manifest=manifest,catalogue_sha256=file_hash(CAT),
        source_hashes={str(p.relative_to(ROOT)):file_hash(p) for p in [Path(__file__),ROOT/'stage2_validation/RESULT2_PROTOCOL.md',ROOT/'perturbation_scan/statistics.py',ROOT/'clue_discovery/v03/lower_order_null.py']})
    write_json(out/'PROTOCOL_FROZEN.json',cfg)
    write_json(out/'identities.json',dict(targets=targets,batches=batches,triplets=triplets,patterns=patterns))
    # No expression accessed before this metadata/configuration barrier.
    genes=json.loads((STORE/'genes.json').read_text());gidx={g:i for i,g in enumerate(genes)}
    wanted=sorted({g for t in triplets for g in t});positions=np.array([gidx[g] for g in wanted]);wi={g:i for i,g in enumerate(wanted)}
    packed=np.load(STORE/'states.npy',mmap_mode='r',allow_pickle=False)
    encoded=np.empty((len(meta),len(wanted)),dtype=np.uint8)
    for start in range(0,len(meta),4096):
        encoded[start:start+4096]=(packed[start:start+4096,positions//8]>>(7-positions%8))&1
    table=np.empty((2,N,B,len(triplets),8),dtype=np.uint16)
    for j,tri in enumerate(triplets):
        code=encoded[:,[wi[g] for g in tri]]@np.array([4,2,1],dtype=np.uint8)
        counts=np.bincount(groups*8+code,minlength=2*N*B*8).reshape(2,N,B,8)
        assert counts.max()<65536 and np.array_equal(counts.sum(-1),n)
        table[:,:,:,j,:]=counts
    for j,p in enumerate(patterns):assert table[:,0,:,mapping[j],codes[j]].sum()==p['nt_support']
    np.savez_compressed(out/'eight_state_counts.npz',table=table,n=n,mapping=mapping,codes=codes)
    write_json(out/'COUNTS_AUDIT.json',dict(nt_supports_match=341,cell_ids_match=True,excluded_targets_absent=True,
        fold_totals=n.sum((1,2)).tolist(),counts_sha256=file_hash(out/'eight_state_counts.npz')))
    return patterns,targets,triplets,cohorts,table,n,mapping,codes


def effect(table,n,f,t,mapping,codes):
    used=n[f,t]>0;np_=n[f,t,used];nc=n[f,0,used];w=np_/np_.sum()
    x=table[f,t,used][:,mapping,codes].astype(int);xc=table[f,0,used][:,mapping,codes].astype(int)
    base=w@(xc/nc[:,None]);delta=x.sum(0)/np_.sum()-base
    eligible=bool((nc>=20).all() and 1/np.sum(w*w/nc)>=100)
    return delta,base,x,xc,np_,nc,eligible


def discovery(out,minimum,ids,patterns,targets,table,n,mapping,codes):
    folder=out/f'n{minimum}';folder.mkdir()
    results=[]
    for f in (0,1):
        p=np.ones((len(ids),len(patterns)));d=np.zeros_like(p);eligible=np.zeros_like(p,dtype=bool)
        for i,t in enumerate(ids):
            delta,base,x,xc,np_,nc,ok=effect(table,n,f,t,mapping,codes);d[i]=delta
            if not ok:continue
            N=np_.sum();xp=x.sum(0)
            gate=(abs(delta)>=.1)&(np.where(delta>0,xp,N-xp)>=10)&(N*np.where(delta>0,1-base,base)>=10)
            for j in np.flatnonzero(gate):p[i,j]=exact_stratified_test(x[:,j],np_,xc[:,j],nc)['p_value']
            eligible[i]=gate
        adj=implicit_holm(p.ravel(),p.size).reshape(p.shape);selected=eligible&(adj<=.05)
        frame=pd.DataFrame(dict(target=np.repeat(np.array(targets)[ids],len(patterns)),
            reference_id=np.tile([r['reference_id'] for r in patterns],len(ids)),delta=d.ravel(),
            p_accounting=p.ravel(),holm=adj.ravel(),tested=eligible.ravel(),candidate=selected.ravel()))
        frame.to_csv(folder/f'discovery_{"AB"[f]}_all.csv.gz',index=False)
        locked=[dict(target_index=int(ids[i]),pattern_index=int(j),target=targets[ids[i]],
            reference_id=patterns[j]['reference_id'],discovery_delta=float(d[i,j]),direction=int(np.sign(d[i,j])))
            for i,j in zip(*np.nonzero(selected))]
        write_json(folder/f'locked_{"AB"[f]}.json',dict(family_size=p.size,candidates=locked))
        results.append(locked)
        print(json.dumps(dict(phase='discovery_frozen',minimum=minimum,fold='AB'[f],candidates=len(locked))),flush=True)
    return results


def validation(folder,minimum,source,locked,table,n,mapping,codes):
    f=1-source;rows=[];cache={}
    for item in locked:
        t=item['target_index'];j=item['pattern_index']
        if t not in cache:cache[t]=effect(table,n,f,t,mapping,codes)
        delta,base,x,xc,np_,nc,ok=cache[t]
        p=exact_stratified_test(x[:,j],np_,xc[:,j],nc)['p_value'] if ok else 1.
        rows.append(dict(**item,validation_delta=float(delta[j]),n_discovery=int(n[source,t].sum()),
            n_validation=int(np_.sum()),p_accounting=p,evaluable=ok,
            same_direction=bool(np.sign(delta[j])==item['direction']),validation_abs_ge_10pp=bool(abs(delta[j])>=.1)))
    columns=['target_index','pattern_index','target','reference_id','discovery_delta','direction','validation_delta',
             'n_discovery','n_validation','p_accounting','evaluable','same_direction','validation_abs_ge_10pp']
    df=pd.DataFrame(rows,columns=columns)
    df['holm']=implicit_holm(df.p_accounting.to_numpy(float),len(df))
    df['validated']=df.evaluable&df.same_direction&(df.holm<=.025)
    df['validated_10pp']=df.validated&df.validation_abs_ge_10pp
    name='AB'[source]+'_to_'+'AB'[f];df.to_csv(folder/f'validation_{name}.csv',index=False)
    summary=metrics(df);summary.update(minimum=minimum,direction=name)
    write_json(folder/f'summary_{name}.json',summary)
    return df,summary


def metrics(df):
    N=len(df)
    return dict(locked=N,evaluable=int(df.evaluable.sum()),same_direction=int(df.same_direction.sum()),
        direction_rate=float(df.same_direction.mean()) if N else None,
        validated=int(df.validated.sum()),replication_rate=float(df.validated.mean()) if N else None,
        validation_abs_ge_10pp=int(df.validation_abs_ge_10pp.sum()),
        effect_retention_rate=float(df.validation_abs_ge_10pp.mean()) if N else None,
        validated_10pp=int(df.validated_10pp.sum()),strict_rate=float(df.validated_10pp.mean()) if N else None,
        **correlations(df.discovery_delta,df.validation_delta))


def distributions(table,n,f,t):
    used=n[f,t]>0;w=n[f,t,used]/n[f,t].sum()
    pp=table[f,t].sum(0)/n[f,t].sum()
    pn=np.einsum('b,bks->ks',w,table[f,0,used]/n[f,0,used,None,None])
    neff=1/np.sum(w*w/n[f,0,used])
    return pp,pn,int(n[f,t].sum()),neff,used,w


def projections(p,n,alpha):
    smooth=(p*n+alpha)/(n+8*alpha)
    pair,ok=LowerOrderNullModel().fit_batch(smooth)
    marg=smooth@STATES
    independent=np.prod(np.where(STATES[None,:,:]==1,marg[:,None,:],1-marg[:,None,:]),axis=2)
    err=0.
    for drop in range(3):
        index=STATES[:,[k for k in range(3) if k!=drop]]@np.array([2,1])
        for state in range(4):err=max(err,float(abs((smooth-pair)[:,index==state].sum(1)).max()))
    signs=(-1.)**STATES.sum(1)
    contrast=np.max(abs(np.log(pair)@signs))
    return smooth,independent,pair,ok,err,float(contrast)


def lower_order(out,ids,targets,patterns,table,n,mapping,codes):
    folder=out/'lower_order';folder.mkdir()
    ranks=sorted(ids,key=lambda t:(n[:,t].sum(1).min(),targets[t]))
    pilot=[ranks[i] for i in np.linspace(0,len(ranks)-1,12,dtype=int)]
    write_json(folder/'PILOT_FROZEN.json',dict(targets=[targets[i] for i in pilot],alphas=[.5,.1,1.],
        max_marginal_error=1e-8,max_log_contrast=1e-7,min_success_fraction=.99,descriptive_only=True))
    checks=[];batchdiag=[]
    for f in (0,1):
        for t in pilot:
            pp,pn,N,ne,used,w=distributions(table,n,f,t)
            delta=effect(table,n,f,t,mapping,codes)[0]
            assert np.max(abs((pp-pn)[mapping,codes]-delta))<1e-10
            for alpha in (.5,.1,1.):
                for label,p,size in [('pert',pp,N),('NT',pn,ne)]:
                    sm,ind,q,ok,err,con=projections(p,size,alpha)
                    checks.append(dict(fold='AB'[f],target=targets[t],population=label,alpha=alpha,
                        success=float(ok.mean()),marginal_error=err,log_contrast=con,zero_cells=int((p==0).sum())))
            sm_mix,_,qmix,_,_,_=projections(pn,ne,.5);before=np.zeros_like(qmix);sm_before=np.zeros_like(qmix)
            for b,weight in zip(np.flatnonzero(used),w):
                p=table[f,0,b]/n[f,0,b];sm,ind,q,ok,err,con=projections(p,int(n[f,0,b]),.5)
                before+=weight*q;sm_before+=weight*sm
            for k in range(len(qmix)):
                batchdiag.append(dict(fold='AB'[f],target=targets[t],triplet_index=k,
                    max_projection_order_difference_pp=100*float(abs(qmix[k]-before[k]).max()),
                    max_smoothing_difference_pp=100*float(abs(sm_mix[k]-sm_before[k]).max())))
    pd.DataFrame(checks).to_csv(folder/'pilot_fit_checks.csv',index=False)
    pd.DataFrame(batchdiag).to_csv(folder/'pilot_batch_mixture.csv',index=False)
    passed=all(c['success']>=.99 and c['marginal_error']<=1e-8 and c['log_contrast']<=1e-7 for c in checks)
    write_json(folder/'PILOT_DECISION.json',dict(expand=passed,numerical_only=True))
    if not passed:raise RuntimeError('pilot failed; no threshold retuning or scale-up')
    print('Lower-order pilot passed; expanding descriptive analysis.',flush=True)
    import gzip,csv
    summaries=[]
    for alpha in (.5,.1,1.):
        destination=folder/f'descriptive_alpha_{alpha}.csv.gz';records=[]
        with gzip.open(destination,'wt',newline='') as stream:
            writer=None
            for f in (0,1):
                for t in ids:
                    pp,pn,N,ne,_,_=distributions(table,n,f,t)
                    sp,ip,qp,okp,ep,cp=projections(pp,N,alpha);sn,inn,qn,okn,en,cn=projections(pn,ne,alpha)
                    obs=(pp-pn)[mapping,codes];smooth=(sp-sn)[mapping,codes]
                    di=(ip-inn)[mapping,codes];dq=(qp-qn)[mapping,codes];ok=(okp&okn)[mapping]
                    for j,p in enumerate(patterns):
                        row=dict(fold='AB'[f],target=targets[t],reference_id=p['reference_id'],triplet_index=int(mapping[j]),
                            n_target=N,nt_effective_n=ne,alpha=alpha,delta_observed=obs[j],delta_smoothed=smooth[j],
                            delta_independent=di[j],delta_pairwise=dq[j],residual_independent=obs[j]-di[j],
                            residual_pairwise=obs[j]-dq[j],residual_pairwise_smoothed=smooth[j]-dq[j],
                            smoothing_shift=smooth[j]-obs[j],fit_success=bool(ok[j]))
                        if writer is None:writer=csv.DictWriter(stream,fieldnames=list(row));writer.writeheader()
                        writer.writerow(row)
                    records.append(np.column_stack([obs,di,dq,ok,np.full(len(obs),f)]))
        arr=np.concatenate(records)
        for f in (0,1):
            for label,mask in [('all',arr[:,4]==f),('abs_delta_ge_10pp',(arr[:,4]==f)&(abs(arr[:,0])>=.1))]:
                all_a=arr[mask];a=all_a[all_a[:,3]==1];assert len(a)>0
                for model,col in [('independent',1),('pairwise',2)]:
                    residual=a[:,0]-a[:,col]
                    summaries.append(dict(alpha=alpha,fold='AB'[f],subset=label,model=model,n=len(a),total_rows=len(all_a),
                        success_rate=float(all_a[:,3].mean()),mae_pp=float(abs(residual).mean()*100),
                        rmse_pp=float(np.sqrt(np.mean(residual**2))*100),
                        median_abs_residual_pp=float(np.median(abs(residual))*100),
                        p90_abs_residual_pp=float(np.quantile(abs(residual),.9)*100),
                        median_relative_absolute_error=float(np.median(abs(residual/a[:,0]))) if label!='all' else None,
                        **correlations(a[:,0],a[:,col])))
    pd.DataFrame(summaries).to_csv(folder/'model_summary.csv',index=False)
    return summaries


def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    write_json(out/'STATUS.json',dict(status='running',phase='preparation'))
    try:
        patterns,targets,triplets,cohorts,table,n,mapping,codes=prepare(out)
        locked={}
        for minimum in (100,50):locked[minimum]=discovery(out,minimum,cohorts[str(minimum)],patterns,targets,table,n,mapping,codes)
        barriers={str(p.relative_to(out)):file_hash(p) for p in out.glob('n*/locked_*.json')}
        write_json(out/'ALL_DISCOVERIES_FROZEN_BEFORE_VALIDATION.json',barriers)
        summaries=[];strata=[];common=set(cohorts['100'])
        for minimum in (100,50):
            for source in (0,1):
                frame,s=validation(out/f'n{minimum}',minimum,source,locked[minimum][source],table,n,mapping,codes)
                summaries.append(s)
                if minimum==50:
                    for label,mask in [('common_386',frame.target_index.isin(common)),('added_856',~frame.target_index.isin(common))]:
                        strata.append(dict(stratum=label,direction=s['direction'],**metrics(frame[mask])))
        assert all(file_hash(out/p)==h for p,h in barriers.items())
        pd.DataFrame(summaries).to_csv(out/'replication_summary.csv',index=False)
        pd.DataFrame(strata).to_csv(out/'sensitivity_strata.csv',index=False)
        lower_order(out,cohorts['50'],targets,patterns,table,n,mapping,codes)
        frozen=json.loads((out/'PROTOCOL_FROZEN.json').read_text())
        assert all(file_hash(ROOT/p)==h for p,h in frozen['source_hashes'].items())
        write_json(out/'STATUS.json',dict(status='complete',elapsed_seconds=time.monotonic()-start,
            peak_process_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if sys.platform=='darwin' else 1024),
            cpu_only=True,nt_selection_adjusted=False,confirmatory=False))
    except BaseException as e:
        write_json(out/'STATUS.json',dict(status='failed',error=repr(e)));raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output-dir',required=True);args=p.parse_args();run(args.output_dir)
