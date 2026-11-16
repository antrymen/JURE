"""Recovery diagnostics must distinguish proposal coverage from statistical power."""
from dataclasses import replace
import itertools
import json

import numpy as np
import pandas as pd
import pytest

from clue_discovery.v03.config import ScalableConfig
from clue_discovery.v03.recovery import (generate_search_recovery_populations,
    run_search_recovery, _distribution, _target_diagnostics)
import clue_discovery.v03.recovery as recovery


def test_planted_distributions_have_prespecified_highest_order_truth():
    states, probabilities = _distribution('pairwise_only')
    signs = (-1.)**states.sum(axis=1)
    assert abs(np.log(probabilities) @ signs) < 1e-12
    # This control still contains real pairwise structure.
    expected_ab = sum(probabilities[(states[:, 0] == 1) & (states[:, 1] == 1)])
    assert expected_ab > .3
    for kind, order in [('pure_three_way', 3), ('pure_four_way', 4)]:
        states, probabilities = _distribution(kind)
        assert abs(np.log(probabilities) @ ((-1.)**states.sum(axis=1))) > 1
        for subset in itertools.combinations(range(order), order-1):
            observed = np.zeros(2**len(subset))
            for state, weight in zip(states, probabilities):
                code = sum(int(state[index])*2**(len(subset)-position-1) for position, index in enumerate(subset))
                observed[code] += weight
            assert np.allclose(observed, 1/len(observed))


def test_generation_is_independent_reproducible_and_does_not_select_seed():
    first, truth, metadata = generate_search_recovery_populations(n_cells=1200, random_seed=9)
    repeat, repeat_truth, repeat_metadata = generate_search_recovery_populations(n_cells=1200, random_seed=9)
    assert truth == repeat_truth
    assert metadata['dataset_hashes'] == repeat_metadata['dataset_hashes']
    assert not set(first['A'].cell_ids) & set(first['B'].cell_ids)
    assert not np.array_equal(first['A'].matrix, first['B'].matrix)
    assert np.array_equal(first['A'].matrix, repeat['A'].matrix)
    assert first['A'].matrix.shape == (600, 100)
    assert metadata['truth_used_for_proposal'] is False
    assert metadata['seed_selected_for_recovery'] is False
    assert sum(target['genuine_highest_order'] for target in truth) == 2
    assert len(first['A'].gene_names) == 100


def test_smoke_uses_production_discovery_and_frozen_validation_without_truth(tmp_path, monkeypatch):
    config = ScalableConfig(hvg_pool_size=20, max_order=3, max_pair_candidates=24,
        max_triplet_candidates=24, max_quad_candidates=4, max_bootstrap_gene_sets=8,
        max_gain_calibration_gene_sets=8, max_exploration_candidates_per_order=8,
        max_exploration_candidates=24, n_null_simulations=39, n_bootstrap=30)
    actual_discover, actual_validate = recovery.discover, recovery.validate_locked
    events = []
    def discovery_spy(population, configuration, store, testing_audit, **kwargs):
        assert set(kwargs) == {'fold'}
        assert len(population.gene_names) == configuration.hvg_pool_size
        events.append(('discovery', store.root.name, kwargs['fold']))
        return actual_discover(population, configuration, store, testing_audit, **kwargs)
    def validation_spy(population, locked, configuration, store, testing_audit, **kwargs):
        assert (store.root/'both_discoveries_frozen.json').exists()
        assert [kind for kind, case, _ in events if case == store.root.name][:2] == ['discovery', 'discovery']
        events.append(('validation', store.root.name, kwargs['source_fold']))
        return actual_validate(population, locked, configuration, store, testing_audit, **kwargs)
    monkeypatch.setattr(recovery, 'discover', discovery_spy)
    monkeypatch.setattr(recovery, 'validate_locked', validation_spy)
    result = run_search_recovery(tmp_path/'smoke', config, n_cells=1600,
        universe_size=20, include_four_way=False)
    assert len(result['cases']) == 4
    tiny = next(case for case in result['cases'] if case['gene_universe_size'] == 3)
    assert tiny['true_higher_order_candidate_recall'] == 1
    assert tiny['true_higher_order_recovery'] == 1
    assert tiny['n_bootstrap'] == 30 and tiny['n_null_simulations'] == 39
    assert tiny['exploration_target_inclusion_probability_per_fold'] == {'A': 1., 'B': 1.}
    large = [case for case in result['cases'] if case['gene_universe_size'] == 20]
    assert {case['candidate_mode'] for case in large} == {'dependency_only', 'exploration_only', 'hybrid'}
    assert all(case['no_parameter_retuning'] for case in result['cases'])
    for case in result['cases']:
        folder = tmp_path/'smoke'/case['case']
        assert (folder/'config_frozen.yaml').exists()
        manifest = json.loads((folder/'multiple_testing_manifest.json').read_text())
        assert manifest['global_search_fdr_controlled'] is False
        assert all(family['n_members'] == len(family['unique_member_ids']) for family in manifest['families'])
    target_table = pd.read_csv(tmp_path/'smoke'/'search_recovery_targets.csv')
    assert {'failure_stage', 'candidate_proposed', 'candidate_evaluated', 'cross_fold_replicated'} <= set(target_table)
    with pytest.raises(FileExistsError):
        run_search_recovery(tmp_path/'smoke', config, n_cells=1600, universe_size=20)


def test_diagnostics_distinguish_search_estimation_statistics_and_stability():
    from types import SimpleNamespace
    truth = [{'candidate_id': 'target', 'genes': ('A', 'B', 'C'), 'order': 3,
              'module': 'pure_three_way', 'genuine_highest_order': True}]
    base = dict(fold='A', hvg_genes=('A', 'B', 'C'), proposals=[], records=[], locked=[])
    result = SimpleNamespace(**base)
    assert _target_diagnostics(result, [], truth, mode='hybrid')[0]['failure_stage'] == 'search_failure'
    result.proposals = [{'candidate_id': 'target'}]
    result.records = [{'candidate_id': 'target', 'state_table_computed': True, 'estimability_status': 'poor'}]
    assert _target_diagnostics(result, [], truth, mode='hybrid')[0]['failure_stage'] == 'estimation_failure'
    result.records[0].update(estimability_status='good', mfi_ok=True, gain_ok=False)
    assert _target_diagnostics(result, [], truth, mode='hybrid')[0]['failure_stage'] == 'statistical_failure'
    result.records[0].update(gain_ok=True)
    assert _target_diagnostics(result, [], truth, mode='hybrid')[0]['failure_stage'] == 'stability_failure'
    result.locked = [{'candidate_id': 'target'}]
    validation = [{'candidate_id': 'target', 'cross_fold_replicated': True}]
    assert _target_diagnostics(result, validation, truth, mode='hybrid')[0]['failure_stage'] == 'recovered'
