"""Evaluate only frozen opposite-fold gene sets and exact states."""
from collections import defaultdict

import numpy as np

from .artifacts import write_csv, write_json, enforce_memory_budget
from .bootstrap import bootstrap_gene_set
from .evaluation import (evaluate_counts, eligible_pattern, gain_enabled, joint_counts,
                         mfi_bootstrap_pass, stage_seed)
from .gain import conditional_gain_test


def validate_locked(population, locked, config, store, testing_audit, *, source_fold, validation_fold):
    role = f'{validation_fold}_validation_from_{source_fold}'
    direction = f'{source_fold}_to_{validation_fold}'
    if config.cross_fold_validation == 'off':
        write_csv(store.root/f'locked_validation_{direction}.csv', [],
                  ['reference_id', 'candidate_id', 'genes', 'states', 'order', 'cross_fold_replicated'])
        return [], []
    groups = defaultdict(list)
    for record in locked:
        groups[record['candidate_id']].append(record)
    genes = sorted({g for record in locked for g in record['genes']})
    rows, sets = [], []
    if genes:
        # No detection filter, graph or HVG choice is applied in this direction.
        encoded, _ = population.encode(genes, config)
        matrix = encoded.to_numpy(dtype=np.uint8)
        columns = {gene: i for i, gene in enumerate(genes)}
    for cid, patterns in sorted(groups.items()):
        enforce_memory_budget(config)
        locked_genes = tuple(patterns[0]['genes'])
        counts = joint_counts(matrix, columns, locked_genes)
        point = evaluate_counts(counts, locked_genes, config)
        assessment, gain = point['assessment'], point['gain']
        compute_gain = gain_enabled(config, len(locked_genes))
        state_path = store.save_counts(role, cid, counts, assessment)
        record = dict(candidate_id=cid, genes=locked_genes, order=len(locked_genes), evaluation_role=role,
            total_cells=int(sum(counts)), mfi=point['mfi'], set_level_gain=gain['set_level_gain'] if gain else None,
            state_table_path=state_path, estimability_status=assessment['status'],
            min_state_count=assessment['min_state_count'], zero_state_count=assessment['zero_state_count'],
            state_table_occupancy=assessment['state_table_occupancy'], p_gain=None, p_mfi=None,
            higher_order_gain_status='evaluated' if gain else 'not_evaluated',
            bootstrap_status='not_evaluated', gain_ok=not compute_gain, bootstrap_ok=False,
            calibration_training_performed=False, candidate_search_performed=False)
        allowed = config.estimability_filter == 'off' or assessment['status'] != 'poor'
        if gain is not None:
            write_json(store.root/f'gain/{role}/{cid}.json', gain)
            record['gain_path'] = f'gain/{role}/{cid}.json'
        if compute_gain and allowed:
            calibration = conditional_gain_test(counts, alpha=config.smoothing_alpha)
            record['gain_null_path'] = store.save_arrays('gain', role, cid+'_conditional', calibration)
            write_json(store.root/f'gain/{role}/{cid}_conditional.json',
                       {k: v for k, v in calibration.items() if not isinstance(v, np.ndarray)})
            record.update(p_gain=calibration['p_gain'], gain_ok=calibration['p_gain'] <= config.alpha_gain,
                gain_method=calibration['method'], conditional_fiber_size=calibration['support_size'])
            record['p_mfi'] = float(np.clip(calibration['null_weights'][np.abs(calibration['null_mfi']) >= abs(record['mfi'])-1e-12].sum(), 0., 1.))
            del calibration
        boot = None
        # All estimable locked sets get the same predeclared uncertainty assessment,
        # including those that fail validation Gain; no validation-side shortlist search.
        if allowed and config.bootstrap == 'on':
            boot = bootstrap_gene_set(counts, n_bootstrap=config.n_bootstrap, alpha=config.smoothing_alpha,
                seed=stage_seed(config, role, locked_genes, 'bootstrap'), ci_level=config.ci_level,
                compute_gain=compute_gain)
            record['bootstrap_path'] = store.save_arrays('bootstrap', role, cid, boot['arrays'])
            write_json(store.root/f'bootstrap/{role}/{cid}_summary.json', {k: v for k, v in boot.items() if k != 'arrays'})
            record.update(bootstrap_status=boot['status'],
                bootstrap_ok=boot['status'] == 'complete' and mfi_bootstrap_pass(boot['summary']['mfi'], config),
                mfi_ci_low=boot['summary']['mfi']['ci_low'], mfi_ci_high=boot['summary']['mfi']['ci_high'],
                mfi_sign_stability=boot['summary']['mfi']['sign_stability'])
        elif config.bootstrap == 'off':
            record.update(bootstrap_status='disabled_ablation', bootstrap_ok=True)
        sets.append(record)
        for frozen in patterns:
            observed = point['patterns'][frozen['state_index']]
            if observed['reference_id'] != frozen['reference_id']:
                raise ValueError('locked candidate states or canonical gene order changed')
            pattern_ci = (boot['summary']['pattern_absolute_gain'][frozen['state_index']]
                          if boot is not None and compute_gain and boot['status'] == 'complete' else None)
            sign_ok = np.sign(record['mfi']) == np.sign(frozen['mfi']) and record['mfi'] != 0
            pattern_ok = eligible_pattern(observed, config, compute_gain=compute_gain) and (
                not compute_gain or config.bootstrap == 'off' or (pattern_ci is not None and pattern_ci['ci_low'] > 0
                    and pattern_ci['sign_stability'] >= config.min_sign_stability))
            passed = allowed and abs(record['mfi']) >= config.min_abs_mfi and record['gain_ok'] and record['bootstrap_ok'] and sign_ok and pattern_ok
            reasons = []
            for ok, name in ((allowed, 'poor_estimability'), (abs(record['mfi']) >= config.min_abs_mfi, 'mfi_prefilter_failed'),
                             (record['gain_ok'], 'gain_not_rejected'), (record['bootstrap_ok'], 'bootstrap_failed'),
                             (sign_ok, 'mfi_direction_changed'), (pattern_ok, 'locked_pattern_not_supported_or_stable')):
                if not ok:
                    reasons.append(name)
            rows.append(dict(observed, **{k: v for k, v in record.items() if k not in observed},
                discovery_fold=source_fold, validation_fold=validation_fold,
                discovery_mfi=frozen['mfi'], discovery_frequency=frozen['frequency'],
                evaluation_passed_under_config=bool(passed),
                cross_fold_replicated=bool(passed and frozen['within_discovery_stable']
                                          and config.bootstrap == 'on'),
                validation_reason=('passed' if config.bootstrap == 'on' else 'ablation_bootstrap_disabled') if passed else ';'.join(reasons),
                pattern_gain_bootstrap=pattern_ci, proposal_sources=frozen['proposal_sources'],
                locked_genes_and_states_unchanged=True))
        if boot is not None:
            del boot
    for order in range(2, config.max_order+1):
        g = [r for r in sets if r['order'] == order]
        p = [r for r in rows if r['order'] == order]
        testing_audit.adjust(role, order, 'gain', g, 'p_gain')
        testing_audit.adjust(role, order, 'mfi', g, 'p_mfi')
        testing_audit.adjust(role, order, 'state', p, 'p_state', id_key='reference_id')
        by_id = {r['candidate_id']: r for r in g}
        for r in p:
            r.update(q_gain=by_id[r['candidate_id']]['q_gain'], q_mfi=by_id[r['candidate_id']]['q_mfi'])
    write_csv(store.root/f'locked_validation_{direction}.csv', rows,
              ['reference_id', 'candidate_id', 'genes', 'states', 'order', 'cross_fold_replicated'])
    write_csv(store.root/f'search_logs/{role}_gene_sets.csv', sets,
              ['candidate_id', 'genes', 'order', 'estimability_status', 'p_gain', 'bootstrap_status'])
    return rows, sets
