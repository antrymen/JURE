"""Independent discoveries, immutable lock barrier, then opposite-fold testing."""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import resource
import sys
import time

from ..v02.populations import assert_disjoint
from .artifacts import ArtifactStore, code_hashes, digest, software_versions, write_csv, write_json
from .bottom_up import discover
from .catalogue import build_catalogue
from .multiple_testing import MultipleTestingAudit
from .validation import validate_locked


SENTINELS = (
    ('HBD', 'HBZ', 'VGF'), ('HIST1H1C', 'HIST1H4C', 'TMEM158'),
    ('HIST1H1C', 'TMEM158', 'VGF'), ('HIST1H4C', 'TMEM158', 'VGF'),
    ('HBG1', 'HBZ', 'HIST1H4C', 'VGF'))


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def peak_rss_mib():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value/(1024**2 if sys.platform == 'darwin' else 1024)


def opposite_status(record, own, other, validation):
    genes, rid, cid = record['genes'], record['reference_id'], record['candidate_id']
    presence = {g: g in other.hvg_genes for g in genes}
    proposed = next((r for r in other.proposals if r['candidate_id'] == cid), None)
    evaluated = next((r for r in other.records if r['candidate_id'] == cid), None)
    rediscovered = any(r['reference_id'] == rid for r in other.locked)
    v = next((r for r in validation if r['reference_id'] == rid), None)
    if not all(presence.values()):
        stage = 'opposite_hvg_exclusion'
    elif proposed is None:
        stage = 'present_in_hvg_but_not_proposed'
    elif not rediscovered:
        stage = 'proposed_but_not_qualified_in_opposite_discovery'
    elif v is None or not v['cross_fold_replicated']:
        stage = 'rediscovered_but_locked_validation_failed'
    else:
        stage = 'rediscovered_and_locked_validation_passed'
    return dict(reference_id=rid, candidate_id=cid, discovery_fold=own.fold, opposite_fold=other.fold,
        genes_in_opposite_hvg=presence, all_genes_in_opposite_hvg=all(presence.values()),
        candidate_searchable_in_opposite_fold=all(presence.values()),
        candidate_proposed_in_opposite_fold=proposed is not None,
        candidate_evaluated_in_opposite_fold=bool(evaluated and evaluated.get('state_table_computed')),
        exact_state_rediscovered_in_opposite_fold=rediscovered,
        locked_validation_replicated=bool(v and v['cross_fold_replicated']), failure_stage=stage,
        opposite_discovery_failure_reason=evaluated.get('prune_reason') if evaluated else None,
        searchable_definition='All genes eligible in opposite HVG universe; proposal coverage reported separately.')


def summarize_crossfold(discoveries, validations):
    records, summary = [], []
    for fold, other in (('A', 'B'), ('B', 'A')):
        records.extend(opposite_status(r, discoveries[fold], discoveries[other], validations[fold])
                       for r in discoveries[fold].locked)
    for rid in sorted({r['reference_id'] for r in records}):
        directions = {r['discovery_fold']: r for r in records if r['reference_id'] == rid}
        locked = next(r for d in discoveries.values() for r in d.locked if r['reference_id'] == rid)
        summary.append(dict(reference_id=rid, candidate_id=locked['candidate_id'], genes=locked['genes'],
            states=locked['states'], pattern=locked['pattern'], order=locked['order'],
            discovered_in_A='A' in directions, discovered_in_B='B' in directions,
            within_discovery_stable=all(r['within_discovery_stable'] for d in discoveries.values() for r in d.locked if r['reference_id'] == rid),
            cross_fold_replicated=any(r['locked_validation_replicated'] for r in directions.values()),
            independent_rediscovery_in_both_folds=len(directions) == 2,
            replicated_A_to_B=bool(directions.get('A', {}).get('locked_validation_replicated')),
            replicated_B_to_A=bool(directions.get('B', {}).get('locked_validation_replicated')),
            bidirectionally_rediscovered=(len(directions) == 2 and all(r['locked_validation_replicated'] for r in directions.values())),
            directional_evidence=directions))
    return records, summary


def sentinel_audit(discoveries, validations):
    rows = []
    for fold, d in discoveries.items():
        for sentinel in SENTINELS:
            genes = tuple(sorted(sentinel))
            hvg = all(g in d.hvg_genes for g in genes)
            r = next((r for r in d.records if tuple(r['genes']) == genes), None)
            proposed = any(tuple(p['genes']) == genes for p in d.proposals)
            frozen = [p for p in d.locked if tuple(p['genes']) == genes]
            v = [p for p in validations[fold] if tuple(p['genes']) == genes]
            stage = ('hvg_exclusion' if not hvg else 'not_proposed' if not proposed else
                'not_evaluated' if not r or not r.get('state_table_computed') else
                'estimability' if r['estimability_status'] == 'poor' else
                'gain_calibration' if r.get('gain_status') == 'budget_exhausted' else
                'statistical' if not r.get('mfi_ok') or not r.get('gain_ok') else
                'stability' if not frozen else 'validation' if not any(p['cross_fold_replicated'] for p in v) else 'replicated')
            rows.append(dict(genes=genes, order=len(genes), fold=fold, genes_in_hvg={g: g in d.hvg_genes for g in genes},
                all_genes_in_hvg=hvg, proposed=proposed, evaluated=bool(r and r.get('state_table_computed')),
                estimability_status=r.get('estimability_status') if r else 'not_evaluated',
                min_state_count=r.get('min_state_count') if r else None,
                mfi=r.get('mfi') if r else None, set_level_gain=r.get('set_level_gain') if r else None,
                p_gain=r.get('p_gain') if r else None, bootstrap_status=r.get('bootstrap_status') if r else 'not_evaluated',
                kept_states=len(frozen), validated_states=sum(p['cross_fold_replicated'] for p in v),
                failure_stage=stage, failure_reason=r.get('prune_reason') if r else None,
                diagnostic_only=True, injected_into_candidates=False))
    return rows


def known_limitations(discoveries, validations, dry_run, config):
    flags = []
    if any(d.status != 'complete' for d in discoveries.values()):
        flags.extend(['candidate_budget_exhaustion', 'multiple_testing_search_universe_incomplete'])
    if any(d.graph_summary.get('n_edges', 0) == 0 for d in discoveries.values()):
        flags.append('dependency_graph_too_sparse_for_guided_proposals')
    if any(d.graph_summary.get('graph_density', 0) > .2 for d in discoveries.values()):
        flags.append('dependency_graph_dense_relative_to_gene_universe')
    for d in discoveries.values():
        triple = next((s for s in d.order_summaries if s['order'] == 3), {})
        # Uniform exploration coverage is exact for its subchannel, not an estimate of overall recall.
        p = triple.get('exploration', {}).get('inclusion_probability', 0.)
        if p < .01:
            flags.append('exploration_budget_covers_less_than_1_percent_of_triplet_universe')
        evaluated = [r for r in d.records if r.get('state_table_computed')]
        if evaluated and sum(r['estimability_status'] == 'poor' for r in evaluated)/len(evaluated) > .25:
            flags.append('many_candidates_with_poor_estimability')
        if any(r.get('gain_calibration_unstable') for r in evaluated):
            flags.append('gain_null_calibration_unstable_near_decision_boundary')
    if any(r['estimability_status'] != 'good' for vv in validations.values() for r in vv):
        flags.append('validation_sample_sparsity')
    if dry_run:
        flags.append(f'{config.hvg_pool_size}_gene_run_only_dry_run')
    flags += ['global_search_fdr_not_established', 'random_cell_holdout_is_not_biological_replication',
              'raw_count_fano_is_a_proxy_not_normalized_hvg', 'positive_gain_states_only',
              'four_way_gain_not_formally_qualified' if not config.quad_gain_enabled else 'four_way_gain_exploratory']
    return sorted(set(flags))


@dataclass
class PipelineResult:
    discoveries: dict
    validations: dict
    cross_summary: list
    catalogue: object
    manifest: dict


def fit_twofold(population_a, population_b, config, output_dir, *, dataset_manifest=None,
                selections=None, dry_run=False):
    assert_disjoint(population_a, population_b)
    root = Path(output_dir)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError('refuse to overwrite a frozen run; use a new directory/version')
    store, testing = ArtifactStore(root), MultipleTestingAudit()
    started = time.monotonic()
    config_hash = store.freeze_config(config)
    hashes = code_hashes()
    manifest = dict(run_version=config.run_version, run_role='NT_only_reference_development',
        started_at=datetime.now(timezone.utc).isoformat(), config_hash=config_hash, config=config.to_dict(),
        code_hashes=hashes, software_versions=software_versions(), dataset=dataset_manifest or {},
        random_seed=config.random_seed, seed_policy='SHA256(root_seed,role,canonical_genes,stage); recorded in artifacts',
        fold_cell_ids={'A': population_a.cell_ids, 'B': population_b.cell_ids},
        fold_counts={'A': len(population_a.cell_ids), 'B': len(population_b.cell_ids)},
        split_is_biological_replication=False, dry_run=dry_run, status='running',
        perturbation_analysis=False, tn_training=False, agent_calls=False)
    write_json(root/'run_manifest.json', manifest)
    try:
        discoveries = {}
        for fold, population in (('A', population_a), ('B', population_b)):
            discoveries[fold] = discover(population, config, store, testing, fold=fold,
                                         selection=(selections or {}).get(fold), dry_run=dry_run)
        frozen_paths = ['config_frozen.yaml'] + [f'{stem}_{fold}.{suffix}' for fold in ('A', 'B')
            for stem, suffix in [('frozen_candidates', 'csv'), ('discovery', 'json')]]
        # Discovery JSON has an explicit _frozen suffix.
        frozen_paths = [p.replace('.json', '_frozen.json') if p.startswith('discovery_') else p for p in frozen_paths]
        barrier = {p: file_sha(root/p) for p in frozen_paths}
        write_json(root/'both_discoveries_frozen_before_validation.json',
                   dict(frozen_file_hashes=barrier, recorded_at=datetime.now(timezone.utc).isoformat(),
                        validation_started=False, locked_hashes={f: digest(d.locked) for f, d in discoveries.items()}))
        validations, vsets = {}, []
        for source, target, population in (('A', 'B', population_b), ('B', 'A', population_a)):
            validations[source], sets = validate_locked(population, discoveries[source].locked, config, store,
                testing, source_fold=source, validation_fold=target)
            vsets.extend(sets)
            # Keep the discovery-only search log immutable; final lifecycle joins
            # are separate, so validation cannot rewrite candidate decisions.
            final_lifecycle = []
            for record in discoveries[source].records:
                measured = [r for r in validations[source] if r['candidate_id'] == record['candidate_id']]
                state = ('not_discovered' if not record.get('keep') else
                         'disabled_ablation' if config.cross_fold_validation == 'off' else
                         'replicated' if any(r['cross_fold_replicated'] for r in measured) else 'not_replicated')
                final_lifecycle.append(dict(record, validation_status=state,
                    validation_states_tested=len(measured),
                    validation_states_replicated=sum(r['cross_fold_replicated'] for r in measured),
                    validation_result_path=f'locked_validation_{source}_to_{target}.csv'))
            write_csv(root/f'candidate_lifecycle_final_{source}.csv', final_lifecycle,
                      ['candidate_id', 'genes', 'order', 'keep', 'expand', 'prune', 'validation_status'])
        if any(file_sha(root/p) != value for p, value in barrier.items()):
            raise RuntimeError('frozen discoveries or configuration changed during validation')
        detail, cross = summarize_crossfold(discoveries, validations)
        write_csv(root/'cross_fold_searchability.csv', detail, ['reference_id', 'discovery_fold', 'failure_stage'])
        write_csv(root/'cross_fold_summary.csv', cross, ['reference_id', 'genes', 'order', 'bidirectionally_rediscovered'])
        write_csv(root/'sentinel_recovery.csv', sentinel_audit(discoveries, validations))
        all_sets = [dict(r, evaluation_role=f'{f}_discovery') for f, d in discoveries.items() for r in d.records] + vsets
        write_csv(root/'estimability_summary.csv', all_sets, ['candidate_id', 'evaluation_role', 'estimability_status'])
        write_csv(root/'gain_summary.csv', all_sets, ['candidate_id', 'evaluation_role', 'set_level_gain', 'p_gain', 'q_gain'])
        write_csv(root/'bootstrap_summary.csv', [r for r in all_sets if r.get('bootstrap_status') not in (None, 'not_evaluated')],
                  ['candidate_id', 'evaluation_role', 'bootstrap_status', 'bootstrap_path'])
        catalogue = build_catalogue(discoveries, validations, cross, config)
        catalogue.write(root)
        testing_manifest = testing.manifest(generation_complete=all(d.status == 'complete' for d in discoveries.values()))
        write_json(root/'multiple_testing_manifest.json', testing_manifest)
        if code_hashes() != hashes:
            raise RuntimeError('source code changed during run; artifacts retained but run is not frozen-valid')
        manifest.update(status='budget_exhausted' if any(d.status != 'complete' for d in discoveries.values()) else 'complete',
            finished=True, runtime_seconds=time.monotonic()-started, peak_process_rss_mib=peak_rss_mib(),
            peak_memory_scope='process lifetime high-water mark; may include preceding runs in same process',
            output_bytes=sum(p.stat().st_size for p in root.rglob('*') if p.is_file()),
            discovery_frozen_files=barrier, both_discoveries_frozen_before_validation=True,
            catalogue_sha256=catalogue.sha256, catalogue_counts=dict(Counter(r['catalogue_tier'] for r in catalogue.records)),
            order_audits={f: d.order_summaries for f, d in discoveries.items()},
            graph_summaries={f: d.graph_summary for f, d in discoveries.items()},
            limitations=known_limitations(discoveries, validations, dry_run, config),
            crossfold_counts=dict(Counter(r['order'] for r in cross if r['replicated_A_to_B'] or r['replicated_B_to_A'])),
            bidirectional_counts=dict(Counter(r['order'] for r in cross if r['bidirectionally_rediscovered'])),
            formal_global_fdr_control=False, original_code_unchanged_during_run=True)
        write_json(root/'run_manifest.json', manifest)
        return PipelineResult(discoveries, validations, cross, catalogue, manifest)
    except BaseException as exc:
        manifest.update(status='failed', finished=False, error_type=type(exc).__name__, error=str(exc), runtime_seconds=time.monotonic()-started)
        write_json(root/'run_manifest.json', manifest)
        raise
