"""Unified three-stage CLI. Does not import or execute downstream Agents."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import resource
import sys
import time
from clue_discovery.adapters import DatasetConfig, TableDatasetAdapter
from clue_discovery.adapters.base import GLOBAL_METHOD_DEFAULTS
from clue_discovery.integration.io import artifact, sha256, write_json, write_jsonl
from clue_discovery.schemas import SCHEMA_VERSION, METHOD_VERSION
from clue_discovery.reference import discover_reference, import_frozen_catalogue, check_transfer
from clue_discovery.perturbation_scan import scan_conditions
from clue_discovery.landscape import organize_landscape


def run_pipeline(mode,config_path,output,stop_after='landscape'):
    cfg=DatasetConfig.load(config_path);out=Path(output).resolve()
    if out.exists() and any(out.iterdir()):raise FileExistsError('refuse overwrite; choose an empty output directory')
    if mode not in ('full','transfer','landscape') or stop_after not in ('reference','perturbation_scan','landscape'):
        raise ValueError('invalid mode/stage')
    if mode=='landscape' and stop_after!='landscape':raise ValueError('landscape mode only runs Stage III')
    if cfg.adapter=='replogle_frozen' and mode!='landscape':raise ValueError('frozen adapter is read-only landscape import; no real-data rerun')
    out.mkdir(parents=True,exist_ok=True);started=time.monotonic()
    from clue_discovery.v04.config import ScalableConfig
    from broad_screening.config import Config
    reference_cfg=replace(ScalableConfig(),**cfg.candidate_budget,n_bootstrap=cfg.bootstrap_config['reference_repetitions'],random_seed=cfg.seed)
    landscape_cfg=Config(**cfg.landscape_config,seed=cfg.seed,bootstrap_repetitions=cfg.bootstrap_config['landscape_repetitions']).validate()
    frozen={'GLOBAL_METHOD_DEFAULTS':GLOBAL_METHOD_DEFAULTS,'DATASET_CALIBRATION':cfg.model_dump(mode='json'),
        'RUN_FROZEN_CONFIG':{'resolved_reference_backend':asdict(reference_cfg),'resolved_landscape_backend':asdict(landscape_cfg),
            'shift_support':cfg.min_cells,'shift_testing':cfg.multiple_testing_config,'mode':mode,'stop_after':stop_after}}
    write_json(out/'RUN_FROZEN_CONFIG.json',frozen)
    repo=Path(__file__).resolve().parents[1]
    code={str(p.relative_to(repo)):sha256(p) for name in ('clue_discovery','broad_screening','perturbation_scan','landscape_analysis','real_nt_v04_holm')
        for p in (repo/name).rglob('*.py')}
    manifest={'schema_version':SCHEMA_VERSION,'method_version':METHOD_VERSION,'dataset_id':cfg.dataset_id,
        'started_utc':datetime.now(timezone.utc).isoformat(),'status':'RUNNING','mode':mode,'seed':cfg.seed,
        'config':artifact(config_path),'frozen_config':artifact(out/'RUN_FROZEN_CONFIG.json'),
        'inputs':{k:artifact(p) for k,p in cfg.paths.items() if Path(p).is_file()},
        'source_hashes':code,'stages':{},'warnings':[],'external_validation_performed':False,'agent_calls':False}
    write_json(out/'run_manifest.json',manifest)
    bundle=landscape=catalogue=None
    def stage(name,status,scope):
        manifest['stages'][name]={'status':status,'evidence_scope':scope}
        write_json(out/name/'EVIDENCE_SCOPE.json',scope)
    try:
        if mode=='landscape':
            if cfg.adapter=='replogle_frozen':
                from clue_discovery.adapters.replogle import ReplogleFrozenAdapter
                adapter=ReplogleFrozenAdapter();bundle=adapter.load_bundle(cfg);catalogue=bundle.catalogue
                landscape=adapter.load_landscape(cfg,bundle,out/'landscape')
            else:
                from clue_discovery.adapters.external import load_external_bundle
                bundle=load_external_bundle(cfg);catalogue=bundle.catalogue
                landscape=organize_landscape(bundle,cfg,out/'landscape')
            stage('reference','IMPORTED',{'evidence_level':'REFERENCE_PATTERN','recomputed':False})
            stage('perturbation_scan','IMPORTED',{'evidence_levels':sorted({a.evidence_level.value for a in bundle.associations}),'recomputed':False})
        else:
            ds=TableDatasetAdapter().load_dataset(cfg)
            write_json(out/'dataset_adapter_audit.json',{'dataset_id':ds.dataset_id,'n_cells':len(ds.cell_metadata),
                'conditions':ds.conditions,'genes':ds.genes,'controls':ds.control_labels,
                'reference_population_available':ds.reference_available,'provenance':ds.provenance})
            if mode=='full':catalogue=discover_reference(ds,out/'reference')
            else:
                catalogue=import_frozen_catalogue(cfg.paths['reference_catalogue'],cfg)
                audit=check_transfer(ds,catalogue);write_json(out/'transfer_compatibility.json',audit)
                if audit['status']=='INCOMPATIBLE':raise ValueError('incompatible transfer; see transfer_compatibility.json')
                if audit['status']!='READY':manifest['warnings'].append(audit['status'])
            stage('reference','COMPLETED' if mode=='full' and ds.reference_available and catalogue.provenance.get('status')!='reference_population_unavailable' else 'IMPORTED' if mode=='transfer' else 'UNAVAILABLE',
                {'evidence_level':'REFERENCE_PATTERN','crossfold_is_biological_replication':False,'state_level_FDR_controlled':False})
            if stop_after!='reference':
                bundle=scan_conditions(ds,catalogue,out/'perturbation_scan')
                stage('perturbation_scan','COMPLETED',{'evidence_level':'EXPLORATORY_ASSOCIATION',
                    'reference_states_frozen':True,'state_search':False,'nt_selection_adjusted':False,
                    'effect':'matched_prevalence_difference_not_change_in_interaction_strength'})
                if stop_after=='landscape':landscape=organize_landscape(bundle,cfg,out/'landscape')
        write_json(out/'reference/reference_catalogue.json',catalogue)
        if bundle is not None:write_jsonl(out/'perturbation_scan/condition_associations.jsonl',bundle.associations)
        if landscape is not None:stage('landscape','COMPLETED',landscape.evidence_scope)
        manifest['reference_catalogue_hash']=sha256(out/'reference/reference_catalogue.json')
        if landscape is not None:
            manifest['warnings'].extend(landscape.quality_audits.get('kernel_warnings',[]))
            if landscape.quality_audits.get('status') in ('EMPTY','WEAK_OR_UNEVALUABLE'):
                manifest['warnings'].append(landscape.quality_audits['status'])
        manifest['summary']={'reference_states':len(catalogue.records),'associations':len(bundle.associations) if bundle else None,
            'response_groups':len(landscape.response_groups) if landscape else None,'selected_cases':0,
            'requested_stop_after':stop_after,'unrun_stages':[s for s in ('reference','perturbation_scan','landscape') if s not in manifest['stages']]}
        manifest['status']='COMPLETE'
    except Exception as error:
        manifest.update(status='FAILED',error=str(error));raise
    finally:
        current={p:sha256(repo/p) for p in code}
        manifest['original_source_files_unchanged_during_run']=current==code
        manifest['resources']={'runtime_seconds':time.monotonic()-started,
            'peak_process_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),
            'python':sys.version.split()[0]}
        manifest['outputs']={str(p.relative_to(out)):sha256(p) for p in out.rglob('*') if p.is_file() and p.name!='run_manifest.json'}
        write_json(out/'run_manifest.json',manifest)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',required=True,choices=('full','transfer','landscape'))
    parser.add_argument('--dataset-config',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--stop-after',choices=('reference','perturbation_scan','landscape'),default='landscape')
    args=parser.parse_args();result=run_pipeline(args.mode,args.dataset_config,args.output,args.stop_after)
    print(result['status'],result['summary'])

if __name__=='__main__':main()
