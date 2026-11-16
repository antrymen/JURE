"""Frozen search-recovery benchmark separating search coverage from power.

Synthetic truth is used only to generate data and annotate completed discoveries;
no target tuple, truth label, or seed search is passed to the proposal layer.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
from itertools import product
import math
from pathlib import Path
import resource
import sys
import time

import numpy as np

from ..v02.populations import Population, assert_disjoint
from .artifacts import ArtifactStore, code_hashes, digest, software_versions, write_csv, write_json
from .bottom_up import discover
from .candidate import candidate_id
from .config import ScalableConfig
from .multiple_testing import MultipleTestingAudit
from .validation import validate_locked


def _seed(seed, label):
    return int.from_bytes(hashlib.sha256(f'{seed}:search_recovery:{label}'.encode()).digest()[:8], 'big')


def _states(order):
    return np.asarray(list(product((0, 1), repeat=order)), dtype=np.uint8)


def _distribution(kind):
    order = 4 if kind == 'pure_four_way' else 3
    states = _states(order)
    if kind == 'pairwise_only':
        spins = 2*states.astype(float)-1
        log_weights = .55*(spins[:, 0]*spins[:, 1] + spins[:, 0]*spins[:, 2] + spins[:, 1]*spins[:, 2])
        probabilities = np.exp(log_weights-log_weights.max())
    elif kind in {'pure_three_way', 'pure_four_way'}:
        # Strictly positive parity distribution with all lower marginals uniform.
        probabilities = 1 + .65*np.where(states.sum(axis=1) % 2 == 0, 1, -1)
    else:
        raise ValueError('unknown planted module')
    probabilities /= probabilities.sum()
    return states, probabilities


def generate_search_recovery_populations(*, random_seed=20260927, n_cells=12000,
                                         universe_size=100, include_four_way=True,
                                         tiny=False):
    """Generate two independent samples, not duplicated cells or exact tables."""
    if isinstance(n_cells, bool) or not isinstance(n_cells, int) or n_cells < 200:
        raise ValueError('search recovery requires at least 200 total cells')
    modules = [('pure_three_way', ('T0', 'T1', 'T2'))] if tiny else [
        ('pairwise_only', ('P0', 'P1', 'P2')),
        ('pure_three_way', ('T0', 'T1', 'T2'))]
    if include_four_way and not tiny:
        modules.append(('pure_four_way', ('Q0', 'Q1', 'Q2', 'Q3')))
    used = sum(len(genes) for _, genes in modules)
    if universe_size < used or (tiny and universe_size != 3):
        raise ValueError('gene universe cannot contain the requested planted modules')
    genes = tuple(gene for _, group in modules for gene in group) + tuple(f'N{i:03}' for i in range(universe_size-used))
    truth = [{'module': kind, 'genes': tuple(sorted(group)), 'order': len(group),
              'candidate_id': candidate_id(group), 'genuine_highest_order': kind != 'pairwise_only',
              'purpose': 'positive_higher_order_target' if kind != 'pairwise_only' else 'negative_higher_order_control'}
             for kind, group in modules]
    distribution_records = []
    for kind, group in modules:
        states, probabilities = _distribution(kind)
        distribution_records.append({'module': kind, 'genes': group, 'states': states,
            'probabilities': probabilities, 'generation_rule': ('pairwise_Ising_all_edges_J_0.55_zero_fields'
                if kind == 'pairwise_only' else 'strictly_positive_parity_amplitude_0.65')})
    populations, seeds, hashes = {}, {}, {}
    sizes = {'A': n_cells//2, 'B': n_cells-n_cells//2}
    for fold, n in sizes.items():
        seed = _seed(random_seed, 'tiny_'+fold if tiny else 'large_'+fold)
        seeds[fold] = seed
        rng = np.random.default_rng(seed)
        matrix = rng.binomial(1, .5, (n, universe_size)).astype(np.uint8)
        offset = 0
        for kind, group in modules:
            states, probabilities = _distribution(kind)
            matrix[:, offset:offset+len(group)] = states[rng.choice(len(states), size=n, p=probabilities)]
            offset += len(group)
        cells = tuple(f'synthetic_{"tiny" if tiny else "large"}_{fold}_{i:06}' for i in range(n))
        populations[fold] = Population(matrix, genes, cells)
        hashes[fold] = {'matrix_sha256': hashlib.sha256(matrix.tobytes(order='C')).hexdigest(),
                        'cell_ids_sha256': digest(cells), 'genes_sha256': digest(genes)}
    assert_disjoint(populations['A'], populations['B'])
    metadata = {'source': 'synthetic_independent_iid_folds', 'random_seed': random_seed,
        'fold_generation_seeds': seeds, 'n_cells': n_cells, 'fold_sizes': sizes,
        'gene_universe_size': universe_size, 'null_gene_count': universe_size-used,
        'modules': distribution_records, 'truth_used_for_proposal': False,
        'seed_selected_for_recovery': False, 'dataset_hashes': hashes,
        'tiny_positive_control': tiny}
    return populations, truth, metadata


def _target_diagnostics(result, validation_rows, truth, *, mode):
    proposed = {row['candidate_id'] for row in result.proposals}
    evaluated = {row['candidate_id']: row for row in result.records}
    locked_ids = {row['candidate_id'] for row in result.locked}
    validated = {row['candidate_id'] for row in validation_rows if row['cross_fold_replicated']}
    rows = []
    for target in truth:
        cid = target['candidate_id']
        record = evaluated.get(cid, {})
        in_pool = set(target['genes']).issubset(result.hvg_genes)
        is_evaluated = bool(record.get('state_table_computed'))
        if not in_pool:
            stage, reason = 'search_failure', 'not_selected_in_discovery_hvg_pool'
        elif cid not in proposed:
            stage, reason = 'search_failure', 'not_proposed_by_frozen_search'
        elif not is_evaluated:
            stage, reason = 'search_failure', record.get('prune_reason', 'not_evaluated')
        elif record.get('estimability_status') == 'poor':
            stage, reason = 'estimation_failure', 'poor_estimability'
        elif 'budget_exhausted' in str(record.get('prune_reason')):
            stage, reason = 'resource_budget_failure', record['prune_reason']
        elif not record.get('mfi_ok') or not record.get('gain_ok'):
            stage, reason = 'statistical_failure', record.get('prune_reason') or 'mfi_or_gain_failed'
        elif cid not in locked_ids:
            stage, reason = 'stability_failure', record.get('prune_reason') or 'bootstrap_or_pattern_failed'
        elif cid not in validated:
            stage, reason = 'stability_failure', 'opposite_fold_locked_validation_failed_or_disabled'
        else:
            stage, reason = 'recovered', 'at_least_one_locked_exact_state_replicated'
        rows.append({**target, 'candidate_mode': mode, 'fold': result.fold,
            'genes_in_hvg_pool': in_pool, 'candidate_proposed': cid in proposed,
            'candidate_evaluated': is_evaluated, 'estimability_status': record.get('estimability_status', 'not_evaluated'),
            'mfi_ok': record.get('mfi_ok', False), 'gain_ok': record.get('gain_ok', False),
            'gain_status': record.get('gain_status', 'not_evaluated'),
            'within_discovery_stable': record.get('within_discovery_stable', False),
            'candidate_locked': cid in locked_ids, 'cross_fold_replicated': cid in validated,
            'failure_stage': stage, 'reason': reason,
            'negative_control_correctly_not_recovered': (not target['genuine_highest_order'] and cid not in validated),
            'proposal_sources': record.get('proposal_sources', [])})
    return rows


def _run_case(path, populations, truth, data_metadata, config):
    started = time.monotonic()
    path = Path(path)
    if path.exists() and any(path.iterdir()):
        raise FileExistsError('search recovery case already exists; use a new output directory')
    store, audit = ArtifactStore(path), MultipleTestingAudit()
    store.freeze_config(config)
    initial_hashes = code_hashes()
    write_json(path/'run_manifest.json', {'run_role': 'synthetic_search_recovery',
        'config': config.to_dict(), 'config_hash': config.sha256, 'data': data_metadata,
        'software_versions': software_versions(), 'code_hashes': initial_hashes,
        'truth_used_for_proposal': False, 'real_data_used': False,
        'protocol': 'discover_both_independently_freeze_both_then_locked_validation'})
    results = {fold: discover(populations[fold], config, store, audit, fold=fold) for fold in ('A', 'B')}
    frozen_hashes = {fold: digest(result.locked) for fold, result in results.items()}
    write_json(path/'both_discoveries_frozen.json', {'locked_hashes': frozen_hashes,
        'validation_started': False, 'data_independent_fold_ids': True})
    validations, target_rows = {}, []
    for source, destination in (('A', 'B'), ('B', 'A')):
        rows, _ = validate_locked(populations[destination], results[source].locked, config, store, audit,
            source_fold=source, validation_fold=destination)
        validations[source] = rows
        target_rows.extend(_target_diagnostics(results[source], rows, truth, mode=config.candidate_mode))
    if frozen_hashes != {fold: digest(result.locked) for fold, result in results.items()}:
        raise RuntimeError('locked discovery records changed during validation')
    write_csv(path/'search_recovery_targets.csv', target_rows)
    write_json(path/'synthetic_truth.json', {'targets': truth, 'use': 'posthoc_diagnostics_only_not_search_input'})
    write_json(path/'multiple_testing_manifest.json', audit.manifest(generation_complete=True))
    true_ho = {target['candidate_id'] for target in truth if target['genuine_highest_order']}
    proposals = {row['candidate_id']: row for result in results.values() for row in result.proposals}
    validations_all = [row for rows in validations.values() for row in rows]
    recovered_ho = {row['candidate_id'] for row in validations_all if row['order'] >= 3 and row['cross_fold_replicated']}
    proposed_targets = {row['candidate_id'] for row in target_rows if row['candidate_proposed']}
    true_proposed = set(proposals) & true_ho
    unknown_proposals = {cid for cid, row in proposals.items() if row['order'] >= 3 and cid not in true_ho}
    order3_n = {fold: next(row['exploration']['n_sample'] for row in result.order_summaries if row['order'] == 3)
                for fold, result in results.items()}
    universe = math.comb(len(populations['A'].gene_names), 3)
    p = {fold: n/universe for fold, n in order3_n.items()}
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if sys.platform == 'darwin' else 1024)
    summary = {'case': path.name, 'candidate_mode': config.candidate_mode,
        'gene_universe_size': len(populations['A'].gene_names), 'n_cells': sum(len(p.cell_ids) for p in populations.values()),
        'n_target_modules': len(truth), 'n_true_higher_order_modules': len(true_ho),
        'candidate_recall': len(proposed_targets)/len(truth),
        'true_higher_order_candidate_recall': len(true_proposed)/len(true_ho),
        'true_higher_order_recovery': len(recovered_ho & true_ho)/len(true_ho),
        'true_higher_order_recovered_gene_sets': sorted(recovered_ho & true_ho),
        'cross_fold_false_positive_highest_order_gene_sets': sorted(recovered_ho-true_ho),
        'cross_fold_false_positive_highest_order_gene_set_count': len(recovered_ho-true_ho),
        'unique_candidates_proposed': len(proposals),
        'false_candidate_proposal_count': len(unknown_proposals),
        'false_candidate_proposal_definition': 'order>=3 proposed tuple other than exact planted genuine highest-order modules; proposal is not a discovery claim',
        'candidate_recall_definition': 'any-fold proposal of exact module tuple, including pairwise-only negative-control triplet',
        'true_recovery_definition': 'any-fold discovery with at least one exact locked state replicated; order4 remains MFI-only exploratory when quad_gain_enabled=false',
        'exploration_triplet_samples_per_fold': order3_n,
        'exploration_target_inclusion_probability_per_fold': p,
        'exploration_target_inclusion_probability_any_fold': 1-(1-p['A'])*(1-p['B']),
        'exploration_probability_scope': 'uniform sampling mechanism expectation over seed; does not guarantee recovery in this frozen run',
        'failure_stage_counts': {stage: sum(row['failure_stage'] == stage for row in target_rows)
                               for stage in sorted({row['failure_stage'] for row in target_rows})},
        'budget_exhausted': any(result.status == 'budget_exhausted' for result in results.values()),
        'bootstrap_gene_sets': sum(row['bootstrap_gene_sets'] for result in results.values() for row in result.order_summaries),
        'runtime_seconds': time.monotonic()-started, 'peak_process_rss_mib': rss,
        'peak_memory_scope': 'process_cumulative_high_water_mark_not_isolated_case_peak',
        'config_hash': config.sha256, 'source': 'synthetic_independent_iid_folds',
        'n_bootstrap': config.n_bootstrap, 'n_null_simulations': config.n_null_simulations,
        'candidate_mode_only_ablation': True, 'no_parameter_retuning': True,
        'code_unchanged_during_case': initial_hashes == code_hashes()}
    write_json(path/'summary.json', summary)
    summary['disk_usage_mb'] = sum(p.stat().st_size for p in path.rglob('*') if p.is_file())/1024**2
    write_json(path/'summary.json', summary)
    return summary, target_rows


def run_search_recovery(output_dir, config=None, *, n_cells=12000, universe_size=100,
                        include_four_way=True, run_tiny_positive=True):
    """Run three frozen modes on one universe, plus a separate tiny positive path.

    Default inference uses 1000 bootstraps and 1999 null simulations. A caller can
    provide a clearly labelled smoke configuration; no parameter is tuned to an
    observed target, and no target is injected into candidate proposals.
    """
    config = config or ScalableConfig()
    if config.max_order < 3:
        raise ValueError('search recovery requires max_order >=3')
    root = Path(output_dir)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError('search recovery output must be new/empty')
    root.mkdir(parents=True, exist_ok=True)
    frozen = replace(config, hvg_pool_size=universe_size)
    populations, truth, data = generate_search_recovery_populations(random_seed=frozen.random_seed,
        n_cells=n_cells, universe_size=universe_size, include_four_way=include_four_way)
    summaries, targets = [], []
    write_json(root/'benchmark_protocol.json', {'base_config': frozen.to_dict(), 'base_config_hash': frozen.sha256,
        'modes': ['dependency_only', 'exploration_only', 'hybrid'], 'data': data,
        'truth_not_passed_to_discovery': True, 'tiny_positive_is_separate_universe': True,
        'mode_list_and_seeds_fixed_before_results': True})
    for mode in ('dependency_only', 'exploration_only', 'hybrid'):
        summary, rows = _run_case(root/mode, populations, truth, data, replace(frozen, candidate_mode=mode))
        summaries.append(summary)
        targets.extend({'case': mode, **row} for row in rows)
    if run_tiny_positive:
        tiny_pops, tiny_truth, tiny_data = generate_search_recovery_populations(random_seed=frozen.random_seed,
            n_cells=n_cells, universe_size=3, include_four_way=False, tiny=True)
        tiny_config = replace(frozen, hvg_pool_size=3, max_order=3, candidate_mode='exploration_only')
        summary, rows = _run_case(root/'tiny_three_gene_positive_path', tiny_pops, tiny_truth, tiny_data, tiny_config)
        summaries.append(summary)
        targets.extend({'case': 'tiny_three_gene_positive_path', **row} for row in rows)
    write_csv(root/'search_recovery_summary.csv', summaries)
    write_csv(root/'search_recovery_targets.csv', targets)
    write_json(root/'summary.json', {'cases': summaries, 'targets': targets,
        'real_data_used': False, 'no_positive_dependent_resampling_or_parameter_retuning': True})
    lines = ['# Synthetic Search Recovery Benchmark', '',
        'Truth is used only for synthetic generation and post-run diagnostics. Every mode uses the same independent folds. '
        'The graph, proposal, Gain, bootstrap and locked validation calls are the production v0.3 path.', '',
        '| Case | Gene pool | Candidate recall | True HO proposal recall | True HO locked recovery | Off-target HO proposals | Cross-fold false HO sets | Runtime (s) |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in summaries:
        lines.append(f"| {row['case']} | {row['gene_universe_size']} | {row['candidate_recall']:.3f} | {row['true_higher_order_candidate_recall']:.3f} | {row['true_higher_order_recovery']:.3f} | {row['false_candidate_proposal_count']} | {row['cross_fold_false_positive_highest_order_gene_set_count']} | {row['runtime_seconds']:.2f} |")
    lines += ['', '## Interpretation limits', '',
        '- With 300 sampled triplets in a 100-gene pool, each exact triplet has 300 / C(100,3) = 0.1855% exploration inclusion probability per fold. Missing a planted module is expected; search failure cannot estimate statistical power.',
        '- The separate three-gene positive control has complete exploration coverage. It demonstrates the statistical path and does not demonstrate high recall in the 100-gene benchmark.',
        '- Off-target proposals are not false biological discoveries. The report separately counts wrong highest-order sets surviving locked validation.',
        '- The pairwise-only triplet is a negative higher-order control; failure to call it is desired. Lower-order pairs in that module are real planted dependencies.',
        '- Four-way results without four-way Gain remain exploratory. A recovered parity module in this synthetic construction does not promote real NT candidates to causal interactions.',
        '- Per-target failure_stage distinguishes search, estimation, statistical, resource and stability failure. Configurations are frozen before each case; no seed or threshold is selected for successful recovery.',
        '- RSS is the cumulative process high-water mark, not an isolated per-case memory measurement. Timing and artifact sizes are measured for each case.', '']
    (root/'SEARCH_RECOVERY_REPORT.md').write_text('\n'.join(lines))
    return {'cases': summaries, 'targets': targets, 'report': str(root/'SEARCH_RECOVERY_REPORT.md')}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Frozen synthetic v0.3 search-recovery benchmark')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--n-cells', type=int, default=12000)
    parser.add_argument('--universe-size', type=int, default=100)
    parser.add_argument('--without-four-way', action='store_true')
    args = parser.parse_args(argv)
    result = run_search_recovery(args.output_dir, n_cells=args.n_cells,
        universe_size=args.universe_size, include_four_way=not args.without_four_way)
    print(result['report'])


if __name__ == '__main__':
    main()
