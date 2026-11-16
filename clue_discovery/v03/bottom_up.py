"""Bounded incremental discovery; no validation population enters this module."""
from dataclasses import dataclass
import time

import numpy as np

from .artifacts import write_csv, write_json, digest, enforce_memory_budget
from .bootstrap import bootstrap_gene_set
from .dependency import DependencyGraphBuilder
from .evaluation import (evaluate_counts, eligible_pattern, gain_enabled, joint_counts,
                         mfi_bootstrap_pass, stage_seed)
from .gain import GainNullCalibration
from .hvg import select_hvgs
from .proposal import CandidateProposalEngine
from .search_log import decide_expansion


@dataclass
class DiscoveryResult:
    fold: str
    hvg_genes: tuple
    hvg_metadata: dict
    graph_summary: dict
    proposals: list
    records: list
    locked: list
    order_summaries: list
    status: str
    runtime_seconds: float


def make_proposal_engine(selection, graph, config, fold):
    return CandidateProposalEngine(selection.genes, graph, candidate_mode=config.candidate_mode,
        random_seed=stage_seed(config, fold, (), 'proposal'), exploration_fraction=config.exploration_fraction,
        max_exploration_candidates_per_order=min(config.max_exploration_candidates_per_order,
            config.max_exploration_candidates//(config.max_order-1)),
        max_pair_candidates=config.max_pair_candidates, max_triplet_candidates=config.max_triplet_candidates,
        max_quad_candidates=config.max_quad_candidates, fold=fold)


def _bootstrap_quota(config, order):
    if config.max_order == 2:
        return config.max_bootstrap_gene_sets
    pair = config.max_bootstrap_gene_sets//5
    triple = config.max_bootstrap_gene_sets-pair if config.max_order == 3 else config.max_bootstrap_gene_sets*3//5
    return {2: pair, 3: triple, 4: config.max_bootstrap_gene_sets-pair-triple}[order]


def discover(population, config, store, testing_audit, *, fold, selection=None, dry_run=False):
    started = time.monotonic()
    role = f'{fold}_discovery'
    selection = selection or select_hvgs(population.matrix, population.gene_names,
        n_top=config.hvg_pool_size, fold=fold, min_detection_rate=config.min_detection_rate,
        max_detection_rate=config.max_detection_rate)
    if selection.metadata['fold'] != fold or len(selection.genes) != config.hvg_pool_size:
        raise ValueError('HVG selection must belong to the current discovery fold and configured pool')
    write_csv(store.root/f'hvg_selection_{fold}.csv', selection.table)
    write_csv(store.root/f'selected_hvgs_{fold}.csv', selection.table.loc[selection.table.selected])
    encoded, encoding_qc = population.encode(selection.genes, config)
    write_csv(store.root/f'binary_encoding_qc_{fold}.csv', encoding_qc)
    binary = encoded.to_numpy(dtype=np.uint8)
    columns = {gene: i for i, gene in enumerate(encoded.columns)}
    graph = DependencyGraphBuilder(top_k=config.dependency_top_k,
        min_abs_phi=config.dependency_min_abs_phi, block_size=config.dependency_block_size,
        threshold_source=config.threshold_source, version=config.run_version).build(
            binary, selection.genes, fold=fold, audit_path=store.root/f'dependency_graph_{fold}.csv')
    write_json(store.root/f'dependency_graph_summary_{fold}.json', graph.summary)
    enforce_memory_budget(config)
    engine = make_proposal_engine(selection, graph, config, fold)
    proposals, records, locked, orders = [], [], [], []
    parents, calibration_count = [], 0
    exhausted = False
    for order in range(2, config.max_order+1):
        enforce_memory_budget(config)
        batch = engine.propose(order, parents=parents)
        exhausted |= batch.audit['budget_exhausted']
        proposals.extend(candidate.to_record() for candidate in batch.candidates)
        proposal_by_id = {c.candidate_id: c for c in batch.candidates}
        level, state_rows, shortlist = [], [], []
        for candidate_index, candidate in enumerate(batch.candidates):
            if candidate_index % 64 == 0:
                enforce_memory_budget(config)
            cid, genes = candidate.candidate_id, candidate.genes
            row = dict(candidate.to_record(), state_table_computed=False, estimability_status='not_evaluated',
                mfi_status='not_evaluated', gain_status='not_evaluated', bootstrap_status='not_evaluated',
                keep=False, expand=False, prune=False, prune_reason=None, validation_status='not_yet_locked',
                within_discovery_stable=False, p_gain=None, p_mfi=None, higher_order_gain_status='not_evaluated')
            if dry_run:
                row.update(expand=order < config.max_order, lifecycle_status='dry_run_not_statistically_evaluated')
                level.append(row)
                continue
            counts = joint_counts(binary, columns, genes)
            point = evaluate_counts(counts, genes, config)
            assessment, gain = point['assessment'], point['gain']
            path = store.save_counts(role, cid, counts, assessment)
            row.update(state_table_computed=True, state_table_path=path,
                estimability_status=assessment['status'], min_state_count=assessment['min_state_count'],
                zero_state_count=assessment['zero_state_count'], state_table_occupancy=assessment['state_table_occupancy'],
                mfi=point['mfi'], mfi_status='evaluated', mfi_ok=abs(point['mfi']) >= config.min_abs_mfi,
                total_cells=int(sum(counts)), gain_status='evaluated' if gain is not None else 'not_evaluated',
                higher_order_gain_status='evaluated' if gain is not None else 'not_evaluated',
                set_level_gain=gain['set_level_gain'] if gain is not None else None,
                gain_ok=order == 2 or gain is None,
                gain_calibration_unstable=False, bootstrap_ok=False)
            row['has_supported_state'] = bool(max(counts) >= config.min_support)
            for pattern in point['patterns']:
                state_rows.append(dict(pattern, candidate_id=cid, evaluation_role=role))
            if gain is not None:
                write_json(store.root/f'gain/{role}/{cid}.json', gain)
                row['gain_path'] = f'gain/{role}/{cid}.json'
            allowed = config.estimability_filter == 'off' or assessment['status'] != 'poor'
            eligible = [p for p in point['patterns'] if eligible_pattern(p, config, compute_gain=gain is not None)]
            if not allowed:
                row.update(prune=True, prune_reason='poor_estimability', gain_ok=False)
            elif not row['mfi_ok']:
                row.update(prune=True, prune_reason='mfi_prefilter_failed')
            elif not eligible:
                row.update(prune=True, prune_reason='no_supported_positive_gain_state')
            elif order >= 3 and gain is not None:
                if calibration_count >= config.max_gain_calibration_gene_sets:
                    exhausted = True
                    row.update(prune=True, prune_reason='gain_calibration_budget_exhausted', gain_ok=False,
                               gain_status='budget_exhausted')
                else:
                    calibration_count += 1
                    calibration = GainNullCalibration(config.n_null_simulations, config.smoothing_alpha,
                        stage_seed(config, role, genes, 'gain_null')).calibrate(counts)
                    row['gain_null_path'] = store.save_arrays('gain', role, cid+'_null', calibration)
                    write_json(store.root/f'gain/{role}/{cid}_calibration.json',
                               {k: v for k, v in calibration.items() if not isinstance(v, np.ndarray)})
                    p = calibration['p_gain']
                    se = calibration['mc_standard_error']
                    row.update(p_gain=p, p_gain_resolution=calibration['p_resolution'],
                        gain_status=calibration['status'],
                        gain_ok=p is not None and p <= config.alpha_gain,
                        gain_calibration_unstable=(p is None or p-1.96*se <= config.alpha_gain <= p+1.96*se))
                    if calibration['fit_failures'] == 0:
                        row['p_mfi'] = float((1 + np.count_nonzero(np.abs(calibration['null_mfi']) >= abs(row['mfi']))) /
                                              (len(calibration['null_mfi'])+1))
                    if not row['gain_ok']:
                        row.update(prune=True, prune_reason='gain_null_not_rejected')
                    del calibration
            if allowed and row['mfi_ok'] and eligible and row['gain_ok']:
                shortlist.append((row, eligible))
            level.append(row)
        # Every evaluated gene set/state belongs to one recorded family, independent of neighborhood.
        testing_audit.adjust(role, order, 'gain', level, 'p_gain')
        testing_audit.adjust(role, order, 'mfi', level, 'p_mfi')
        testing_audit.adjust(role, order, 'state', state_rows, 'p_state', id_key='reference_id')
        state_lookup = {p['reference_id']: p for p in state_rows}
        completed_bootstraps = 0
        # Stable canonical candidate order is fixed before seeing effect scores.
        for row, eligible in shortlist:
            compute_gain = gain_enabled(config, order)
            if config.bootstrap == 'on' and completed_bootstraps >= _bootstrap_quota(config, order):
                row.update(prune=True, prune_reason='bootstrap_budget_exhausted', bootstrap_status='budget_exhausted')
                exhausted = True
                continue
            if config.bootstrap == 'off':
                row.update(bootstrap_status='disabled_ablation', bootstrap_ok=True)
                boot = None
            else:
                counts = store.counts(row['state_table_path'])
                boot = bootstrap_gene_set(counts, n_bootstrap=config.n_bootstrap, alpha=config.smoothing_alpha,
                    seed=stage_seed(config, role, row['genes'], 'bootstrap'), ci_level=config.ci_level,
                    compute_gain=compute_gain)
                completed_bootstraps += 1
                row['bootstrap_path'] = store.save_arrays('bootstrap', role, row['candidate_id'], boot['arrays'])
                write_json(store.root/f'bootstrap/{role}/{row["candidate_id"]}_summary.json',
                           {k: v for k, v in boot.items() if k != 'arrays'})
                row.update(bootstrap_status=boot['status'],
                    bootstrap_ok=boot['status'] == 'complete' and mfi_bootstrap_pass(boot['summary']['mfi'], config),
                    mfi_ci_low=boot['summary']['mfi']['ci_low'], mfi_ci_high=boot['summary']['mfi']['ci_high'],
                    mfi_sign_stability=boot['summary']['mfi']['sign_stability'])
            if row['bootstrap_ok']:
                for pattern in eligible:
                    pattern = dict(state_lookup[pattern['reference_id']])
                    state_summary = (boot['summary']['pattern_absolute_gain'][pattern['state_index']]
                                     if boot is not None and compute_gain and boot['status'] == 'complete' else None)
                    pattern_ok = (state_summary is None or (state_summary['ci_low'] > 0 and
                                  state_summary['sign_stability'] >= config.min_sign_stability))
                    if not pattern_ok:
                        continue
                    locked.append(dict(pattern, candidate_id=row['candidate_id'], discovery_fold=fold,
                        mfi=row['mfi'], set_level_gain=row['set_level_gain'], p_gain=row['p_gain'], q_gain=row['q_gain'],
                        estimability_status=row['estimability_status'], min_state_count=row['min_state_count'],
                        gain_calibration_unstable=row['gain_calibration_unstable'],
                        higher_order_gain_status=row['higher_order_gain_status'],
                        bootstrap_status=row['bootstrap_status'], mfi_sign_stability=row.get('mfi_sign_stability'),
                        mfi_ci_low=row.get('mfi_ci_low'), mfi_ci_high=row.get('mfi_ci_high'),
                        pattern_gain_bootstrap=state_summary, proposal_sources=row['proposal_sources'],
                        provenance=row['provenance'], generation_parent_ids=row['generation_parent_ids'],
                        state_table_path=row['state_table_path'], bootstrap_path=row.get('bootstrap_path'),
                        within_discovery_stable=config.bootstrap == 'on'))
                    row['keep'] = True
                row['within_discovery_stable'] = row['keep'] and config.bootstrap == 'on'
            if not row['keep']:
                row.update(prune=True, prune_reason='bootstrap_or_pattern_stability_failed')
            if boot is not None:
                del boot
        parents = []
        for row in level:
            if dry_run:
                parents.append(proposal_by_id[row['candidate_id']])
                continue
            supported = row['has_supported_state']
            decision = decide_expansion(row['candidate_id'], order=order, max_order=config.max_order,
                keep=row['keep'], estimability_status=('good' if config.estimability_filter == 'off' else row['estimability_status']), gain_ok=row['gain_ok'],
                bootstrap_ok=row['bootstrap_ok'], proposal_support=True, has_supported_state=supported)
            row.update(expand=decision.expand, expansion_reason=decision.reason,
                       prune=not (row['keep'] or decision.expand), lifecycle_status='evaluated')
            if decision.expand:
                parents.append(proposal_by_id[row['candidate_id']])
        stats = dict(batch.audit, evaluated=0 if dry_run else len(level),
            estimability_pruned=sum(r.get('prune_reason') == 'poor_estimability' for r in level),
            gain_pruned=sum(r.get('prune_reason') == 'gain_null_not_rejected' for r in level),
            bootstrap_gene_sets=completed_bootstraps, bootstrap_shortlist=len(shortlist),
            bootstrap_quota=_bootstrap_quota(config, order),
            bootstrap_budget_pruned=sum(r.get('bootstrap_status') == 'budget_exhausted' for r in level),
            gain_calibration_budget_pruned=sum(r.get('gain_status') == 'budget_exhausted' for r in level),
            kept_gene_sets=sum(r['keep'] for r in level), expandable_gene_sets=len(parents),
            dry_run=dry_run, quad_dry_run_scope='unqualified_L3_parents_upper_bound' if dry_run else None)
        orders.append(stats)
        records.extend(level)
        for rejected in batch.budget_pruned_candidates:
            records.append(dict(rejected.to_record(), state_table_computed=False, keep=False, expand=False,
                prune=True, prune_reason='proposal_budget_exhausted', lifecycle_status='not_evaluated',
                estimability_status='not_evaluated', gain_status='not_evaluated', bootstrap_status='not_evaluated'))
        write_csv(store.root/f'search_logs/{role}_order{order}.csv', level, ['candidate_id', 'genes', 'order'])
        write_csv(store.root/f'search_logs/{role}_states_order{order}.csv', state_rows,
                  ['reference_id', 'candidate_id', 'genes', 'states', 'order', 'p_state', 'q_state'])
        write_json(store.root/f'search_logs/{role}_order{order}_audit.json', stats)
    write_csv(store.root/f'candidate_proposals_{fold}.csv', proposals, ['candidate_id', 'genes', 'order', 'proposal_sources'])
    write_csv(store.root/f'candidate_search_log_{fold}.csv', records, ['candidate_id', 'genes', 'order', 'keep', 'expand', 'prune_reason'])
    write_csv(store.root/f'frozen_candidates_{fold}.csv', locked, ['reference_id', 'candidate_id', 'genes', 'states', 'order'])
    write_json(store.root/f'discovery_{fold}_frozen.json', {'fold': fold, 'locked': locked,
        'locked_sha256': digest(locked), 'hvg_genes': selection.genes, 'graph_summary': graph.summary,
        'no_opposite_population_received': True, 'status': 'budget_exhausted' if exhausted else 'complete'})
    return DiscoveryResult(fold, selection.genes, selection.metadata, graph.summary, proposals, records, locked,
                           orders, 'budget_exhausted' if exhausted else 'complete', time.monotonic()-started)
