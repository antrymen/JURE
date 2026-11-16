"""Read-only regression and aggregate-metadata smoke audits."""
from pathlib import Path
import json
from clue_discovery.integration.io import artifact, sha256, write_json

def verify_snapshot(snapshot_path,repo):
    saved=json.loads(Path(snapshot_path).read_text());repo=Path(repo)
    changed=[p for p,h in saved.items() if not (repo/p).is_file() or sha256(repo/p)!=h]
    return {'status':'PASS' if not changed else 'FAIL','files_checked':len(saved),'changed_files':changed,
            'frozen_results_and_preexisting_python_sources_unchanged':not changed}

def legacy_engine_inventory(repo):
    """Scope the old whole-repository hash guard without modifying its frozen manifest."""
    repo=Path(repo)
    frozen=json.loads((repo/'outputs/clue_hunting_v04_validation_family_v1/PROTOCOL_FROZEN.json').read_text())['source_hashes']
    differences=[p for p,h in frozen.items() if not (repo/p).exists() or sha256(repo/p)!=h]
    return {'original_inventory_files':len(frozen),'changed_original_entries':differences,
        'statistical_kernel_changes':[p for p in differences if p.endswith('.py')],
        'legacy_whole_inventory_guard':'does_not_accept_added_files_or_packaging_changes',
        'preexisting_pyproject_difference':True,'frozen_manifest_modified':False}

def day8_aggregate_metadata_smoke(source,output):
    """Only existing aggregate metadata is read. No fake cells or expression matrix."""
    data=json.loads(Path(source).read_text())['TabA_K562_day8_library']
    report={'status':'PARTIAL_METADATA_ONLY','dataset_id':'replogle_k562_day8',
        'source':artifact(source),'source_kind':'published_aggregate_condition_counts',
        'aggregate_total_cells':data['total'],'aggregate_control_cells':data['control'],
        'aggregate_target_count':data['genes'],'control_label':'non-targeting',
        'cell_level_metadata_available':False,'batch_metadata_available':False,'replicate_metadata_available':False,
        'gene_detection_matrix_available':False,'full_adapter_ready':False,
        'missing_count_rows':len(data.get('missing_count_rows',[])),
        'reference_compatibility':'NOT_EVALUABLE_WITH_AGGREGATE_METADATA',
        'expression_accessed':False,'Day8_shift_scan_performed':False,'Day8_validation_performed':False}
    write_json(output,report);return report
