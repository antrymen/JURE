"""Descriptive strata and source-preserving candidate interfaces, without selection."""
from collections import defaultdict
import json
import numpy as np
import pandas as pd
from .analysis import correlation,medoid
from .io import clean_json


def build_interfaces(d,cfg,groups,summary,membership,cores,reps,activity,pairs,target_burden,robustness,co):
    targets,refs,patterns=d['targets'],d['refs'],d['patterns']
    ti={v:i for i,v in enumerate(targets)};pi={v:i for i,v in enumerate(refs)}
    stable=membership.set_index('reference_id');sm=summary.set_index('module_id')
    burden=target_burden.set_index('target');corr=correlation(d['x'])
    eligible=summary.loc[(summary.n_patterns>=3)&(summary.n_triplets>=2),'module_id'].tolist()
    eligible_activity=activity[eligible].abs()
    active=eligible_activity>=cfg.strong_module_activity_pp
    row_sum=eligible_activity.sum(1)
    specificity=eligible_activity.div(row_sum.replace(0,np.nan),axis=0).fillna(0)
    contexts={};specific_rows=[];cross_rows=[]
    for target in targets:
        strong=active.columns[active.loc[target]].tolist()
        dominant=eligible_activity.loc[target].idxmax() if eligible else None
        score=float(specificity.loc[target,dominant]) if dominant else 0.
        specific=len(strong)==1 and score>=cfg.module_specificity_min
        contexts[target]=dict(strong_modules=strong,n_strong_modules=len(strong),
            dominant_module=dominant,module_specificity=score,module_specific=bool(specific),cross_module=len(strong)>=2)
        row=dict(target=target,dominant_module=dominant,dominant_activity_pp=activity.loc[target,dominant] if dominant else np.nan,
                 module_specificity=score,n_strong_modules=len(strong),strong_modules=json.dumps(strong),
                 target_cell_count=int(burden.loc[target,'target_cell_count']),definition='absolute_median_delta_in_eligible_groups')
        if specific:specific_rows.append(row)
        if len(strong)>=2:cross_rows.append(row)
    disjoint=pairs.loc[(pairs.shared_gene_count==0)&(pairs.pearson_r>=cfg.context_pearson_min)&
        (pairs.spearman_rho>=cfg.context_spearman_min)&(pairs.n_shared_candidate_targets>=cfg.context_shared_candidates_min)]
    contrasts=pairs.loc[(pairs.shared_gene_count>=2)&(pairs.state_disagreements>0)&
        (pairs.pearson_r<=cfg.contrast_pearson_max)&(pairs.n_shared_candidate_targets>=cfg.context_shared_candidates_min)]
    disjoint_map=defaultdict(list);contrast_map=defaultdict(list)
    for table,mapping in [(disjoint,disjoint_map),(contrasts,contrast_map)]:
        for r in table.itertuples():
            for a,b in [(r.reference_a,r.reference_b),(r.reference_b,r.reference_a)]:
                mapping[a].append(dict(reference_id=b,pearson_r=r.pearson_r,spearman_rho=r.spearman_rho,
                                      shared_gene_count=r.shared_gene_count,shared_candidate_targets=r.n_shared_candidate_targets))
    # Compression keys group records only within one target and response direction.
    # They are sampling blocks, not assertions of biological equivalence.
    blocks=defaultdict(list)
    for c in d['candidates']:
        j=pi[c['reference_id']];g=groups[j];direction='enrichment' if c['delta']>0 else 'depletion'
        blocks[(c['target'],g,direction)].append(j)
    block_reps={}
    for key,js in blocks.items():
        g=key[1];med=reps[g]
        block_reps[key]=min(js,key=lambda j:(-corr[j,med],
            -int(stable.loc[refs[j],'core_or_boundary']=='stable_core'),refs[j]))
    robust_status={}
    for g in summary.module_id:
        r=robustness.loc[(robustness.reference_module==g)&(robustness.alternative_run!='continuous_pearson')]
        cont=r.loc[r.comparison_kind=='continuous_profile']
        robust_status[g]='stable_across_continuous_choices' if len(cont) and cont.passes_descriptive_alignment_rule.all() else 'parameter_sensitive'
    rows=[];pool=[]
    source=str(d['scan_run']/'scan/candidates.jsonl')
    for c in sorted(d['candidates'],key=lambda c:(c['target'],c['reference_id'])):
        target,ref=c['target'],c['reference_id'];i,j=ti[target],pi[ref];g=groups[j]
        direction='enrichment' if c['delta']>0 else 'depletion';ctx=contexts[target]
        key=(target,g,direction);role='representative' if block_reps[key]==j else 'additional_record'
        core=stable.loc[ref,'core_or_boundary'];n=int(c['perturbation_n']);effect=c['delta']*100
        dj=[v for v in disjoint_map[ref] if d['mask'][i,pi[v['reference_id']]]]
        sc=[v for v in contrast_map[ref] if d['mask'][i,pi[v['reference_id']]]]
        tags=[]
        if core=='stable_core':tags.append('stable_module_core')
        if core=='boundary':tags.append('module_boundary')
        if j==reps[g]:tags.append('module_representative')
        if core=='stable_core' and role=='representative':tags.append('stable_core_representative')
        if ctx['module_specific'] and g==ctx['dominant_module']:tags.append('module_specific')
        if ctx['cross_module'] and g in ctx['strong_modules']:tags.append('cross_module')
        if dj:tags.append('gene_disjoint_correlated_context')
        if sc:tags.append('signed_state_contrast')
        tags.append(direction)
        if abs(effect)>=cfg.high_effect_pp:tags.extend(['high_effect','strong_'+direction])
        if n>=cfg.high_target_support_cells:tags.append('high_target_support')
        sensitive=n<cfg.sample_size_context_cells or n>=cfg.high_target_support_cells
        if sensitive:tags.append('sample_size_sensitive')
        sample=dict(target_cell_count=n,target_candidate_count=int(burden.loc[target,'n_candidates']),
            support_context='near_support_floor' if n<cfg.sample_size_context_cells else 'high_sample_count' if n>=cfg.high_target_support_cells else 'intermediate',
            sample_size_sensitive=sensitive,flag_scope='sample_size_stratum; individual sensitivity not estimated',
            burden_is_not_biological_breadth=True)
        case_id=f'{d["scan"].name}:{c["clue_id"]}'
        row=dict(case_id=case_id,target=target,reference_id=ref,signed_pattern=c['pattern'],
            genes=json.dumps(c['genes']),states=json.dumps(c['states']),triplet_id=patterns[j]['candidate_id'],
            delta=c['delta'],delta_percentage_points=effect,direction=direction,
            exploratory_adjusted_p=c['selected_family_holm_exploratory'],adjusted_p_method='selected_family_holm_exploratory',
            target_cell_count=n,pattern_reference_prevalence=patterns[j]['nt_frequency'],
            module_id=g,module_stability=sm.loc[g,'mean_co_clustering'],core_or_boundary=core,
            module_robustness=robust_status[g],target_cluster=burden.loc[target,'target_cluster'],
            target_module_activity_pp=activity.loc[target,g],
            target_module_specificity=float(specificity.loc[target,g]) if g in eligible else np.nan,
            target_specificity_eligible=bool(g in eligible),cross_module_context=json.dumps(ctx['strong_modules']),
            n_gene_disjoint_candidate_partners=len(dj),n_signed_state_contrast_partners=len(sc),
            gene_overlap_context=json.dumps(dict(target_in_pattern=target in c['genes'],signed_contrast_partners=sc)),
            sample_size_context=json.dumps(sample),strata=json.dumps(tags),
            redundancy_group_id='|'.join(key),redundancy_group_size=len(blocks[key]),redundancy_group_role=role,
            day8_eligible='not_assessed',day8_status='not_performed',evidence_status='day6_exploratory',
            selected_for_day8=False,selected_for_deep=False,biological_annotation_status='not_performed',
            nt_selection_adjusted=c['nt_selection_adjusted'],eligible_as_confirmed_clue=c['eligible_as_confirmed_clue'],
            source_artifact=source,source_line=c['_source_line'],source_clue_id=c['clue_id'])
        rows.append(row)
        pool.append(dict(case_id=case_id,target=target,reference_id=ref,signed_pattern=c['pattern'],genes=c['genes'],states=c['states'],
            delta=c['delta'],delta_percentage_points=effect,direction=direction,
            support={k:c[k] for k in ['perturbation_hits','perturbation_n','matched_nt_frequency','pooled_nt_n','batch_support']},
            exploratory_adjusted_p=c['selected_family_holm_exploratory'],adjusted_p_method='selected_family_holm_exploratory',
            family_size=c['family_size'],p_value=c['p_value'],
            original_interval={k:c[k] for k in ['nominal_pointwise_delta_ci_low','nominal_pointwise_delta_ci_high','ci_method']},
            module_id=g,module_stability=sm.loc[g,'mean_co_clustering'],core_or_boundary=core,module_robustness=robust_status[g],
            target_cluster=burden.loc[target,'target_cluster'],target_module_activity=dict(module_id=g,value_pp=activity.loc[target,g],method='median_signed_delta'),
            module_specificity=row['target_module_specificity'],cross_module_context=ctx,
            gene_overlap_context=dict(target_in_pattern=target in c['genes'],signed_state_contrast_partners=sc),
            gene_disjoint_correlated_context=dj,sample_size_context=sample,strata=tags,
            redundancy_group_id=row['redundancy_group_id'],redundancy_group_role=role,
            day8_eligible=None,day8_status='not_performed',evidence_status='day6_exploratory',
            nt_selection_adjusted=c['nt_selection_adjusted'],eligible_as_confirmed_clue=c['eligible_as_confirmed_clue'],
            external_validation_status=c['external_validation_status'],selected_for_day8=False,selected_for_deep=False,
            source=dict(path=source,sha256=d['hashes'][source],line=c['_source_line'],clue_id=c['clue_id'],
                        catalogue_digest=c['catalogue_digest'])))
    table=pd.DataFrame(rows);counts=[]
    planned={'module_specific','cross_module','stable_module_core','module_boundary','module_representative',
             'stable_core_representative','gene_disjoint_correlated_context','signed_state_contrast',
             'enrichment','depletion','strong_enrichment','strong_depletion','high_effect','high_target_support','sample_size_sensitive'}
    for tag in sorted(planned|{t for raw in table.strata for t in json.loads(raw)}):
        selected=table.loc[table.strata.map(lambda v:tag in json.loads(v))]
        counts.append(dict(stratum=tag,n_cases=len(selected),n_targets=selected.target.nunique(),n_modules=selected.module_id.nunique(),
                           n_redundancy_blocks=selected.redundancy_group_id.nunique(),overlapping=True))
    compression=[dict(category='all_source_candidates',n=len(table)),dict(category='target_module_direction_blocks',n=len(blocks)),
        dict(category='block_representative_records',n=int((table.redundancy_group_role=='representative').sum())),
        dict(category='additional_records_within_blocks',n=int((table.redundancy_group_role=='additional_record').sum())),
        dict(category='finally_selected_deep_cases',n=0)]
    objects=[]
    for g in summary.module_id:
        full=np.flatnonzero(groups==g)
        for mode,indices in [('whole_module',full),('stable_core',cores[g])]:
            object_rep=medoid(indices,corr,d['mask'].sum(0),d['x'],co,refs) if len(indices) else None
            subactivity=np.median(d['x'][:,indices],axis=1) if len(indices) else np.full(len(targets),np.nan)
            has_candidates=d['mask'][:,indices].any(1) if len(indices) else np.zeros(len(targets),bool)
            top=sorted(np.flatnonzero(has_candidates),key=lambda i:(-abs(subactivity[i]),targets[i]))[:8]
            ixrefs=set(refs[indices]);partners=disjoint.loc[disjoint.reference_a.isin(ixrefs)|disjoint.reference_b.isin(ixrefs)]
            objects.append(dict(annotation_object_id=f'{g}_{"core" if mode=="stable_core" else "whole"}',module_id=g,scope=mode,
                available=bool(len(indices)),status='ready_for_future_annotation' if len(indices) else 'no_assessable_stable_core',
                patterns=[dict(reference_id=refs[j],genes=patterns[j]['genes'],states=patterns[j]['states'],
                    signed_pattern=patterns[j]['pattern'],reference_prevalence=patterns[j]['nt_frequency']) for j in indices],
                stable_core_patterns=list(refs[cores[g]]),
                representative_pattern=dict(reference_id=refs[object_rep],signed_pattern=patterns[object_rep]['pattern'],included_in_object=True) if object_rep is not None else None,
                whole_module_representative_reference_id=refs[reps[g]],all_genes=sorted({gene for j in indices for gene in patterns[j]['genes']}),
                top_perturbation_targets=[dict(target=targets[i],median_signed_delta_pp=subactivity[i],
                    target_cell_count=int(burden.loc[targets[i],'target_cell_count'])) for i in top],
                module_activity_profile=[dict(target=t,median_signed_delta_pp=v) for t,v in zip(targets,subactivity)],
                gene_disjoint_correlated_partners=partners[['reference_a','reference_b','pearson_r','spearman_rho','n_shared_candidate_targets']].to_dict('records'),
                stability_metrics={k:sm.loc[g,k] for k in ['mean_co_clustering','median_co_clustering','min_co_clustering','core_fraction']},
                candidate_coverage=int(d['mask'][:,indices].sum()),evidence_status='day6_exploratory',day8_status='not_performed',
                biological_annotation_status='not_performed',signed_state_required=True))
    columns=['target','dominant_module','dominant_activity_pp','module_specificity','n_strong_modules','strong_modules','target_cell_count','definition']
    return dict(table=table,pool=pool,annotation_objects=objects,strata=pd.DataFrame(counts),compression=pd.DataFrame(compression),
        specific=pd.DataFrame(specific_rows,columns=columns),cross=pd.DataFrame(cross_rows,columns=columns),contexts=contexts,
        disjoint_context_pairs=disjoint,contrast_context_pairs=contrasts,robust_status=robust_status)
