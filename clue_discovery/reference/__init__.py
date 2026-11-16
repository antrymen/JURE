"""Stage I: adaptation of the accepted v04 + held-out Holm implementation."""
from dataclasses import replace
from pathlib import Path
import json
import numpy as np
from clue_discovery.schemas import ReferenceState, ReferenceCatalogue
from clue_discovery.integration.io import artifact, clean, write_json
from clue_discovery.v03.artifacts import digest


def compatibility_metadata(config):
    return {k:getattr(config,k) for k in ('modality','binarization_rule','cell_context','timepoint',
            'control_labels','batch_field','replicate_field','condition_type','matching_strategy')}


def import_frozen_catalogue(path,config):
    value=json.loads(Path(path).read_text())
    if 'payload' not in value: return ReferenceCatalogue.model_validate(value)
    if digest(value['payload'])!=value['sha256']: raise ValueError('catalogue digest mismatch')
    provenance=artifact(path);records=[]
    for r in value['payload']['records']:
        evidence={f'{role}:{fold}':ev for role in ('discovery','validation')
                  for fold,ev in r.get(role+'_evidence',{}).items()}
        def select(tokens):
            return {f:({k:v for k,v in e.items() if any(t in k for t in tokens)} if e is not None else None) for f,e in evidence.items()}
        records.append(ReferenceState(dataset_id=config.dataset_id,reference_id=r['reference_id'],
            genes=r['genes'],states=r['states'],order=r['order'],
            reference_population={'control_labels':config.control_labels,'n_cells':r['nt_n_cells'],
                'support':r['nt_support'],'counts_by_fold':r.get('nt_counts_by_fold',{}),'prevalence_scope':'pooled_descriptive'},
            reference_prevalence=r['nt_frequency'],mfi_evidence=select(['mfi']),gain_evidence=select(['gain']),
            estimability=select(['estimability','min_state_count']),
            bootstrap_stability={'discovery':r.get('discovery_bootstrap_stable'),
                'validation':r.get('validation_bootstrap_stable'),'details':select(['bootstrap','sign_stability'])},
            crossfold_evidence={'successful_directions':r.get('successful_directions',[]),
                'bidirectionally_qualified':r.get('bidirectionally_qualified',False)},
            qualification={'holm_qualified':r['holm_qualified'],'validation_family_tests':r.get('validation_family_tests',[]),
                'state_level_FDR_controlled':False,'complete_search':r.get('complete_search',False)},
            provenance={**provenance,'record_key':r['reference_id'],'gene_set_id':r['candidate_id'],
                'source_evidence_retained':True}))
    return ReferenceCatalogue(dataset_id=config.dataset_id,records=records,
        compatibility=compatibility_metadata(config),provenance=provenance)


def discover_reference(dataset,output):
    from clue_discovery.v02.populations import Population
    from clue_discovery.v04.config import ScalableConfig
    from clue_discovery.v03.hvg import select_hvgs
    from real_nt_v04_holm.run import run_reference
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    cfg=dataset.config
    if not dataset.reference_available or int(dataset.cell_metadata.is_control.sum()) < cfg.min_cells['effective_control']:
        catalogue=ReferenceCatalogue(dataset_id=dataset.dataset_id,records=[],compatibility=compatibility_metadata(cfg),
            provenance={'status':'reference_population_unavailable','reason':'absent_or_insufficient_control_cells',**dataset.provenance})
        write_json(out/'reference_catalogue.json',catalogue);return catalogue
    if dataset.detection_matrix is None: raise ValueError('Stage I needs cell-level detection data')
    controls=np.flatnonzero(dataset.cell_metadata.is_control.to_numpy())
    if 'reference_fold' in dataset.cell_metadata:
        fold=dataset.cell_metadata.reference_fold.to_numpy()[controls]
        if set(fold)!={'A','B'}: raise ValueError('reference folds must be explicitly A/B and both nonempty')
    else:
        rng=np.random.default_rng(cfg.seed); fold=np.empty(len(controls),dtype='<U1')
        batches=dataset.cell_metadata.batch_id.to_numpy()[controls]
        for b in np.unique(batches):
            ix=np.flatnonzero(batches==b);ix=rng.permutation(ix);fold[ix[::2]]='A';fold[ix[1::2]]='B'
    pops={}
    for f in ('A','B'):
        ix=controls[fold==f]
        if not len(ix): raise ValueError('reference fold has no cells')
        source_matrix=dataset.raw_counts if dataset.raw_counts is not None else dataset.detection_matrix
        pops[f]=Population(source_matrix[ix],dataset.genes,
                           tuple(dataset.cell_metadata.iloc[ix].cell_id))
    config=replace(ScalableConfig(),**cfg.candidate_budget,
                   n_bootstrap=cfg.bootstrap_config['reference_repetitions'],random_seed=cfg.seed)
    selections={f:select_hvgs(p.matrix,p.gene_names,n_top=config.hvg_pool_size,fold=f) for f,p in pops.items()}
    write_json(out/'cell_provenance.json',{'dataset':dataset.provenance,
        'fold_cell_ids':{f:list(p.cell_ids) for f,p in pops.items()},'split_is_biological_replication':False})
    run_reference(pops,selections,{'dataset_id':dataset.dataset_id,'real_data_used':cfg.data_origin=='real',
        'integration_run':True,'source':dataset.provenance},config,out/'backend')
    catalogue=import_frozen_catalogue(out/'backend/holm_reference_catalogue_frozen.json',cfg)
    catalogue.provenance['cell_provenance']=artifact(out/'cell_provenance.json')
    write_json(out/'reference_catalogue.json',catalogue)
    return catalogue


def check_transfer(dataset,catalogue):
    """Read-only compatibility audit; no implicit recalibration or state search."""
    cfg=dataset.config;source=catalogue.compatibility
    required=('modality','binarization_rule','cell_context','timepoint','control_labels','matching_strategy')
    missing=[k for k in required if k not in source]
    conflicts=[k for k in ('modality','binarization_rule','matching_strategy') if source.get(k)!=getattr(cfg,k)]
    contextual_differences={k:{'source':source.get(k),'target':getattr(cfg,k)} for k in
        ('cell_context','timepoint','control_labels','condition_type') if source.get(k)!=getattr(cfg,k)}
    conflicts.extend(k for k in contextual_differences if not cfg.transfer_compatibility.get(k,'').strip())
    unsupported=[r.reference_id for r in catalogue.records if r.order!=3]
    available=set(dataset.genes)
    missing_genes={r.reference_id:sorted(set(r.genes)-available) for r in catalogue.records if not set(r.genes)<=available}
    status='INCOMPATIBLE' if missing or conflicts or unsupported else 'READY_WITH_UNEVALUABLE_REFERENCES' if missing_genes else 'READY'
    if not dataset.reference_available and status!='INCOMPATIBLE': status='reference_population_unavailable'
    return {'status':status,'contextual_differences':contextual_differences,
        'prespecified_compatibility_justifications':cfg.transfer_compatibility,
        'missing_compatibility_fields':missing,'incompatible_fields':conflicts,
        'unsupported_backend_orders':unsupported,'missing_genes_by_reference':missing_genes,
        'gene_mapping':cfg.gene_mapping,'condition_universe':list(dataset.conditions),
        'control_identity':cfg.control_labels,'batch_field':cfg.batch_field,'replicate_field':cfg.replicate_field,
        'cell_context':{'source':source.get('cell_context'),'target':cfg.cell_context},
        'timepoint':{'source':source.get('timepoint'),'target':cfg.timepoint},
        'reference_denominator':len(catalogue.records),'reference_states_locked':True,
        'new_reference_discovery':False,'empirical_transfer_validated':False}
