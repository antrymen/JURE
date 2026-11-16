"""Stage III: thin composition of the accepted Broad Screening kernels."""
from collections import defaultdict
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from clue_discovery.schemas import (SignedState, ResponseGroup, CoResponseRelation, ConditionProfile,
    TriageInput, StructuredClueLandscape)
from clue_discovery.integration.io import clean, identity, write_json, write_jsonl
from landscape_analysis.core import matrix_views, hierarchy
from broad_screening.config import Config
from broad_screening.analysis import cluster, modules, pair_analysis
from broad_screening.sensitivity import resample_schedule, bootstrap_partitions, sensitivity_and_ablation

EVIDENCE_SCOPE = {'stage':'III','role':'descriptive_organization','evidence_upgrade':False,
    'biological_annotation':'NOT_ANNOTATED','causal_claims':False,'deep_agent_calls':False,
    'burden_is_biological_breadth':False,'activity_is_interaction_strength':False,
    'stability_scope':'internal_condition_resampling_not_external_replication'}


def relation_from_row(row, bundle):
    refs={r.reference_id:r for r in bundle.catalogue.records}
    a,b=refs[row['reference_a']],refs[row['reference_b']]
    overlap=sorted(set(a.genes)&set(b.genes))
    kind=('SIGNED_STATE_CONTRAST' if row.get('state_disagreements',0)>0 and row['pearson_r']<0
          else 'OVERLAPPING_GENE_CORESPONSE' if overlap else 'GENE_DISJOINT_CORESPONSE')
    ai=[i for i,r in enumerate(bundle.catalogue.records) if r.reference_id==a.reference_id][0]
    bi=[i for i,r in enumerate(bundle.catalogue.records) if r.reference_id==b.reference_id][0]
    shared=[c for i,c in enumerate(bundle.conditions) if bundle.candidate[i,ai] and bundle.candidate[i,bi]]
    return CoResponseRelation(**clean(dict(relation_id='REL'+identity([a.reference_id,b.reference_id]),
        reference_a=a.reference_id,reference_b=b.reference_id,relation_type=kind,shared_genes=overlap,
        gene_jaccard=row['gene_jaccard'],pearson_r=row['pearson_r'],spearman_rho=row['spearman_rho'],
        shared_candidate_conditions=shared,direction_concordance=row.get('direction_concordance'),
        evaluable_condition_count=row['n_common_evaluable_targets'],provenance={'source':'accepted_pair_profile_kernel'})))


def groups_from_tables(summary,membership,robustness,catalogue):
    refs={r.reference_id:r for r in catalogue.records};result=[]
    import json
    for row in summary.to_dict('records'):
        gid=row['module_id'];ids=membership.loc[membership.module_id==gid,'reference_id'].tolist()
        result.append(ResponseGroup(**clean(dict(group_id=gid,reference_ids=ids,
            signed_states=[SignedState(genes=refs[r].genes,states=refs[r].states,order=refs[r].order) for r in ids],
            representative_reference_id=row['representative_reference_id'],stable_core=json.loads(row['stable_core_patterns']),
            boundary_members=json.loads(row['boundary_patterns']),candidate_count=row['n_candidates'],condition_count=row['n_targets'],
            direction_summary={k:row[k] for k in ('n_enrichment','n_depletion','dominant_direction')},
            within_group_similarity=row['within_module_similarity'],
            stability={k:row[k] for k in ('mean_co_clustering','median_co_clustering','min_co_clustering','stable_core_size')},
            sensitivity=robustness.loc[robustness.reference_module==gid].to_dict('records') if len(robustness) else [],
            activity_definition='median matched prevalence difference across all member signed states; displayed in percentage points'))))
    return result


def assemble_landscape(bundle,groups,relations,activity,quality,legacy_cases=None,config=None):
    """Serialize context without changing any association or choosing any case."""
    refs={r.reference_id:r for r in bundle.catalogue.records}
    by_ref={r:g for g in groups for r in g.reference_ids}
    relations_by_ref=defaultdict(list)
    for rel in relations:
        for r in (rel.reference_a,rel.reference_b):relations_by_ref[r].append(rel)
    cases_by_condition=defaultdict(list)
    for a in bundle.associations:cases_by_condition[a.condition_id].append(a)
    profiles=[]
    for i,c in enumerate(bundle.conditions):
        cases=cases_by_condition[c]
        profiles.append(ConditionProfile(condition_id=c,condition_type=config.condition_type if config else (cases[0].condition_type if cases else 'unspecified'),condition_cell_count=int(bundle.condition_n[i]),
            candidate_count=len(cases),enrichment_count=sum(a.direction=='enrichment' for a in cases),
            depletion_count=sum(a.direction=='depletion' for a in cases),
            response_group_ids=sorted({by_ref[a.reference_id].group_id for a in cases if a.reference_id in by_ref}),
            activity=clean(activity.loc[c].to_dict()) if c in activity.index else {},
            sample_size_context={'condition_cell_count':int(bundle.condition_n[i]),'candidate_burden_raw':len(cases),'is_biological_breadth':False},
            quality_flags=['NOT_EVALUABLE'] if not matrix_views(bundle.delta[i],bundle.candidate[i],bundle.tested[i],bundle.reason[i])['enough_support'].any() else []))
    profiles_by_id={p.condition_id:p for p in profiles};pool=[];strata=defaultdict(list);blocks=defaultdict(list)
    legacy_cases=legacy_cases or {}
    for a in bundle.associations:
        ref=refs[a.reference_id];g=by_ref.get(a.reference_id);context=relations_by_ref[a.reference_id]
        legacy=legacy_cases.get((a.condition_id,a.reference_id),{})
        caseid=legacy.get('case_id',bundle.dataset_id+':'+a.candidate_id)
        core_status='stable_core' if g and a.reference_id in g.stable_core else 'boundary' if g else 'unclustered'
        if legacy:
            core_status=legacy.get('core_or_boundary',core_status)
        elif config and (not config.landscape_config.get('bootstrap_enabled',True) or not config.landscape_config.get('stable_core_enabled',True)):
            core_status='not_assessed'
        elif g and len(g.reference_ids)==1:
            core_status='singleton_unassessable'
        labels=legacy.get('strata',[a.direction,core_status]+(['cross_group'] if len(profiles_by_id[a.condition_id].response_group_ids)>1 else []))
        if not legacy:
            if g and a.reference_id==g.representative_reference_id: labels.append('group_representative')
            if any(r.relation_type=='SIGNED_STATE_CONTRAST' for r in context): labels.append('signed_state_contrast')
            if any(r.relation_type=='GENE_DISJOINT_CORESPONSE' for r in context): labels.append('gene_disjoint_coresponse')
            if config:
                thresholds=Config(**config.landscape_config)
                if abs(a.matched_effect)*100>=thresholds.high_effect_pp: labels.append('high_effect')
                if profiles_by_id[a.condition_id].condition_cell_count>=thresholds.high_target_support_cells: labels.append('high_support')
                if profiles_by_id[a.condition_id].condition_cell_count<thresholds.sample_size_context_cells: labels.append('sample_size_sensitive_context')
        block=legacy.get('redundancy_group_id','BLOCK'+identity([bundle.dataset_id,a.condition_id,g.group_id if g else a.reference_id,a.direction]))
        case=TriageInput(case_id=caseid,dataset_id=bundle.dataset_id,condition_id=a.condition_id,candidate_id=a.candidate_id,
            reference_id=a.reference_id,genes=a.genes,states=a.states,order=a.order,matched_effect=a.matched_effect,
            reference_evidence={'reference_dataset_id':ref.dataset_id,'reference_id':ref.reference_id,
                'qualification':ref.qualification,'mfi':ref.mfi_evidence,'gain':ref.gain_evidence,'provenance':ref.provenance},
            association_evidence=a.association_evidence,group_context={'group_id':g.group_id if g else None,
                'stability':g.stability if g else {},'annotation_status':'NOT_ANNOTATED',
                'legacy_context':{k:legacy[k] for k in ('module_robustness','cross_module_context','target_module_activity','module_specificity') if k in legacy}},
            stable_core_context={'status':core_status,'members':g.stable_core if g else []},
            coresponse_context=[r.relation_id for r in context if r.relation_type!='SIGNED_STATE_CONTRAST'],
            signed_state_contrast_context=[r.relation_id for r in context if r.relation_type=='SIGNED_STATE_CONTRAST'],
            support={'condition':a.condition_support,'control':a.control_support},
            sample_size_context=legacy.get('sample_size_context',profiles_by_id[a.condition_id].sample_size_context),
            external_validation_status=a.external_validation_status,evidence_level=a.evidence_level,
            strata=labels,sampling_block_id=block,provenance={'association':a.provenance,'reference':ref.provenance,
                'matrix_and_cell_sources':bundle.provenance,'selection_performed':False})
        pool.append(case)
        for label in labels:strata[label].append(caseid)
        blocks[block].append(caseid)
    state_profiles=[{'reference_id':r.reference_id,'genes':r.genes,'states':r.states,'order':r.order,
        'reference_prevalence':r.reference_prevalence,'candidate_count':int(bundle.candidate[:,j].sum()),
        'group_id':by_ref[r.reference_id].group_id if r.reference_id in by_ref else None,
        'evidence_level':r.evidence_level.value} for j,r in enumerate(bundle.catalogue.records)]
    return StructuredClueLandscape(dataset_id=bundle.dataset_id,evidence_scope=EVIDENCE_SCOPE,response_groups=groups,
        condition_profiles=profiles,reference_state_profiles=state_profiles,stable_cores={g.group_id:g.stable_core for g in groups},
        boundary_members={g.group_id:g.boundary_members for g in groups},
        coresponse_relations=[r for r in relations if r.relation_type!='SIGNED_STATE_CONTRAST'],
        signed_state_contrasts=[r for r in relations if r.relation_type=='SIGNED_STATE_CONTRAST'],
        case_strata=dict(strata),sampling_blocks=dict(blocks),quality_audits=clean(quality),triage_inputs=pool,
        annotation_inputs=[{'group_id':g.group_id,'reference_ids':g.reference_ids,
            'signed_states':[v.model_dump() for v in g.signed_states],'stable_core':g.stable_core,
            'representative_reference_id':g.representative_reference_id,'annotation_status':'NOT_ANNOTATED'} for g in groups],
        provenance=bundle.provenance)


def write_landscape(landscape,output):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    write_json(out/'structured_clue_landscape.json',landscape)
    write_jsonl(out/'triage_inputs.jsonl',landscape.triage_inputs)
    write_jsonl(out/'annotation_inputs.jsonl',landscape.annotation_inputs)
    write_json(out/'deep_case_pool.json',{'status':'UNSELECTED','triage_inputs':'triage_inputs.jsonl','selected_case_count':0})
    write_json(out/'EVIDENCE_SCOPE.json',landscape.evidence_scope)


def organize_landscape(bundle,config,output):
    bundle.validate();out=Path(output);out.mkdir(parents=True,exist_ok=True)
    cfg=Config(**config.landscape_config,seed=config.seed,bootstrap_repetitions=config.bootstrap_config['landscape_repetitions']).validate()
    views=matrix_views(bundle.delta,bundle.candidate,bundle.tested,bundle.reason)
    # Candidate-bearing conditions match the accepted Broad primary cohort.
    rows=np.flatnonzero(bundle.candidate.any(1)&views['enough_support'].all(1))
    ix=np.array([],int)
    if len(rows)>=2:
        x_all=bundle.delta[rows]*100
        ix=np.flatnonzero(np.isfinite(x_all).all(0)&(np.std(x_all,axis=0)>1e-12))
    groups=[];relations=[];activity=pd.DataFrame();quality={'status':'EMPTY' if not bundle.associations else 'WEAK_OR_UNEVALUABLE',
        'candidate_count':len(bundle.associations),'condition_count':len(bundle.conditions),'reference_count':len(bundle.catalogue.records),
        'profile_cohort':'candidate_bearing_conditions_with_all_references_supported',
        'profile_condition_count':len(rows),'profile_reference_count':len(ix),
        'excluded_condition_ids':[c for i,c in enumerate(bundle.conditions) if i not in set(rows)],
        'family_denominator':bundle.delta.size,'tested_count':int(bundle.tested.sum()),
        'insufficient_support_count':int((~views['enough_support']).sum()),'missing_effect_count':int((~np.isfinite(bundle.delta)).sum()),
        'observed_zero_count':int((bundle.delta==0).sum()),'unselected_observed_effect_count':int((~bundle.candidate&np.isfinite(bundle.delta)).sum())}
    # No candidate, no shared-response claim. One varying state is insufficient for a group.
    if bundle.associations and len(ix)>=2:
        references=[bundle.catalogue.records[i] for i in ix];refs=np.array([r.reference_id for r in references])
        patterns=[dict(reference_id=r.reference_id,genes=r.genes,states=r.states,pattern=r.signed_pattern,
                       candidate_id=identity(sorted(r.genes))) for r in references]
        x=bundle.delta[np.ix_(rows,ix)]*100;mask=bundle.candidate[np.ix_(rows,ix)];mass=mask.sum(0)
        labels,_=cluster(x,mass,refs,cfg.clustering_cut)
        schedule=resample_schedule(len(rows),np.array([p['candidate_id'] for p in patterns]),cfg.bootstrap_repetitions,cfg.seed)
        co,boots=bootstrap_partitions(x,mass,refs,cfg,schedule) if cfg.bootstrap_enabled else (np.full((len(ix),len(ix)),np.nan),np.empty((0,len(ix)),str))
        d={'x':x,'mask':mask,'refs':refs,'patterns':patterns,'targets':np.array(bundle.conditions)[rows],
           'target_table':pd.DataFrame({'target_group':hierarchy(x,'cosine',cfg.clustering_cut,optimal=False)['labels']})}
        summary,members,cores,reps,activity,zmean,unstable=modules(d,cfg,labels,co)
        pairs,dist,_,_=pair_analysis(d,labels)
        with warnings.catch_warnings(record=True) as diagnostic_warnings:
            warnings.simplefilter('always',RuntimeWarning)
            sensitivity=sensitivity_and_ablation(d,cfg,labels,co,cores,reps,schedule,boots)
        quality['kernel_warnings']=sorted({str(w.message) for w in diagnostic_warnings})
        quality['undefined_comparisons']='null; no common binary pair domain is a valid outcome'
        for name,frame in {'group_summary':summary,'core_membership':members,'pattern_pair_similarity':pairs,
                'pair_similarity_distribution':dist,**{k:v for k,v in sensitivity.items() if isinstance(v,pd.DataFrame)}}.items():
            frame.to_csv(out/(name+'.csv'),index=False)
        np.savez_compressed(out/'bootstrap_coassignment.npz',coassignment=co,reference_ids=refs,condition_indices=rows)
        groups=groups_from_tables(summary,members,sensitivity['robustness'],bundle.catalogue)
        selected=pairs[((pairs.pearson_r>=cfg.context_pearson_min)&(pairs.spearman_rho>=cfg.context_spearman_min)&
                        (pairs.n_shared_candidate_targets>=cfg.context_shared_candidates_min))|
                       ((pairs.state_disagreements>0)&(pairs.pearson_r<=cfg.contrast_pearson_max))]
        relations=[relation_from_row(r,bundle) for r in selected.to_dict('records')]
        quality.update(status='ORGANIZED',kernel='broad_screening.analysis + sensitivity',
            signed_state_ablation=clean(sensitivity['ablation'].to_dict('records')),
            bootstrap_scope='internal_condition_bootstrap; very small cohorts give coarse stability')
    burden=bundle.candidate.sum(1)
    rho=spearmanr(bundle.condition_n,burden).statistic if len(burden)>2 and np.std(burden)>0 and np.std(bundle.condition_n)>0 else None
    quality['sample_size_dependence']={'spearman_rho':clean(rho),'cohort':'all_configured_conditions','is_power_adjustment':False}
    # Standard centered SVD, same convention as accepted Broad PCA; no low-rank target imposed.
    if len(rows)>=2 and bundle.delta.shape[1] and np.isfinite(bundle.delta[rows]).all():
        centered=(bundle.delta[rows]-bundle.delta[rows].mean(0))*100
        u,s,vt=np.linalg.svd(centered,full_matrices=False)
        if np.sum(s*s)>1e-20:
            ev=s*s/np.sum(s*s);pcs=[f'PC{i+1}' for i in range(len(s))]
            pd.DataFrame({'component':pcs,'variance_explained':ev,'cumulative_variance':np.cumsum(ev)}).to_csv(out/'pca_variance.csv',index=False)
            pd.DataFrame(u*s,index=np.array(bundle.conditions)[rows],columns=pcs).to_csv(out/'pca_condition_scores.csv')
            pd.DataFrame(vt.T,index=[r.reference_id for r in bundle.catalogue.records],columns=pcs).to_csv(out/'pca_state_loadings.csv')
            quality['pca']={'status':'DESCRIPTIVE','variance_explained':ev.tolist(),'cohort':quality['profile_cohort']}
    quality.setdefault('pca',{'status':'NOT_EVALUABLE'})
    mass=bundle.candidate.sum(0);total=int(mass.sum());curves=[]
    for unit,pairs in [('state',[(r.reference_id,int(mass[j])) for j,r in enumerate(bundle.catalogue.records)]),
                       ('group',[(g.group_id,g.candidate_count) for g in groups])]:
        cumulative=0
        for rank,(key,count) in enumerate(sorted(pairs,key=lambda p:(-p[1],p[0])),1):
            cumulative+=count
            curves.append({'unit':unit,'rank':rank,'identity':key,'candidate_count':count,
                'cumulative_candidates':cumulative,'candidate_fraction':cumulative/total if total else None})
    quality['concentration']=curves
    quality['direction_composition']={'enrichment':sum(a.direction=='enrichment' for a in bundle.associations),
                                      'depletion':sum(a.direction=='depletion' for a in bundle.associations)}
    quality['group_coverage_unassigned_candidates']=total-sum(g.candidate_count for g in groups)
    for name,values in [('effect_matrix',bundle.delta),('candidate_mask',bundle.candidate.astype(int)),
                        ('tested_mask',bundle.tested.astype(int)),('reason_matrix',bundle.reason),('support_matrix',bundle.support)]:
        pd.DataFrame(values,index=pd.Index(bundle.conditions,name='condition_id'),
                     columns=[r.reference_id for r in bundle.catalogue.records]).to_csv(out/(name+'.csv'))
    landscape=assemble_landscape(bundle,groups,relations,activity,quality,config=config)
    write_landscape(landscape,out);return landscape
