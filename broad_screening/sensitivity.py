"""Representation comparisons, matched groups and target bootstrap diagnostics."""
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from landscape_analysis.core import adjusted_rand, hierarchy, silhouette_from_tree
from .analysis import cluster, correlation, vector_r


def resample_schedule(n, triplets, repetitions, seed):
    # Preserve the historical random stream: legacy drew triplet blocks first.
    rng=np.random.default_rng(seed);blocks=np.unique(triplets);out=[]
    for _ in range(repetitions):
        rng.choice(blocks,size=len(blocks),replace=True)
        out.append(rng.integers(0,n,size=n))
    return np.asarray(out)


def align_modules(x, reference, alternative, cores, representatives, refs, run):
    """Best overlap matches with response-centroid tie breaking; many-to-one allowed.

    IDs do not participate in matching except final deterministic tie breaking.
    Match reuse is exported, making splits/merges visible instead of forcing an
    artificial one-to-one correspondence.
    """
    rg=sorted(set(reference)-{'unclustered'});ag=sorted(set(alternative)-{'unclustered'})
    if not ag: return pd.DataFrame([dict(reference_module=g,alternative_run=run,matched_module=None,
        membership_jaccard=0.,centroid_correlation=np.nan,core_recovery=0. if len(cores.get(g,[])) else np.nan,
        representative_pattern_recovered=False,direction_consistency=np.nan,match_status='no_evaluable_group') for g in rg])
    ri=[np.flatnonzero(reference==g) for g in rg];ai=[np.flatnonzero(alternative==g) for g in ag]
    rc=np.array([np.median(x[:,ix],axis=1) for ix in ri]).T
    ac=np.array([np.median(x[:,ix],axis=1) for ix in ai]).T
    cc=correlation(np.c_[rc,ac])[:len(rg),len(rg):]
    rows=[]
    for i,g in enumerate(rg):
        own=set(ri[i]);overlap=np.array([len(own&set(ix)) for ix in ai])
        jac=np.array([ov/(len(own)+len(ix)-ov) for ov,ix in zip(overlap,ai)])
        if overlap.max()==0:
            rows.append(dict(reference_module=g,alternative_run=run,matched_module=None,membership_jaccard=0.,
                centroid_correlation=np.nan,core_recovery=0. if len(cores.get(g,[])) else np.nan,
                representative_pattern_recovered=False,direction_consistency=np.nan,match_status='no_member_overlap'))
            continue
        best=min(range(len(ag)),key=lambda j:(-jac[j],-np.nan_to_num(cc[i,j],nan=-2),ag[j]))
        other=set(ai[best]);core=set(cores.get(g,[]));nonzero=(rc[:,i]!=0)&(ac[:,best]!=0)
        rows.append(dict(reference_module=g,alternative_run=run,matched_module=ag[best],membership_jaccard=jac[best],
            centroid_correlation=cc[i,best],core_recovery=len(core&other)/len(core) if core else np.nan,
            representative_pattern_recovered=bool(representatives.get(g,-1) in other),
            direction_consistency=float((np.sign(rc[nonzero,i])==np.sign(ac[nonzero,best])).mean()) if nonzero.any() else np.nan,
            n_reference_patterns=len(own),n_matched_patterns=len(other),n_shared_patterns=int(overlap[best]),
            reference_members_in_multiple_alternative_groups=len(set(alternative[list(own)])-{'unclustered'}),
            match_status='membership_matched'))
    frame=pd.DataFrame(rows)
    counts=frame.matched_module.value_counts()
    frame['n_reference_modules_sharing_match']=frame.matched_module.map(counts).fillna(0).astype(int)
    return frame


def bootstrap_partitions(x, mass, refs, cfg, schedule, similarity='pearson'):
    co=np.zeros((x.shape[1],x.shape[1]),float);assignments=[]
    for sampled in schedule:
        ids,_=cluster(x[sampled],mass,refs,cfg.clustering_cut,similarity)
        valid=ids!='unclustered'
        co+=(ids[:,None]==ids[None,:])&valid[:,None]&valid[None,:]
        assignments.append(ids)
    return co/len(schedule),np.asarray(assignments)


def primary_stability(d,cfg,groups):
    triplets=np.array([p['candidate_id'] for p in d['patterns']])
    schedule=resample_schedule(len(d['x']),triplets,cfg.bootstrap_repetitions,cfg.seed)
    if not cfg.bootstrap_enabled:
        return np.full((len(groups),len(groups)),np.nan),np.empty((0,len(groups)),str),schedule,dict(status='disabled')
    # Partition traces were not saved by the historical run. Reconstruct them
    # once to provide bootstrap alignment and matched ablation replicates.
    co,labels=bootstrap_partitions(d['x'],d['mask'].sum(0),d['refs'],cfg,schedule)
    compatible=(cfg.seed==d['frozen']['seed'] and cfg.bootstrap_repetitions==d['frozen']['resampling_repetitions']
                and cfg.clustering_cut==d['frozen']['cutoff'])
    diff=float(np.max(np.abs(co-d['co']['pattern']))) if compatible else None
    if compatible and diff>1e-12: raise ValueError('Bootstrap trace reconstruction differs from cached co-assignment')
    return (d['co']['pattern'].copy() if compatible else co),labels,schedule,dict(status='reconstructed_partition_trace',
        cached_coassignment_reused=compatible,max_difference=diff,reason='new per-replicate module alignment and paired ablation')


def sensitivity_and_ablation(d,cfg,groups,co,cores,reps,schedule,primary_boot):
    x,mask,refs=d['x'],d['mask'],d['refs'];mass=mask.sum(0)
    trips=np.array([p['candidate_id'] for p in d['patterns']]);unique=np.unique(trips)
    mapping=np.array([np.flatnonzero(unique==t)[0] for t in trips])
    gene_binary=np.stack([mask[:,trips==t].any(1) for t in unique],axis=1).astype(float)
    cases=[('continuous_pearson',x,'pearson',np.arange(len(refs)),refs,mass),
        ('continuous_spearman',x,'spearman',np.arange(len(refs)),refs,mass),
        ('candidate_binary_state_preserved',mask.astype(float),'pearson',np.arange(len(refs)),refs,mass),
        ('candidate_signed_binary',mask*np.sign(x),'pearson',np.arange(len(refs)),refs,mass),
        ('gene_only_any_candidate',gene_binary,'pearson',mapping,unique,gene_binary.sum(0))]
    robust=[];runstats=[];ablation=[];all_assign=[];boot_align=[];boot_summaries=[];caches={}
    original_corr=correlation(x);tri=np.triu_indices(len(refs),1)
    bridge_corr=correlation(mask.astype(float))
    gene_corr=correlation(gene_binary)[np.ix_(mapping,mapping)]
    common_pairs=np.isfinite(bridge_corr[tri])&np.isfinite(gene_corr[tri])
    gene_sets=[set(p['genes']) for p in d['patterns']]
    disjoint_pairs=np.array([not(gene_sets[a]&gene_sets[b]) for a,b in zip(*tri)])
    cross_triplet=trips[:,None]!=trips[None,:]
    target_primary=d['target_table'].target_group.values
    original_tree=hierarchy(x.T,'correlation',cfg.clustering_cut,optimal=False)
    for name,features,similarity,expand,names,weights in cases:
        labels,tree=cluster(features,weights,names,cfg.clustering_cut,similarity)
        expanded=labels[expand]
        if name=='continuous_pearson':
            bco,boots=co,primary_boot
        elif cfg.bootstrap_enabled:
            bco,boots=bootstrap_partitions(features,weights,names,cfg,schedule,similarity)
        else:
            bco=np.full((features.shape[1],features.shape[1]),np.nan);boots=np.empty((0,features.shape[1]),str)
        eco=bco[np.ix_(expand,expand)]
        caches[name]=(expanded,eco,features[:,expand])
        match=align_modules(x,groups,expanded,cores,reps,refs,name)
        robust.append(match)
        for rep,blabs in enumerate(boots,1):
            eb=blabs[expand]
            a=align_modules(x,groups,eb,cores,reps,refs,name)
            a['replicate']=rep;boot_align.append(a)
            all_assign.extend(dict(run=name,replicate=rep,reference_id=r,module_id=g) for r,g in zip(refs,eb))
        for g in sorted(set(expanded)-{'unclustered'}):
            ix=np.flatnonzero(expanded==g);values=eco[np.ix_(ix,ix)][np.triu_indices(len(ix),1)]
            boot_summaries.append(dict(run=name,module_id=g,n_patterns=len(ix),
                mean_co_clustering=float(np.mean(values)) if len(values) else np.nan))
        valid=expanded!='unclustered';within=(expanded[:,None]==expanded[None,:])&valid[:,None]&valid[None,:]
        between=(expanded[:,None]!=expanded[None,:])&valid[:,None]&valid[None,:]
        w=within[tri];b=between[tri]
        w_cross=(within&cross_triplet)[tri]
        values=rankdata(features,axis=0) if similarity=='spearman' else features
        reprcorr=correlation(values)[np.ix_(expand,expand)]
        evaluable=np.isfinite(reprcorr[tri]);original=original_corr[tri]
        rtree=hierarchy(features,'cosine',cfg.clustering_cut,optimal=False)
        exact_cases=int(mask.sum())
        collapsed_records=int(gene_binary.sum()) if name=='gene_only_any_candidate' else exact_cases
        common_evaluable=common_pairs&np.isfinite(reprcorr[tri])
        common_within=w&common_pairs
        common_between=b&common_pairs
        disjoint_common=common_evaluable&disjoint_pairs
        high_disjoint=disjoint_common&(original>=cfg.context_pearson_min)
        table=dict(representation=name,n_native_features=features.shape[1],n_groups=len(set(labels)-{'unclustered'}),
            n_evaluable_states=int(valid.sum()),pairwise_correlation_coverage=float(evaluable.mean()),
            correlation_preservation_pearson=vector_r(original[evaluable],reprcorr[tri][evaluable]),
            correlation_preservation_mae=float(np.mean(np.abs(original[evaluable]-reprcorr[tri][evaluable]))) if evaluable.any() else np.nan,
            continuous_within_module_coherence=float(np.mean(original[w])) if w.any() else np.nan,
            continuous_between_module_similarity=float(np.mean(original[b])) if b.any() else np.nan,
            separability_within_minus_between=float(np.mean(original[w])-np.mean(original[b])) if w.any() and b.any() else np.nan,
            within_module_stability=float(np.nanmean(eco[tri][w])) if w.any() and cfg.bootstrap_enabled else np.nan,
            cross_triplet_within_stability=float(np.nanmean(eco[tri][w_cross])) if w_cross.any() and cfg.bootstrap_enabled else np.nan,
            target_clustering_ari_vs_continuous=adjusted_rand(target_primary,rtree['labels']),
            source_case_records=exact_cases,representation_case_keys=collapsed_records,
            source_records_merged_by_representation=exact_cases-collapsed_records,
            matching_reference_groups_ari=adjusted_rand(groups[valid],expanded[valid]),
            common_binary_pair_count=int(common_evaluable.sum()),
            common_binary_correlation_mae=float(np.mean(np.abs(original[common_evaluable]-reprcorr[tri][common_evaluable]))),
            common_binary_within_coherence=float(np.mean(original[common_within])) if common_within.any() else np.nan,
            common_binary_between_similarity=float(np.mean(original[common_between])) if common_between.any() else np.nan,
            common_binary_separability=float(np.mean(original[common_within])-np.mean(original[common_between])) if common_within.any() and common_between.any() else np.nan,
            common_binary_within_stability=float(np.mean(eco[tri][common_within])) if common_within.any() and cfg.bootstrap_enabled else np.nan,
            common_cross_triplet_stability=float(np.mean(eco[tri][common_within&cross_triplet[tri]])) if (common_within&cross_triplet[tri]).any() and cfg.bootstrap_enabled else np.nan,
            gene_disjoint_correlation_mae_common=float(np.mean(np.abs(original[disjoint_common]-reprcorr[tri][disjoint_common]))) if disjoint_common.any() else np.nan,
            high_disjoint_pairs_in_common_domain=int(high_disjoint.sum()),
            high_disjoint_pairs_retained_in_representation=int((reprcorr[tri][high_disjoint]>=cfg.context_pearson_min).sum()),
            comparison_scope='descriptive_in_sample; binary bridge isolates state collapse from effect discretization')
        ablation.append(table)
        runstats.append(dict(run=name,cut=cfg.clustering_cut,groups=table['n_groups'],
            excluded_profiles=int((~valid).sum()),adjusted_rand_vs_primary=table['matching_reference_groups_ari']))
        print(f'  sensitivity {name}: {table["n_groups"]} groups',flush=True)
    for cut in cfg.sensitivity_cuts:
        labels,tree=cluster(x,mass,refs,cut)
        name=f'continuous_pearson_cut_{cut:.2f}'
        robust.append(align_modules(x,groups,labels,cores,reps,refs,name))
        runstats.append(dict(run=name,cut=cut,groups=len(set(labels)-{'unclustered'}),excluded_profiles=int((labels=='unclustered').sum()),
            adjusted_rand_vs_primary=adjusted_rand(groups,labels)))
    # Candidate-only effect encoding is distinct from binary candidate identity.
    encoded=np.where(mask,x,0.)
    labels,_=cluster(encoded,mass,refs,cfg.clustering_cut)
    robust.append(align_modules(x,groups,labels,cores,reps,refs,'candidate_only_zero_encoded'))
    runstats.append(dict(run='candidate_only_zero_encoded',cut=cfg.clustering_cut,groups=len(set(labels)-{'unclustered'}),
        excluded_profiles=int((labels=='unclustered').sum()),adjusted_rand_vs_primary=adjusted_rand(groups,labels)))
    rt=pd.concat(robust,ignore_index=True)
    rt['passes_descriptive_alignment_rule']=(rt.membership_jaccard>=cfg.robustness_jaccard_min)&(rt.centroid_correlation>=cfg.robustness_centroid_min)&(
        rt.core_recovery.isna()|(rt.core_recovery>=cfg.robustness_core_recovery_min))
    rt['comparison_kind']=np.where(rt.alternative_run.str.startswith('continuous'),'continuous_profile','representation_change')
    core_comparison=[]
    for g in sorted(cores):
        for enabled in (True,False):
            ix=cores[g] if enabled else np.flatnonzero(groups==g)
            pv=co[np.ix_(ix,ix)][np.triu_indices(len(ix),1)]
            pc=original_corr[np.ix_(ix,ix)][np.triu_indices(len(ix),1)]
            core_comparison.append(dict(module_id=g,stable_core_enabled=enabled,n_patterns=len(ix),
                candidate_records=int(mask[:,ix].sum()),mean_co_clustering=float(pv.mean()) if len(pv) else np.nan,
                within_coherence=float(pc.mean()) if len(pc) else np.nan))
    return dict(robustness=rt,runs=pd.DataFrame(runstats),ablation=pd.DataFrame(ablation),
        bootstrap_alignment=pd.concat(boot_align,ignore_index=True) if boot_align else pd.DataFrame(),
        bootstrap_assignments=pd.DataFrame(all_assign),bootstrap_module_stability=pd.DataFrame(boot_summaries),
        core_ablation=pd.DataFrame(core_comparison),gene_binary=gene_binary,gene_triplets=unique,mapping=mapping)
