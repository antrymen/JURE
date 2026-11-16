"""Statistical structure, exact-state identities and non-causal summaries."""
from collections import Counter
import json
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from scipy.stats import rankdata, spearmanr
from landscape_analysis.core import hierarchy, stable_group_ids


def correlation(x):
    """Column correlations with constant profiles explicitly undefined."""
    x=np.asarray(x,float); z=x-x.mean(0)
    norms=np.linalg.norm(z,axis=0)
    return np.divide(z.T@z,np.outer(norms,norms),out=np.full((x.shape[1],x.shape[1]),np.nan),
                     where=np.outer(norms,norms)>1e-20).clip(-1,1)


def vector_r(a,b):
    a,b=np.asarray(a,float),np.asarray(b,float)
    valid=np.isfinite(a)&np.isfinite(b)
    if valid.sum()<3 or np.std(a[valid])<1e-12 or np.std(b[valid])<1e-12: return np.nan
    return float(correlation(np.c_[a[valid],b[valid]])[0,1])


def cluster(x, mass, refs, cut=.3, similarity='pearson'):
    features=rankdata(x,axis=0) if similarity=='spearman' else x
    tree=hierarchy(features.T,'correlation',cut,optimal=False)
    ids=stable_group_ids(tree['labels'],mass,refs,'M')
    return ids,tree


def choose_core(co, indices, refs, threshold=.8, min_size=2):
    """Largest complete-linkage block: every pair meets the frozen threshold.

    This is a deterministic block rule, not a maximum-clique claim. Ties use
    average pair stability then sorted reference IDs. Singletons have no core.
    """
    indices=np.asarray(indices,int)
    if len(indices)<min_size or not np.isfinite(co[np.ix_(indices,indices)]).all(): return np.array([],int)
    sub=co[np.ix_(indices,indices)]
    dist=np.clip(1-sub,0,1); np.fill_diagonal(dist,0)
    labs=fcluster(linkage(squareform(dist,checks=False),method='complete'),
                  np.nextafter(1-threshold,np.inf),criterion='distance')
    groups=[indices[labs==v] for v in np.unique(labs) if (labs==v).sum()>=min_size]
    def key(ix):
        pairs=co[np.ix_(ix,ix)][np.triu_indices(len(ix),1)]
        return (-len(ix),-float(pairs.mean()),tuple(sorted(refs[ix])))
    return sorted(groups,key=key)[0] if groups else np.array([],int)


def medoid(indices, corr, mass, x, co, refs):
    ix=np.asarray(indices,int)
    means=np.nanmean(corr[np.ix_(ix,ix)],axis=1)
    stability=np.nanmean(co[np.ix_(ix,ix)],axis=1) if np.isfinite(co[np.ix_(ix,ix)]).any() else np.zeros(len(ix))
    choices=sorted(range(len(ix)),key=lambda q:(-means[q],-stability[q],-mass[ix[q]],
                  -np.median(np.abs(x[:,ix[q]])),refs[ix[q]]))
    return int(ix[choices[0]])


def modules(d, cfg, groups, co):
    x,mask,refs,patterns=d['x'],d['mask'],d['refs'],d['patterns']
    corr=correlation(x); mass=mask.sum(0)
    summaries=[]; membership=[]; cores={}; reps={}; activity={}; zmean={}; unstable=[]
    z=(x-x.mean(0))/x.std(0)
    for group in sorted(set(groups)-{'unclustered'}):
        ix=np.flatnonzero(groups==group); sub=co[np.ix_(ix,ix)]
        pv=sub[np.triu_indices(len(ix),1)]
        core=choose_core(co,ix,refs,cfg.stable_core_pair_probability,cfg.stable_core_min_size) if cfg.stable_core_enabled else np.array([],int)
        cores[group]=core
        representative=medoid(ix,corr,mass,x,co,refs); reps[group]=representative
        count=int(mask[:,ix].sum()); enrich=int(((x[:,ix]>0)&mask[:,ix]).sum());deplete=count-enrich
        gene_counts=Counter(g for j in ix for g in patterns[j]['genes'])
        pair_corr=corr[np.ix_(ix,ix)][np.triu_indices(len(ix),1)]
        jacc=[]
        for a,b in zip(*np.triu_indices(len(ix),1)):
            ga,gb=set(patterns[ix[a]]['genes']),set(patterns[ix[b]]['genes'])
            jacc.append(len(ga&gb)/len(ga|gb))
            if np.isfinite(sub[a,b]) and sub[a,b]<cfg.stable_core_pair_probability:
                unstable.append(dict(module_id=group,reference_a=refs[ix[a]],reference_b=refs[ix[b]],co_clustering=sub[a,b]))
        core_set=set(core)
        boundary=[j for j in ix if j not in core_set]
        summary=dict(module_id=group,n_patterns=len(ix),n_triplets=len({patterns[j]['candidate_id'] for j in ix}),
            n_candidates=count,n_targets=int(mask[:,ix].any(1).sum()),fraction_of_all_candidates=count/int(mask.sum()),
            n_enrichment=enrich,n_depletion=deplete,
            dominant_direction='enrichment' if enrich>deplete else 'depletion' if deplete>enrich else 'balanced' if count else 'no_candidates',
            fraction_enrichment=enrich/count if count else np.nan,fraction_depletion=deplete/count if count else np.nan,
            representative_reference_id=refs[representative],representative_signed_pattern=patterns[representative]['pattern'],
            representative_rule='response_correlation_medoid',
            stable_core_patterns=json.dumps(list(refs[core])),boundary_patterns=json.dumps(list(refs[boundary])),
            stable_core_size=len(core),boundary_size=len(boundary),core_fraction=len(core)/len(ix),boundary_fraction=len(boundary)/len(ix),
            mean_co_clustering=float(pv.mean()) if len(pv) else np.nan,
            median_co_clustering=float(np.median(pv)) if len(pv) else np.nan,
            min_co_clustering=float(pv.min()) if len(pv) else np.nan,
            q10_co_clustering=float(np.quantile(pv,.1)) if len(pv) else np.nan,
            within_module_similarity=float(np.mean(pair_corr)) if len(pair_corr) else np.nan,
            mean_gene_jaccard=float(np.mean(jacc)) if jacc else np.nan,
            all_genes=json.dumps(sorted(gene_counts)),top_genes='; '.join(g for g,_ in gene_counts.most_common(8)),
            signed_state_summary=json.dumps([patterns[j]['pattern'] for j in ix]),
            stability_scope='internal_target_bootstrap' if cfg.bootstrap_enabled else 'not_assessed')
        summaries.append(summary)
        activity[group]=np.median(x[:,ix],axis=1); zmean[group]=z[:,ix].mean(1)
        for j in ix:
            peers=ix[ix!=j]
            status=('not_assessed' if not cfg.bootstrap_enabled or not cfg.stable_core_enabled else
                    'singleton_unassessable' if len(ix)==1 else 'stable_core' if j in core_set else 'boundary')
            membership.append(dict(reference_id=refs[j],signed_pattern=patterns[j]['pattern'],module_id=group,
                core_or_boundary=status,mean_co_clustering_to_group=float(np.mean(co[j,peers])) if len(peers) else np.nan,
                min_co_clustering_to_core=float(np.min(co[j,core[core!=j]])) if len(core[core!=j]) else np.nan,
                representative=bool(j==representative)))
    return (pd.DataFrame(summaries).sort_values(['n_candidates','module_id'],ascending=[False,True]),
        pd.DataFrame(membership),cores,reps,pd.DataFrame(activity,index=pd.Index(d['targets'],name='target')),
        pd.DataFrame(zmean,index=pd.Index(d['targets'],name='target')),pd.DataFrame(unstable))


def pair_analysis(d,groups):
    x,mask,patterns,refs=d['x'],d['mask'],d['patterns'],d['refs']
    pearson=correlation(x); spearman=correlation(rankdata(x,axis=0));rows=[]
    for a in range(len(refs)):
        ga=set(patterns[a]['genes']); sa=dict(zip(patterns[a]['genes'],patterns[a]['states']))
        for b in range(a+1,len(refs)):
            gb=set(patterns[b]['genes']);sb=dict(zip(patterns[b]['genes'],patterns[b]['states']))
            overlap=ga&gb; shared=mask[:,a]&mask[:,b]; union=mask[:,a]|mask[:,b]
            nonzero=(x[:,a]!=0)&(x[:,b]!=0);concord=np.sign(x[:,a])==np.sign(x[:,b])
            rows.append(dict(reference_a=refs[a],reference_b=refs[b],pattern_a=patterns[a]['pattern'],pattern_b=patterns[b]['pattern'],
                genes_a=json.dumps(patterns[a]['genes']),genes_b=json.dumps(patterns[b]['genes']),
                states_a=json.dumps(patterns[a]['states']),states_b=json.dumps(patterns[b]['states']),
                module_a=groups[a],module_b=groups[b],same_triplet=bool(ga==gb),shared_gene_count=len(overlap),
                gene_overlap='; '.join(sorted(overlap)),gene_jaccard=len(overlap)/len(ga|gb),
                signed_state_overlap=sum(sa[g]==sb[g] for g in overlap),state_disagreements=sum(sa[g]!=sb[g] for g in overlap),
                pearson_r=pearson[a,b],spearman_rho=spearman[a,b],n_common_evaluable_targets=len(x),
                n_shared_candidate_targets=int(shared.sum()),candidate_jaccard=shared.sum()/union.sum() if union.sum() else np.nan,
                direction_concordance=float(concord[nonzero].mean()) if nonzero.any() else np.nan,
                n_nonzero_pair_targets=int(nonzero.sum()),
                candidate_direction_concordance=float(concord[shared].mean()) if shared.any() else np.nan))
    table=pd.DataFrame(rows).sort_values(['pearson_r','reference_a','reference_b'],ascending=[False,True,True])
    distributions=[]
    for overlap,subset in table.groupby('shared_gene_count'):
        for metric in ('pearson_r','spearman_rho'):
            v=subset[metric].dropna().values
            distributions.append(dict(shared_gene_count=int(overlap),metric=metric,n_pairs=len(v),
                median=np.median(v),q05=np.quantile(v,.05),q95=np.quantile(v,.95),q99=np.quantile(v,.99),
                minimum=v.min(),maximum=v.max(),mean=v.mean(),fraction_ge_08=float((v>=.8).mean()),
                n_ge_08=int((v>=.8).sum()),fraction_le_minus08=float((v<=-.8).mean())))
    return table,pd.DataFrame(distributions),pearson,spearman


def module_relationships(d,groups,summary,activity,zmean):
    patterns=d['patterns'];index={g:np.flatnonzero(groups==g) for g in activity.columns}
    reps=summary.set_index('module_id');corr=activity.corr();zcorr=zmean.corr();rows=[]
    for a,ga in enumerate(activity.columns):
        ia=index[ga];genes_a={g for j in ia for g in patterns[j]['genes']}; ca=d['mask'][:,ia].any(1)
        for gb in activity.columns[a+1:]:
            ib=index[gb];genes_b={g for j in ib for g in patterns[j]['genes']}; cb=d['mask'][:,ib].any(1)
            value=corr.loc[ga,gb]
            rows.append(dict(module_a=ga,module_b=gb,shared_genes='; '.join(sorted(genes_a&genes_b)),
                gene_overlap=len(genes_a&genes_b),gene_jaccard=len(genes_a&genes_b)/len(genes_a|genes_b),
                representative_state_a=reps.loc[ga,'representative_signed_pattern'],
                representative_state_b=reps.loc[gb,'representative_signed_pattern'],
                activity_correlation=value,legacy_zmean_correlation=zcorr.loc[ga,gb],
                direction_relation='opposing' if value<0 else 'same_sign_correlation' if value>0 else 'zero_correlation',
                n_shared_candidate_targets=int((ca&cb).sum()),candidate_target_jaccard=(ca&cb).sum()/(ca|cb).sum() if (ca|cb).any() else np.nan))
    return pd.DataFrame(rows),corr,zcorr


def burden_and_concentration(d,groups,activity):
    x,mask,patterns=d['x'],d['mask'],d['patterns']; rows=[];prows=[];curves=[]
    for i,target in enumerate(d['targets']):
        observed=x[i];chosen=observed[mask[i]]
        rows.append(dict(target=target,n_candidates=int(mask[i].sum()),candidate_burden_raw=int(mask[i].sum()),
            n_enrichment=int((chosen>0).sum()),n_depletion=int((chosen<0).sum()),
            median_abs_delta=np.median(np.abs(chosen)),max_abs_delta=np.max(np.abs(chosen)),mean_abs_delta=np.mean(np.abs(chosen)),
            mean_abs_delta_all=np.mean(np.abs(observed)),max_abs_delta_all=np.max(np.abs(observed)),
            n_distinct_pattern_groups=len(set(groups[mask[i]])),target_cell_count=int(d['stats']['target_n'][d['rows'][i]]),
            target_cluster=d['target_table'].iloc[i]['target_group']))
    for j,p in enumerate(patterns):
        v=x[:,j];q=mask[:,j]
        prows.append(dict(reference_id=p['reference_id'],genes=json.dumps(p['genes']),states=json.dumps(p['states']),
            exact_signed_state=p['pattern'],triplet_id=p['candidate_id'],bidirectional_reference_flag=p['bidirectionally_qualified'],
            reference_prevalence=p['nt_frequency'],reference_prevalence_definition='pooled_Day6_NT_descriptive',
            n_targets=int(q.sum()),n_enrichment_targets=int((q&(v>0)).sum()),n_depletion_targets=int((q&(v<0)).sum()),
            median_delta=np.median(v),median_abs_delta=np.median(np.abs(v)),max_abs_delta=np.max(np.abs(v)),
            candidate_median_delta=np.median(v[q]) if q.any() else np.nan,module_id=groups[j],
            delta_units='percentage_points',effect_summary_population='all_main_cohort_targets'))
    table=pd.DataFrame(rows);pburden=pd.DataFrame(prows)
    mass=mask.sum(0);ids=d['refs']
    for unit,keys,values in [('pattern',ids,mass),('module',sorted(set(groups)),
        [int(mass[groups==g].sum()) for g in sorted(set(groups))])]:
        ordered=sorted(zip(keys,values),key=lambda v:(-v[1],v[0]));cum=0
        for rank,(key,value) in enumerate(ordered,1):
            cum+=value;curves.append(dict(unit=unit,rank=rank,identity=key,candidates=value,cumulative_candidates=cum,cumulative_fraction=cum/int(mask.sum())))
    sample=[]
    for field in ['n_candidates','mean_abs_delta','max_abs_delta','n_distinct_pattern_groups','mean_abs_delta_all','max_abs_delta_all']:
        rho=spearmanr(table.target_cell_count,table[field]).statistic
        sample.append(dict(cohort='candidate_bearing_targets',n_targets=len(table),predictor='target_cell_count',response=field,spearman_rho=rho,
                           interpretation='descriptive_association_not_power_adjustment'))
    return table,pburden,pd.DataFrame(curves),pd.DataFrame(sample)
