"""Three-stage integration tests; empirical Day6 counts are only regression expectations."""
from pathlib import Path
import ast
import json
import numpy as np
import pandas as pd
import pytest
import yaml
from pydantic import ValidationError
from clue_discovery.adapters import DatasetConfig, TableDatasetAdapter
from clue_discovery.integration.synthetic import make_fixture
from clue_discovery.integration.io import read_jsonl, write_json, write_jsonl
from clue_discovery.run import run_pipeline
from clue_discovery.reference import import_frozen_catalogue, check_transfer
from clue_discovery.schemas import (SignedState, ReferenceCatalogue, ConditionAssociation,
    StructuredClueLandscape, SelectedCase, EvidenceLevel, LandscapeAlignmentRequest, align_landscapes)
from clue_discovery.perturbation_scan import scan_conditions
from clue_discovery.landscape import organize_landscape

@pytest.fixture(scope='module')
def full(tmp_path_factory):
    root=tmp_path_factory.mktemp('integration');cfg=make_fixture(root/'source')
    result=run_pipeline('full',cfg,root/'run')
    return root,cfg,result


def read_landscape(root):
    return StructuredClueLandscape.model_validate_json((root/'landscape/structured_clue_landscape.json').read_text())


def changed_config(path,**changes):
    original=DatasetConfig.load(path).model_dump();original.update(changes)
    return DatasetConfig.model_validate(original)


def test_actual_three_stage_signed_states_and_context(full):
    root,cfg,result=full;land=read_landscape(root/'run')
    cat=ReferenceCatalogue.model_validate_json((root/'run/reference/reference_catalogue.json').read_text())
    assert result['status']=='COMPLETE' and len(cat.records)>1
    assert all(r.qualification['holm_qualified'] and r.mfi_evidence and r.gain_evidence for r in cat.records)
    assert {c.condition_id for c in land.triage_inputs}=={'Condition_A','Condition_B'}
    assert all(c.evidence_level==EvidenceLevel.EXPLORATORY_ASSOCIATION for c in land.triage_inputs)
    assert len({tuple(c.states) for c in land.triage_inputs})>1
    assert {a.direction for a in map(ConditionAssociation.model_validate,read_jsonl(root/'run/perturbation_scan/condition_associations.jsonl'))}=={'enrichment','depletion'}
    assert len(land.response_groups)>0 and len(land.signed_state_contrasts)>0
    assert any(len(g.reference_ids)>1 for g in land.response_groups)
    assert land.quality_audits['pca']['status']=='DESCRIPTIVE'
    assert land.quality_audits['concentration']
    assert not land.evidence_scope['evidence_upgrade']
    assert all(g.annotation_status=='NOT_ANNOTATED' for g in land.response_groups)
    assert any(c.signed_state_contrast_context for c in land.triage_inputs)
    assert all(c.provenance['matrix_and_cell_sources']['cell_provenance']['sha256'] for c in land.triage_inputs)
    assert all(not c.provenance['selection_performed'] for c in land.triage_inputs)
    assert (root/'run/RUN_FROZEN_CONFIG.json').exists()


def test_negative_reference_present_no_shift_no_group(tmp_path):
    cfg=make_fixture(tmp_path/'source',True);result=run_pipeline('full',cfg,tmp_path/'run')
    land=read_landscape(tmp_path/'run')
    assert result['summary']['reference_states']>0
    assert result['summary']['associations']==0
    assert land.quality_audits['status']=='EMPTY' and not land.response_groups and not land.triage_inputs
    assert not land.signed_state_contrasts and not land.coresponse_relations


def test_adapter_fields_control_mapping_are_not_replogle(full):
    _,path,_=full;ds=TableDatasetAdapter().load_dataset(DatasetConfig.load(path))
    assert ds.genes==('SYN_A','SYN_B','SYN_C') and ds.control_labels==('vehicle',)
    assert ds.conditions==('Condition_A','Condition_B','Condition_C')
    assert ds.cell_metadata.is_control.sum()>0
    assert ds.config.condition_type=='treatment'


def test_ambiguous_mapping_and_missing_control_no_fallback(full,tmp_path):
    _,path,_=full;cfg=changed_config(path,gene_mapping={'feature_a':'X','feature_b':'X','feature_c':'Z'})
    with pytest.raises(ValueError,match='ambiguous gene'):TableDatasetAdapter().load_dataset(cfg)
    cfg=changed_config(path,control_labels=['absent_control'],expected_conditions=[])
    ds=TableDatasetAdapter().load_dataset(cfg)
    assert not ds.reference_available
    config_file=tmp_path/'config.yaml';config_file.write_text(yaml.safe_dump(cfg.model_dump()))
    result=run_pipeline('full',config_file,tmp_path/'run')
    assert result['summary']['reference_states']==0
    assert result['stages']['reference']['status']=='UNAVAILABLE'
    assert not read_landscape(tmp_path/'run').response_groups


def test_transfer_uses_frozen_states_and_preserves_family(full,tmp_path):
    root,path,_=full;cfg=DatasetConfig.load(path);data=cfg.model_dump()
    data['paths']['reference_catalogue']=str(root/'run/reference/reference_catalogue.json')
    transfer=tmp_path/'transfer.yaml';transfer.write_text(yaml.safe_dump(data))
    result=run_pipeline('transfer',transfer,tmp_path/'run')
    assert result['summary']['reference_states']==len(read_landscape(root/'run').reference_state_profiles)
    assert not (tmp_path/'run/reference/backend').exists()
    assert (tmp_path/'run/transfer_compatibility.json').exists()
    left=read_landscape(root/'run').triage_inputs;right=read_landscape(tmp_path/'run').triage_inputs
    assert {(c.condition_id,c.reference_id,c.matched_effect) for c in left}=={(c.condition_id,c.reference_id,c.matched_effect) for c in right}


def test_transfer_missing_gene_and_low_support_are_not_negative(full,tmp_path):
    root,path,_=full;cfg=DatasetConfig.load(path);ds=TableDatasetAdapter().load_dataset(cfg)
    cat=import_frozen_catalogue(root/'run/reference/reference_catalogue.json',cfg)
    ds.genes=ds.genes[:-1];ds.detection_matrix=ds.detection_matrix[:,:-1]
    audit=check_transfer(ds,cat);assert audit['status']=='READY_WITH_UNEVALUABLE_REFERENCES'
    b=scan_conditions(ds,cat,tmp_path/'missing_gene')
    assert not b.associations and np.isnan(b.delta).all()
    assert b.provenance['family_size']==len(ds.conditions)*len(cat.records)
    assert np.all(b.reason=='NOT_EVALUABLE:missing_reference_genes')
    ds=TableDatasetAdapter().load_dataset(cfg)
    indices=np.flatnonzero(ds.cell_metadata.is_control|ds.cell_metadata.cell_id.isin(ds.cell_metadata.query("condition_id=='Condition_A'").cell_id.iloc[:4]))
    ds.cell_metadata=ds.cell_metadata.iloc[indices].reset_index(drop=True);ds.detection_matrix=ds.detection_matrix[indices]
    b=scan_conditions(ds,cat,tmp_path/'low_support')
    assert not b.associations and 'insufficient_perturbation_cells' in b.reason
    assert b.delta.size==len(ds.conditions)*len(cat.records)


def test_transfer_incompatible_modality_fails_before_scan(full,tmp_path):
    root,path,_=full;cfg=changed_config(path,modality='protein_detection')
    ds=TableDatasetAdapter().load_dataset(cfg);cat=import_frozen_catalogue(root/'run/reference/reference_catalogue.json',cfg)
    assert check_transfer(ds,cat)['status']=='INCOMPATIBLE'
    cfg.paths['reference_catalogue']=str(root/'run/reference/reference_catalogue.json')
    path=tmp_path/'config.yaml';path.write_text(yaml.safe_dump(cfg.model_dump()))
    with pytest.raises(ValueError,match='incompatible transfer'):run_pipeline('transfer',path,tmp_path/'run')
    assert not (tmp_path/'run/perturbation_scan').exists()
    assert json.loads((tmp_path/'run/run_manifest.json').read_text())['status']=='FAILED'


def test_arbitrary_order_schema_but_backend_capacity_explicit():
    assert SignedState(genes=['a','b','c','d'],states=[1,0,1,0],order=4).order==4
    with pytest.raises(ValidationError):SignedState(genes=['a','a'],states=[1,0],order=2)


def test_selected_case_requires_concrete_case_and_selection(full):
    root,_,_=full;case=read_landscape(root/'run').triage_inputs[0]
    result=SelectedCase(case=case,selection_method='human',selection_reason='unit test only',selector='test',
        selected_at='2026-01-01T00:00:00Z',selection_provenance={'scope':'synthetic_schema_validation'})
    assert result.case.states==case.states
    with pytest.raises(ValidationError):SelectedCase.model_validate({'group_id':'M01'})


def test_stop_after_reference_and_scan(full,tmp_path):
    root,path,_=full;cfg=DatasetConfig.load(path);cfg.paths['reference_catalogue']=str(root/'run/reference/reference_catalogue.json')
    p=tmp_path/'cfg.yaml';p.write_text(yaml.safe_dump(cfg.model_dump()))
    for stop in ('reference','perturbation_scan'):
        result=run_pipeline('transfer',p,tmp_path/stop,stop)
        assert not (tmp_path/stop/'landscape').exists()
        assert ('perturbation_scan' in result['stages'])==(stop=='perturbation_scan')


def test_landscape_external_tables_roundtrip_and_order_four(full,tmp_path):
    root,path,_=full;cfg=DatasetConfig.load(path);land=root/'run/landscape'
    cfg.paths={k:str(land/(k+'.csv')) for k in ('effect_matrix','candidate_mask','tested_mask','reason_matrix','support_matrix')}
    cfg.paths.update(reference_catalogue=str(root/'run/reference/reference_catalogue.json'),
        condition_associations=str(root/'run/perturbation_scan/condition_associations.jsonl'))
    pd.DataFrame({'condition_id':cfg.expected_conditions,'condition_n':[3200]*3}).to_csv(tmp_path/'conditions.csv',index=False)
    cfg.paths['condition_metadata']=str(tmp_path/'conditions.csv')
    p=tmp_path/'cfg.yaml';p.write_text(yaml.safe_dump(cfg.model_dump()))
    result=run_pipeline('landscape',p,tmp_path/'run')
    assert result['summary']['associations']==len(read_landscape(root/'run').triage_inputs)
    assert len(read_landscape(tmp_path/'run').response_groups)==len(read_landscape(root/'run').response_groups)
    # Add a fourth signed gene to every reference/case, without using Stage I/II.
    catalogue=json.loads(Path(cfg.paths['reference_catalogue']).read_text())
    for r in catalogue['records']:r['genes'].append('SYN_D');r['states'].append(1);r['order']=4
    write_json(tmp_path/'catalogue4.json',catalogue)
    cases=read_jsonl(cfg.paths['condition_associations'])
    for c in cases:c['genes'].append('SYN_D');c['states'].append(1);c['order']=4
    write_jsonl(tmp_path/'cases4.jsonl',cases)
    cfg.paths.update(reference_catalogue=str(tmp_path/'catalogue4.json'),condition_associations=str(tmp_path/'cases4.jsonl'))
    p.write_text(yaml.safe_dump(cfg.model_dump()));run_pipeline('landscape',p,tmp_path/'run4')
    assert all(c.order==4 for c in read_landscape(tmp_path/'run4').triage_inputs)


def test_weak_profile_and_no_disjoint_pairs_valid(full,tmp_path):
    root,path,_=full;cfg=DatasetConfig.load(path);ds=TableDatasetAdapter().load_dataset(cfg)
    cat=import_frozen_catalogue(root/'run/reference/reference_catalogue.json',cfg)
    b=scan_conditions(ds,cat,tmp_path/'scan')
    keep=[0];b.conditions=[b.conditions[0]]
    for key in ('delta','candidate','tested','reason','support','condition_n'):setattr(b,key,getattr(b,key)[keep])
    b.associations=[a for a in b.associations if a.condition_id==b.conditions[0]]
    land=organize_landscape(b,cfg,tmp_path/'land')
    assert land.quality_audits['status']=='WEAK_OR_UNEVALUABLE' and not land.response_groups
    assert len(land.triage_inputs)==len(b.associations)
    assert not land.coresponse_relations


def test_no_agent_dependency_and_alignment_interface_only():
    root=Path(__file__).parents[1]/'clue_discovery'
    paths=[root/'run.py']+[p for name in ('adapters','reference','perturbation_scan','landscape','schemas','integration') for p in (root/name).rglob('*.py')]
    for p in paths:
        tree=ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):assert not (node.module or '').startswith(('jure.agents','triage'))
            if isinstance(node,ast.Import):assert all(not x.name.startswith(('jure.agents','triage')) for x in node.names)
    with pytest.raises(NotImplementedError):align_landscapes(LandscapeAlignmentRequest(source_landscape='a',target_landscape='b',gene_mapping={},compatibility_audit={}))


def test_transfer_context_difference_requires_prespecified_justification(full):
    root,path,_=full;cfg=changed_config(path,timepoint='new_time')
    cat=import_frozen_catalogue(root/'run/reference/reference_catalogue.json',cfg)
    ds=TableDatasetAdapter().load_dataset(cfg)
    assert check_transfer(ds,cat)['status']=='INCOMPATIBLE'
    cfg.transfer_compatibility={'timepoint':'Prespecified synthetic transfer at a new observation time'}
    assert check_transfer(ds,cat)['status']=='READY'


def test_frozen_day6_regression_read_only():
    # Application regression only: numbers below are not generic algorithm defaults.
    from clue_discovery.adapters.replogle import ReplogleFrozenAdapter
    from clue_discovery.integration.audit import verify_snapshot
    repo=Path(__file__).parents[1]
    cfg=DatasetConfig.load(repo/'configs/clue_discovery/replogle_day6_frozen.yaml')
    b=ReplogleFrozenAdapter().load_bundle(cfg)
    assert len(b.associations)==6129 and len(b.catalogue.records)==341
    assert int(b.candidate.any(1).sum())==419
    assert sum(a.direction=='enrichment' for a in b.associations)==4202
    assert b.provenance['statistics_recomputed'] is False
    snapshot=repo/'outputs/integration_tests/architecture_audit/before_snapshot.json'
    assert verify_snapshot(snapshot,repo)['status']=='PASS'


def test_day8_metadata_smoke_does_not_claim_full_adapter(tmp_path):
    from clue_discovery.integration.audit import day8_aggregate_metadata_smoke
    source=Path(__file__).parents[1]/'dataset_audit/replogle_counts.json'
    result=day8_aggregate_metadata_smoke(source,tmp_path/'audit.json')
    assert result['status']=='PARTIAL_METADATA_ONLY'
    assert not result['expression_accessed'] and not result['full_adapter_ready']
    assert not result['Day8_validation_performed']


def test_scalar_count_hvg_input_preserved(full):
    _,path,_=full;ds=TableDatasetAdapter().load_dataset(DatasetConfig.load(path))
    assert ds.raw_counts is not None
    assert np.array_equal(ds.raw_counts>0,ds.detection_matrix)


def test_candidate_mask_cannot_upgrade_reference_or_mutate_state(full):
    root,_,_=full
    row=read_jsonl(root/'run/perturbation_scan/condition_associations.jsonl')[0]
    row['evidence_level']='REFERENCE_PATTERN'
    with pytest.raises(ValidationError):ConditionAssociation.model_validate(row)
    row['evidence_level']='EXTERNALLY_VALIDATED_ASSOCIATION'
    with pytest.raises(ValidationError):ConditionAssociation.model_validate(row)
