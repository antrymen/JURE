"""Sequential real NT 500/1000 full runs; frozen kernels, no perturbation scan."""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from clue_discovery.v02.populations import assert_disjoint
from clue_discovery.v03.artifacts import code_hashes, digest, write_csv, write_json
from clue_discovery.v03.data import load_prepared, file_hash, KNOWN_REPLOGLE_MD5
from clue_discovery.v03.multiple_testing import MultipleTestingAudit
from clue_discovery.v03.validation import validate_locked
from clue_discovery.v04.bottom_up import discover
from clue_discovery.v04.catalogue import build_catalogue
from clue_discovery.v04.config import ScalableConfig
from clue_discovery.v04.pipeline import summarize_crossfold, peak_rss_mib
from clue_discovery.v04_validation.experiment import CompactArtifactStore
from clue_discovery.v04_validation.policy import freeze_family, evaluate_family

REPO = Path(__file__).resolve().parents[1]


def source_hashes():
    result = code_hashes()
    result.update({str(p.relative_to(REPO)): file_hash(p)
                   for p in sorted((REPO/'real_nt_v04_holm').iterdir())
                   if p.is_file() and p.suffix in ('.py','.md','.json')})
    return result


def verify_frozen_engine():
    frozen = json.loads((REPO/'outputs/clue_hunting_v04_validation_family_v1/PROTOCOL_FROZEN.json').read_text())
    if code_hashes() != frozen['source_hashes']:
        raise RuntimeError('v0.4 or validation-family source changed since synthetic acceptance')


def export_catalogue(discoveries, validations, corrected_sets, corrected_states, populations, config, root):
    """Keep original primary vetoes; export Holm qualification as a separate field."""
    _, cross = summarize_crossfold(discoveries, validations)
    original = build_catalogue(discoveries, validations, cross, config)
    original.write(root/'original_v04_catalogue')
    selected = [s for s in corrected_states if s['arm']=='holm_025' and s['qualified']]
    ids = {s['reference_id'] for s in selected}
    all_records = {r['reference_id']:r for r in original.records}
    genes = sorted({g for rid in ids for g in all_records[rid]['genes']})
    encoded = {f:p.encode(genes,config)[0] for f,p in populations.items()} if genes else {}
    records = []
    for rid in sorted(ids):
        base = all_records[rid]
        directions = [s['family_id'].split(':')[0] for s in selected if s['reference_id']==rid]
        counts = {}
        for fold, matrix in encoded.items():
            mask = (matrix.loc[:,list(base['genes'])].to_numpy()==base['states']).all(axis=1)
            n, support = len(mask), int(mask.sum())
            counts[fold] = dict(n_cells=n,support=support,frequency=support/n)
        n = sum(v['n_cells'] for v in counts.values())
        support = sum(v['support'] for v in counts.values())
        tests = [r for r in corrected_sets if r['arm']=='holm_025' and r['candidate_id']==base['candidate_id']]
        records.append(dict(reference_id=rid,candidate_id=base['candidate_id'],genes=base['genes'],
            states=base['states'],pattern=base['pattern_string'],order=3,
            encoding=dict(input_kind='raw_counts',positive='count > 0',negative='count == 0'),
            nt_support=support,nt_n_cells=n,nt_frequency=support/n,nt_counts_by_fold=counts,
            pooled_nt_frequency_is_descriptive=True,
            successful_directions=sorted(directions),bidirectionally_qualified=len(directions)==2,
            holm_qualified=True,holm_level_per_direction=.025,
            discovery_bootstrap_stable=True,validation_bootstrap_stable=True,
            validation_family_tests=tests,discovery_evidence=base['discovery_evidence'],
            validation_evidence=base['validation_evidence'],quality_flags=base['quality_flags'],
            original_catalogue_tier=base['catalogue_tier'],complete_search=base['complete_search'],
            status='HolmQualifiedNTReferencePattern',state_level_FDR_controlled=False,
            biological_replicate_validated=False,perturbation_evidence_present=False,
            eligible_for_agent_investigation=False,
            shift_baseline_requires_prespecified_selection_aware_or_independent_control_design=True))
    payload = dict(schema_version=1,object_type='HolmQualifiedNTReferenceCatalogue',
        config_hash=config.sha256,source_hashes=source_hashes(),records=records,
        family_scope='all discovery-locked triplet gene sets per direction',
        formal_bound='two-direction gene-set FWER <= 0.05 conditional on valid held-out p-values',
        state_level_FDR_controlled=False,perturbation_evidence_present=False,
        budget_limited_search=True,original_primary_vetoes_preserved=True)
    write_json(root/'holm_reference_catalogue_frozen.json',dict(payload=payload,sha256=digest(payload)))
    write_csv(root/'holm_reference_patterns.csv',records,
              ['reference_id','genes','states','pattern','nt_support','nt_n_cells','nt_frequency'])
    return records


def run_reference(populations, selections, metadata, config, output):
    root = Path(output)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError('refuse overwrite of real NT run')
    assert_disjoint(populations['A'],populations['B'])
    hashes, started = source_hashes(), time.monotonic()
    store = CompactArtifactStore(root); store.freeze_config(config)
    audit = MultipleTestingAudit()
    status = dict(status='running',config=config.to_dict(),config_hash=config.sha256,
                  source_hashes=hashes,dataset=metadata,dry_run=False,
                  biological_replicate_validation=False,perturbation_analysis=False,agent_calls=False)
    def progress(phase):
        status['phase']=phase; write_json(root/'run_status.json',status)
        print(json.dumps(dict(size=config.hvg_pool_size,phase=phase)),flush=True)
    try:
        discoveries = {}
        for fold in ('A','B'):
            progress('discovery_'+fold)
            discoveries[fold]=discover(populations[fold],config,store,audit,fold=fold,selection=selections.get(fold))
        families={f:freeze_family(discoveries[f].locked,source_fold=f,validation_fold=t)
                  for f,t in [('A','B'),('B','A')]}
        write_json(root/'validation_families_frozen.json',dict(
            families={f:v.to_dict() for f,v in families.items()},validation_started=False))
        filenames=['config_frozen.yaml','validation_families_frozen.json']
        filenames += [f'discovery_{f}_frozen.json' for f in ('A','B')]
        filenames += [f'frozen_candidates_{f}.csv' for f in ('A','B')]
        barrier={name:file_hash(root/name) for name in filenames}
        write_json(root/'both_discoveries_and_families_frozen_before_validation.json',barrier)
        validations,infos={},[]
        all_sets,all_states=[],[]
        for source,target in [('A','B'),('B','A')]:
            progress(f'validation_{source}_to_{target}')
            rows,sets=validate_locked(populations[target],discoveries[source].locked,config,store,audit,
                                      source_fold=source,validation_fold=target)
            validations[source]=rows
            result,states,info=evaluate_family(families[source],discoveries[source].locked,sets,rows)
            all_sets.extend(result);all_states.extend(states);infos.extend(info)
        if any(file_hash(root/name)!=value for name,value in barrier.items()):
            raise RuntimeError('frozen discovery or family changed')
        write_csv(root/'corrected_gene_sets.csv',all_sets,['candidate_id','arm','family_gain_rejected'])
        write_csv(root/'corrected_states.csv',all_states,['reference_id','arm','qualified'])
        write_json(root/'family_results.json',infos)
        progress('catalogue_export')
        records=export_catalogue(discoveries,validations,all_sets,all_states,populations,config,root)
        if source_hashes()!=hashes: raise RuntimeError('source changed during real NT run')
        summary=dict(size=config.hvg_pool_size,nt_cells=sum(len(p.cell_ids) for p in populations.values()),
            family_sizes={f:len(v.members) for f,v in families.items()},
            qualified_states_by_arm={a:len({s['reference_id'] for s in all_states if s['arm']==a and s['qualified']})
                                     for a in ('raw_05','bh_05','bh_025','holm_025')},
            holm_qualified_gene_sets=len({r['candidate_id'] for r in records}),
            holm_qualified_states=len(records),holm_bidirectional_states=sum(r['bidirectionally_qualified'] for r in records),
            original_primary_states=sum(r['original_catalogue_tier']=='primary' for r in records),
            discovery_status={f:d.status for f,d in discoveries.items()},
            runtime_seconds=time.monotonic()-started,peak_process_rss_mib=peak_rss_mib(),
            perturbation_associated_clues=0,dry_run=False)
        write_json(root/'summary.json',summary)
        status.update(status='complete',phase='complete',summary=summary,source_unchanged=True)
        write_json(root/'run_status.json',status)
        return summary
    except BaseException as error:
        status.update(status='failed',error=str(error));write_json(root/'run_status.json',status);raise


def compress_csvs(root):
    manifest={}
    for path in sorted(root.rglob('*.csv')):
        # Preserve small user-facing catalogue and frozen barrier files directly.
        if path.name.startswith(('holm_reference','frozen_candidates')): continue
        target=path.with_suffix('.csv.gz')
        with path.open('rb') as src,gzip.open(target,'wb',compresslevel=1) as dst:
            shutil.copyfileobj(src,dst)
        manifest[str(path.relative_to(root))]=dict(path=str(target.relative_to(root)),
            original_sha256=file_hash(path),compressed_sha256=file_hash(target))
        path.unlink()
    write_json(root/'compressed_csv_manifest.json',manifest)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--worker-size',type=int,choices=(500,1000))
    args=parser.parse_args(); root=Path(args.output_dir)
    verify_frozen_engine()
    if file_hash(Path(args.prepared)/'data_manifest.json') != file_hash(REPO/'real_nt_v04_holm/EXPECTED_PREPARED_MANIFEST.json'):
        raise ValueError('prepared manifest differs from the previously audited real NT cache')
    if args.worker_size:
        config=replace(ScalableConfig(),hvg_pool_size=args.worker_size)
        populations,selections,metadata=load_prepared(args.prepared,config)
        if (not metadata.get('real_data_used') or not metadata.get('nt_only') or
            metadata.get('n_cells')!=10691 or metadata.get('source_md5')!=KNOWN_REPLOGLE_MD5):
            raise ValueError('expected verified 10691 NT Replogle preparation')
        run_reference(populations,selections,metadata,config,root)
        compress_csvs(root)
        return
    if root.exists() and any(root.iterdir()): raise FileExistsError('new real run requires empty output')
    for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[key]='1'
    hashes=source_hashes()
    plan=dict(scales=[500,1000],primary_catalogue_scale=1000,scale500_role='predeclared_scale_diagnostic',
        do_not_merge_or_choose_scale_after_outcomes=True,source_hashes=hashes,
        registered_at=datetime.now(timezone.utc).isoformat(),prepared_path=str(Path(args.prepared).resolve()),
        prepared_manifest_sha256=file_hash(Path(args.prepared)/'data_manifest.json'),
        configs={str(n):replace(ScalableConfig(),hvg_pool_size=n).to_dict() for n in (500,1000)},
        correction='Holm adjusted p<=0.025 per direction; same policy as accepted synthetic experiment',
        perturbation_scan=False,agent_calls=False,failures_retained_without_retuning=True)
    write_json(root/'PROTOCOL_FROZEN.json',plan)
    summaries=[]
    try:
        for size in (500,1000):
            write_json(root/'execution_status.json',dict(status='running',current_size=size,completed_sizes=[r['size'] for r in summaries]))
            command=[sys.executable,'-m','nt_reference_experiment.measure','--output',str(root/f'resources_{size}.json'),
                '--rss-limit-mib','1400','--',sys.executable,'-m','real_nt_v04_holm.run',
                '--prepared',args.prepared,'--output-dir',str(root/f'genes_{size}_full'),'--worker-size',str(size)]
            with (root/f'run_{size}.log').open('w') as log:
                result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
            if result.returncode: raise RuntimeError(f'{size}-gene process failed with exit {result.returncode}')
            summaries.append(json.loads((root/f'genes_{size}_full/summary.json').read_text()))
            if source_hashes()!=hashes: raise RuntimeError('source changed between stages')
            write_json(root/'summaries.json',summaries)
        write_json(root/'execution_status.json',dict(status='complete',completed_sizes=[500,1000],source_unchanged=True))
    except BaseException as error:
        write_json(root/'execution_status.json',dict(status='failed',error=str(error),completed_sizes=[r['size'] for r in summaries]));raise


if __name__=='__main__':
    main()
