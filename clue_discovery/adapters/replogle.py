"""Application-specific, read-only adapter for accepted Replogle artifacts."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from .base import DatasetAdapter, ClueDiscoveryDataset
from clue_discovery.integration.io import artifact, read_jsonl, sha256
from clue_discovery.reference import import_frozen_catalogue
from clue_discovery.perturbation_scan import AssociationBundle, convert_candidate
from clue_discovery.landscape import groups_from_tables, relation_from_row, assemble_landscape, write_landscape

class ReplogleFrozenAdapter(DatasetAdapter):
    def load_dataset(self,config):
        source=Path(config.paths['scan_root'])/'metadata/allowed_cell_metadata.csv.gz'
        raw=pd.read_csv(source,dtype=str)
        meta=pd.DataFrame({'cell_id':raw[config.cell_id_field],'condition_id':raw[config.condition_field],
            'batch_id':raw[config.batch_field],'replicate_id':'NOT_PROVIDED'})
        meta['is_control']=meta.condition_id.isin(config.control_labels)
        cat=import_frozen_catalogue(config.paths['reference_catalogue'],config)
        return ClueDiscoveryDataset(config.dataset_id,meta,tuple(sorted(set(meta.loc[~meta.is_control,'condition_id']))),
            tuple(config.control_labels),tuple(sorted({g for r in cat.records for g in r.genes})),None,config,
            {'adapter':'ReplogleFrozenAdapter','metadata':artifact(source),'expression_loaded':False},metadata_only=True).validate()

    def load_bundle(self,config):
        scan=Path(config.paths['scan_root']);broad=Path(config.paths['broad_root'])
        manifest=json.loads((broad/'audit/run_manifest.json').read_text())
        checked={}
        for path,expected in manifest['input_sha256'].items():
            if sha256(path)!=expected: raise ValueError('frozen Broad input hash mismatch: '+path)
            checked[path]=expected
        for rel,expected in manifest['artifacts_sha256'].items():
            path=broad/rel
            if sha256(path)!=expected: raise ValueError('frozen Broad output hash mismatch: '+rel)
            checked[str(path)]=expected
        cat=import_frozen_catalogue(config.paths['reference_catalogue'],config)
        identities=json.loads((scan/'counts/identities.json').read_text())
        if [r.reference_id for r in cat.records]!=[r['reference_id'] for r in identities['patterns']]:
            raise ValueError('frozen catalogue/scan axis order conflict')
        with np.load(scan/'scan/statistics.npz') as z:vals={k:z[k].copy() for k in z.files}
        src=artifact(scan/'scan/candidates.jsonl')
        cases=[convert_candidate(r,config,src,i) for i,r in enumerate(read_jsonl(src['path']),1)]
        provenance={'adapter':'ReplogleFrozenAdapter','mode':'read_only_artifact_conversion',
            'reference_catalogue':artifact(config.paths['reference_catalogue']),
            'association_source':src,'broad_manifest':artifact(broad/'audit/run_manifest.json'),
            'cell_provenance':artifact(scan/'metadata/allowed_cell_metadata.csv.gz'),
            'aggregated_counts':artifact(scan/'counts/counts.npz'),
            'frozen_input_output_hashes_verified':len(checked),'statistics_recomputed':False}
        return AssociationBundle(config.dataset_id,cat,list(identities['targets']),vals['delta'],vals['candidate'],
            vals['tested'],vals['reason'],vals['target_hits'],vals['target_n'],cases,provenance).validate()

    def load_landscape(self,config,bundle,output):
        root=Path(config.paths['broad_root']);table=root/'tables'
        read=lambda name:pd.read_csv(table/(name+'.csv'))
        groups=groups_from_tables(read('module_summary'),read('stable_core_membership'),read('module_robustness'),bundle.catalogue)
        pairs=pd.concat([read('gene_disjoint_case_context_pairs'),read('signed_state_case_context_pairs')]).drop_duplicates(['reference_a','reference_b'])
        relations=[relation_from_row(r,bundle) for r in pairs.to_dict('records')]
        activity=pd.read_csv(table/'target_module_activity.csv',index_col=0)
        legacy={(r['target'],r['reference_id']):r for r in read_jsonl(root/'agent_inputs/deep_case_pool.jsonl')}
        if len(legacy)!=len(bundle.associations): raise ValueError('Broad pool/scan count mismatch')
        for a in bundle.associations:
            old=legacy[(a.condition_id,a.reference_id)]
            if old['delta']!=a.matched_effect or old['states']!=a.states or old['source']['clue_id']!=a.candidate_id:
                raise ValueError('Broad pool changed original candidate')
        quality={'status':'FROZEN_RESULTS_IMPORTED','statistical_recomputation':False,
            'profile_cohort':'original_candidate_bearing_targets','candidate_count':len(bundle.associations),
            'condition_count':len(bundle.conditions),'reference_count':len(bundle.catalogue.records),
            'sample_size_dependence':read('sample_size_dependence').to_dict('records'),
            'source_quality_artifacts':{name:artifact(table/(name+'.csv')) for name in
                ('module_stability','module_robustness','signed_state_ablation','candidate_concentration','pca_variance',
                 'case_strata_summary','same_genes_different_states','gene_overlap_response_similarity')},
            'matrix_views':{p.name:artifact(p) for p in (root/'matrices').glob('*.csv.gz')}}
        landscape=assemble_landscape(bundle,groups,relations,activity,quality,legacy,config=config)
        write_landscape(landscape,output);return landscape
