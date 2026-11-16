"""python -m broad_screening.run --output outputs/broad_screening_v01"""
from __future__ import annotations
import os
for _v in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
    os.environ[_v]='1'
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import numpy as np
import pandas as pd
import scipy
import yaml
from scipy.cluster.hierarchy import leaves_list
from scipy.stats import spearmanr
from .config import Config
from .io import ROOT,DEFAULT_LEGACY,DEFAULT_SCAN,DEFAULT_OUTPUT,load,sha,dump,jsonl,csv
from .analysis import (cluster,modules,pair_analysis,module_relationships,burden_and_concentration)
from .sensitivity import primary_stability,sensitivity_and_ablation,align_modules
from .triage import build_interfaces


def write_matrix(path,values,rows,cols,index_name='target'):
    pd.DataFrame(values,index=pd.Index(rows,name=index_name),columns=cols).to_csv(path,na_rep='NA')


def distribution(values,label):
    v=np.asarray(values).ravel();v=v[np.isfinite(v)]
    return dict(variable=label,n=len(v),minimum=float(v.min()) if len(v) else None,
        q25=float(np.quantile(v,.25)) if len(v) else None,median=float(np.median(v)) if len(v) else None,
        q75=float(np.quantile(v,.75)) if len(v) else None,maximum=float(v.max()) if len(v) else None,
        mean=float(v.mean()) if len(v) else None)


def export_figure_data(out,d,summary,membership,co,activity,zmean,pairs,pca,scores,burden,sample,robustness,ablation,overlap):
    f=out/'figure_data';ro=d['trees']['target_order'];po=d['trees']['pattern_order']
    write_matrix(f/'A_landscape_matrix.csv',d['x'][np.ix_(ro,po)],d['targets'][ro],d['refs'][po])
    np.savez_compressed(f/'A_linkage.npz',**d['trees'])
    csv(f/'A_pattern_order.csv',membership.set_index('reference_id').loc[d['refs'][po]].reset_index())
    csv(f/'A_target_order.csv',d['target_table'].iloc[ro].reset_index()[['target','target_group']])
    csv(f/'B_module_cards.csv',summary.head(4))
    csv(f/'C_pca_variance.csv',pca)
    csv(f/'C_pca_scores.csv',scores.reset_index().merge(burden[['target','target_cluster']],on='target',validate='1:1'))
    disjoint=pairs.loc[pairs.shared_gene_count==0].iloc[0]
    same=pairs.loc[pairs.same_triplet & (pairs.n_shared_candidate_targets>0)].sort_values(['pearson_r','reference_a','reference_b']).iloc[0]
    refs={r:i for i,r in enumerate(d['refs'])};meta={}
    for letter,pair in [('D',disjoint),('E',same)]:
        a,b=refs[pair.reference_a],refs[pair.reference_b]
        frame=pd.DataFrame(dict(target=d['targets'],delta_a_pp=d['x'][:,a],delta_b_pp=d['x'][:,b],
             candidate_a=d['mask'][:,a],candidate_b=d['mask'][:,b],both_candidates=d['mask'][:,a]&d['mask'][:,b]))
        csv(f/('D_gene_disjoint_example.csv' if letter=='D' else 'E_signed_state_contrast.csv'),frame)
        meta[letter]=pair.to_dict()
    leading=summary.module_id.head(2).tolist()
    csv(f/'E_module_activity_contrast.csv',activity[leading].reset_index())
    meta['E_modules']=dict(module_a=leading[0],module_b=leading[1],median_correlation=activity[leading].corr().iloc[0,1],
        zmean_correlation=zmean[leading].corr().iloc[0,1])
    csv(f/'F_module_stability.csv',summary.head(12))
    csv(f/'G_sample_size_dependence.csv',burden)
    csv(f/'G_sample_size_correlations.csv',sample)
    csv(f/'H_module_robustness.csv',robustness)
    csv(f/'H_signed_state_ablation.csv',ablation)
    csv(f/'I_gene_overlap_summary.csv',overlap)
    hist=[]
    bins=np.linspace(-1,1,41)
    for n,subset in pairs.groupby('shared_gene_count'):
        counts,_=np.histogram(subset.pearson_r,bins=bins)
        hist.extend(dict(shared_gene_count=int(n),left=a,right=b,n_pairs=int(c),fraction=c/len(subset))
                    for a,b,c in zip(bins[:-1],bins[1:],counts))
    csv(f/'I_gene_overlap_histogram.csv',pd.DataFrame(hist))
    meta['A']=dict(n_targets=len(d['targets']),n_patterns=len(d['refs']),n_candidates=int(d['mask'].sum()),
        n_enrichment=int(((d['x']>0)&d['mask']).sum()),n_depletion=int(((d['x']<0)&d['mask']).sum()),
        vlim_pp=float(np.ceil(np.abs(d['x']).max()/5)*5),normalization='asinh',linear_width_pp=5)
    dump(f/'plot_metadata.json',meta)
    dump(f/'FROZEN.json',dict(files_sha256={p.name:sha(p) for p in sorted(f.iterdir()) if p.is_file()},
                            rule='Plot functions may only read these prepared data; no analytical recomputation.'))
    return meta


def run(legacy,scan,out,cfg):
    cfg.validate()
    if out.exists():raise FileExistsError('Refusing to overwrite an existing run; use a fresh output path')
    out.mkdir(parents=True)
    for sub in ('tables','matrices','annotation_inputs','agent_inputs','figure_data','figures','audit'):(out/sub).mkdir()
    code={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'broad_screening').glob('*.py')}
    for p in (ROOT/'landscape_analysis').glob('*.py'):code[str(p.relative_to(ROOT))]=sha(p)
    frozen=dict(created_utc=datetime.now(timezone.utc).isoformat(),config=cfg.to_dict(),
        units='effect matrices and module activity in percentage points; candidate delta retains original fraction',
        primary_cohort='targets with at least one frozen exploratory candidate',primary_representation='continuous_signed_delta',
        primary_similarity='Pearson',target_similarity='cosine',linkage='average',module_activity='median_signed_delta',
        representative_rule='correlation medoid; ties: pair stability, candidate coverage, median absolute effect, reference ID',
        stable_core_rule='largest complete-linkage block at fixed pairwise coassignment threshold; minimum size two',
        gene_only_collapse='target-wise OR of candidate masks within the exact same gene triplet',
        specificity_definition='absolute median activity / sum absolute median activities over groups with >=3 patterns and >=2 triplets',
        strong_group_definition='abs(median delta) >= configured pp threshold in eligible groups',
        module_specific_definition='exactly one strong eligible group and its specificity >= configured threshold',
        cross_module_definition='at least two strong eligible groups',
        sample_size_sensitive_definition='near-support-floor or high-support sample-size stratum; individual sensitivity not estimated',
        redundancy_definition='same target, response group and effect direction; descriptive sampling block only',
        models_called=0,external_retrieval_calls=0,day8_accessed=False,biological_annotation_performed=False,
        source_code_sha256=code)
    (out/'audit/config_frozen.yaml').write_text(yaml.safe_dump(frozen,sort_keys=False,allow_unicode=True))
    print('Configuration frozen; auditing prior artifacts and original Day 6 sources.',flush=True)
    d=load(legacy,scan)
    dump(out/'audit/input_hashes.json',d['hashes'])
    x,mask,refs,targets=d['x'],d['mask'],d['refs'],d['targets'];stats=d['stats']
    if cfg.clustering_cut==d['frozen']['cutoff']:
        groups=d['pattern_table'].pattern_group.values.copy()
    else:
        groups,tree=cluster(x,mask.sum(0),refs,cfg.clustering_cut)
        d['trees']['pattern_linkage']=tree['linkage'];d['trees']['pattern_order']=tree['order']
    for prefix in ('target','pattern'):
        if not np.array_equal(leaves_list(d['trees'][prefix+'_linkage']),d['trees'][prefix+'_order']):raise ValueError('Tree/order mismatch')
    sel=np.ix_(d['rows'],d['cols']);reason=stats['reason'][sel];tested=stats['tested'][sel]
    adequate=np.isfinite(stats['delta'])&(stats['target_n'][:,None]>=d['scan_summary']['config']['min_pert_cells'])&(
        ~np.char.startswith(stats['reason'].astype(str),'insufficient'))
    support=adequate[sel]
    status=np.where(stats['candidate'],np.where(stats['delta']>0,'candidate_enrichment','candidate_depletion'),
        np.where(stats['tested'],'tested_not_qualified','not_tested:'+stats['reason'].astype(str)))
    if np.any(mask&(~tested|~support)):raise ValueError('Selected candidate lacks testing/support')
    for name,values in [('effect_matrix',x),('candidate_mask',mask.astype(int)),('tested_mask',tested.astype(int)),
        ('support_mask',support.astype(int)),('reason_matrix',reason),('status_matrix',status[sel]),('candidate_only_effect',np.where(mask,x,np.nan))]:
        write_matrix(out/'matrices'/f'{name}.csv.gz',values,targets,refs)
    all_refs=[p['reference_id'] for p in d['identity']['patterns']]
    for name,values in [('all_targets_effect_matrix',np.where(adequate,stats['delta']*100,np.nan)),
        ('all_targets_candidate_mask',stats['candidate'].astype(int)),('all_targets_tested_mask',stats['tested'].astype(int)),
        ('all_targets_support_mask',adequate.astype(int)),('all_targets_reason_matrix',stats['reason']),('all_targets_status_matrix',status)]:
        write_matrix(out/'matrices'/f'{name}.csv.gz',values,d['identity']['targets'],all_refs)
    print('Computing bootstrap partition traces, cores and response-pair statistics.',flush=True)
    co,boot,schedule,boot_diagnostic=primary_stability(d,cfg,groups)
    write_matrix(out/'matrices/co_clustering_matrix.csv.gz',co,refs,refs,'reference_id')
    np.save(out/'audit/bootstrap_target_indices.npy',schedule)
    summary,membership,cores,reps,activity,zmean,unstable=modules(d,cfg,groups,co)
    csv(out/'tables/module_summary.csv',summary);csv(out/'tables/stable_core_membership.csv',membership)
    csv(out/'tables/module_stability.csv',summary[['module_id','n_patterns','mean_co_clustering','median_co_clustering',
        'min_co_clustering','q10_co_clustering','stable_core_size','boundary_size','core_fraction','boundary_fraction']])
    csv(out/'tables/unstable_pattern_pairs.csv',unstable)
    activity.to_csv(out/'tables/target_module_activity.csv',na_rep='NA')
    zmean.to_csv(out/'tables/target_module_activity_legacy_zmean.csv',na_rep='NA')
    pairs,overlap,pearson,spearman=pair_analysis(d,groups)
    csv(out/'tables/pattern_pair_similarity.csv.gz',pairs)
    csv(out/'tables/gene_overlap_response_similarity.csv',overlap)
    csv(out/'tables/top_correlated_disjoint_gene_patterns.csv',pairs.loc[pairs.shared_gene_count==0].head(cfg.top_pairs))
    csv(out/'tables/same_genes_different_states.csv',pairs.loc[pairs.same_triplet | ((pairs.shared_gene_count>=2)&(pairs.state_disagreements>0))])
    write_matrix(out/'matrices/pattern_pearson.csv.gz',pearson,refs,refs,'reference_id')
    write_matrix(out/'matrices/pattern_spearman.csv.gz',spearman,refs,refs,'reference_id')
    rel,mc,zc=module_relationships(d,groups,summary,activity,zmean)
    csv(out/'tables/module_relationships.csv',rel)
    csv(out/'tables/signed_state_contrast_pairs.csv',rel.loc[(rel.gene_overlap>0)&(rel.activity_correlation<0)])
    mc.to_csv(out/'matrices/module_activity_correlation.csv');zc.to_csv(out/'matrices/module_activity_legacy_zmean_correlation.csv')
    burden,pburden,concentration,sample=burden_and_concentration(d,groups,activity)
    all_rows=[]
    for i,t in enumerate(d['identity']['targets']):
        q=stats['candidate'][i,d['cols']];v=stats['delta'][i,d['cols']]*100
        good=adequate[i,d['cols']];observed=v[good];chosen=v[q]
        all_rows.append(dict(target=t,target_cell_count=int(stats['target_n'][i]),n_candidates=int(q.sum()),
            n_enrichment=int((chosen>0).sum()),n_depletion=int((chosen<0).sum()),
            n_modules_hit=len(set(groups[q])),has_candidates=bool(q.any()),all_patterns_evaluable=bool(good.all()),
            median_abs_delta=float(np.median(np.abs(chosen))) if len(chosen) else np.nan,
            mean_abs_delta=float(np.mean(np.abs(chosen))) if len(chosen) else np.nan,
            max_abs_delta=float(np.max(np.abs(chosen))) if len(chosen) else np.nan,
            mean_abs_delta_all=float(np.mean(np.abs(observed))) if len(observed) else np.nan,
            max_abs_delta_all=float(np.max(np.abs(observed))) if len(observed) else np.nan))
    all_burden=pd.DataFrame(all_rows);csv(out/'tables/all_targets_burden.csv',all_burden)
    extra=[]
    for label,cohort in [('all_scan_targets',all_burden),('all_adequate_targets',all_burden.loc[all_burden.all_patterns_evaluable])]:
        for field in ('n_candidates','n_modules_hit','mean_abs_delta_all','max_abs_delta_all'):
            available=cohort[['target_cell_count',field]].dropna()
            extra.append(dict(cohort=label,n_targets=len(available),predictor='target_cell_count',response=field,
                spearman_rho=spearmanr(available.target_cell_count,available[field]).statistic,
                interpretation='descriptive_association; all_scan includes support-gated zeros' if label=='all_scan_targets' else 'descriptive_association_not_power_adjustment'))
    sample=pd.concat([sample,pd.DataFrame(extra)],ignore_index=True)
    for name,t in [('target_burden',burden),('pattern_burden',pburden),('candidate_concentration',concentration),('sample_size_dependence',sample)]:
        csv(out/'tables'/f'{name}.csv',t)
    csv(out/'tables/target_clusters.csv',burden[['target','target_cluster','target_cell_count','n_candidates']])
    # Retain audited historical cohort/weighting sensitivities as supplementary context.
    csv(out/'tables/legacy_cohort_weighting_sensitivity.csv',pd.read_csv(legacy/'tables/clustering_sensitivity.csv'))
    # Complete PCA exports were absent in the first run (only ten score/loading columns).
    u,s,vt=np.linalg.svd(x-x.mean(0),full_matrices=False);ev=s*s/(s*s).sum()
    pca=pd.DataFrame(dict(component=np.arange(1,len(s)+1),variance_explained_ratio=ev,cumulative_variance=ev.cumsum()))
    old_pca=pd.read_csv(legacy/'tables/pca_variance.csv')
    pca_diff=float(np.max(np.abs(old_pca.explained_variance.values-ev)))
    csv(out/'tables/pca_variance.csv',pca)
    scores=pd.DataFrame(u*s,index=pd.Index(targets,name='target'),columns=[f'PC{i+1}' for i in range(len(s))])
    scores.to_csv(out/'tables/pca_target_scores.csv')
    pd.DataFrame(vt.T,index=pd.Index(refs,name='reference_id'),columns=scores.columns).to_csv(out/'tables/pca_pattern_loadings.csv')
    print('Comparing similarity, selection encodings, gene-only collapse and clustering cuts.',flush=True)
    sensitivity=sensitivity_and_ablation(d,cfg,groups,co,cores,reps,schedule,boot)
    for key,name in [('robustness','module_robustness'),('runs','clustering_sensitivity'),('ablation','signed_state_ablation'),
        ('bootstrap_alignment','bootstrap_module_alignment'),('bootstrap_assignments','bootstrap_pattern_assignments'),
        ('bootstrap_module_stability','ablation_module_stability'),('core_ablation','stable_core_ablation')]:
        csv(out/'tables'/f'{name}.csv.gz' if key in ('bootstrap_alignment','bootstrap_assignments') else out/'tables'/f'{name}.csv',sensitivity[key])
    write_matrix(out/'matrices/gene_only_any_candidate.csv.gz',sensitivity['gene_binary'],targets,sensitivity['gene_triplets'])
    history=align_modules(x,d['pattern_table'].pattern_group.values,groups,cores,reps,refs,'current_vs_historical')
    csv(out/'audit/historical_module_alignment.csv',history)
    print('Building traceable annotation objects and the unselected case pool.',flush=True)
    interfaces=build_interfaces(d,cfg,groups,summary,membership,cores,reps,activity,pairs,burden,sensitivity['robustness'],co)
    for key,name in [('table','case_triage_table'),('strata','case_strata_summary'),('compression','case_pool_compression'),
        ('specific','module_specific_targets'),('cross','cross_module_targets'),('disjoint_context_pairs','gene_disjoint_case_context_pairs'),
        ('contrast_context_pairs','signed_state_case_context_pairs')]:csv(out/'tables'/f'{name}.csv',interfaces[key])
    jsonl(out/'agent_inputs/deep_case_pool.jsonl',interfaces['pool'])
    jsonl(out/'annotation_inputs/module_annotation_input.jsonl',interfaces['annotation_objects'])
    dist=[distribution(x,'all_main_cohort_delta_pp'),distribution(x[mask],'candidate_delta_pp'),
        distribution(x[mask&(x>0)],'positive_candidate_delta_pp'),distribution(x[mask&(x<0)],'negative_candidate_delta_pp'),
        distribution(burden.target_cell_count,'candidate_bearing_target_cell_count'),
        distribution(stats['target_n'],'all_target_cell_count'),distribution(pburden.reference_prevalence,'pooled_reference_prevalence')]
    csv(out/'tables/global_distributions.csv',pd.DataFrame(dist))
    coverage={}
    pc=concentration.loc[concentration.unit=='pattern']
    for fraction in (.5,.6,.7,.8,.9):coverage[str(int(fraction*100))]=int(pc.loc[pc.cumulative_fraction>=fraction,'rank'].iloc[0])
    global_summary=dict(n_targets_total=len(d['identity']['targets']),n_targets_with_candidates=len(targets),
        n_patterns_total=len(refs),n_patterns_with_candidates=int(mask.any(0).sum()),n_candidates=int(mask.sum()),
        n_targets_adequate=int(all_burden.all_patterns_evaluable.sum()),
        n_enrichment=int((mask&(x>0)).sum()),n_depletion=int((mask&(x<0)).sum()),
        n_modules=len(summary),n_stable_cores=int((summary.stable_core_size>=cfg.stable_core_min_size).sum()),
        n_patterns_in_stable_cores=int(summary.stable_core_size.sum()),pattern_counts_for_coverage=coverage,
        top_module_coverage={str(k):float(concentration.loc[(concentration.unit=='module')&(concentration['rank']==k),'cumulative_fraction'].iloc[0]) for k in (1,2,3,4)},
        pca_first3=float(ev[:3].sum()),pca_first4=float(ev[:4].sum()),
        candidate_burden_cell_count_rho=float(sample.loc[sample.response=='n_candidates','spearman_rho'].iloc[0]),
        models_called=0,day8_accessed=False,biological_names_assigned=False,selected_deep_cases=0)
    dump(out/'SUMMARY.json',global_summary)
    meta=export_figure_data(out,d,summary,membership,co,activity,zmean,pairs,pca,scores,burden,sample,sensitivity['robustness'],sensitivity['ablation'],overlap)
    dump(out/'audit/reproduction_metrics.json',dict(bootstrap=boot_diagnostic,pca_max_variance_difference=pca_diff,
        module_alignment_min_jaccard=float(history.membership_jaccard.min()),
        legacy_summary=d['legacy_summary'],current_summary=global_summary,
        leading_module_activity_comparison=meta['E_modules'],disjoint_example=meta['D']))
    from .report import make_reports
    make_reports(out,d,cfg,global_summary,summary,membership,cores,sensitivity,interfaces,overlap,meta)
    (out/'figures/README.md').write_text('本轮按用户最新要求暂不制作图表。冻结作图数据位于 ../figure_data/；未生成 PNG、SVG 或 PDF。\n')
    from .verify import verify
    verification=verify(out,d,cfg)
    dump(out/'audit/integrity_check.json',verification)
    if verification['status']!='passed':raise ValueError('Output integrity checks failed')
    if any(sha(Path(p))!=digest for p,digest in d['hashes'].items()):raise ValueError('Source changed during execution')
    manifest=dict(created_utc=datetime.now(timezone.utc).isoformat(),status='complete',config=frozen,
        source_legacy=str(legacy),source_scan=str(scan),input_sha256=d['hashes'],
        python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,scipy=scipy.__version__,
        artifacts_sha256={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()})
    dump(out/'audit/run_manifest.json',manifest)
    print(json.dumps(dict(status='complete',output=str(out),candidates=len(interfaces['table']),modules=len(summary)),ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--legacy',type=Path,default=DEFAULT_LEGACY);p.add_argument('--scan',type=Path,default=DEFAULT_SCAN)
    p.add_argument('--output',type=Path,default=DEFAULT_OUTPUT);p.add_argument('--config',type=Path)
    p.add_argument('--bootstrap-repetitions',type=int);p.add_argument('--dpi',type=int)
    args=p.parse_args();options=yaml.safe_load(args.config.read_text()) if args.config else {}
    if args.bootstrap_repetitions is not None:options['bootstrap_repetitions']=args.bootstrap_repetitions
    if args.dpi is not None:options['dpi']=args.dpi
    run(args.legacy.resolve(),args.scan.resolve(),args.output.resolve(),Config(**options))
