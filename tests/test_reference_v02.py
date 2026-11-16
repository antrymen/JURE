from dataclasses import replace
from itertools import product
import json
import numpy as np
import pandas as pd
import pytest

from clue_discovery import DiscoveryConfig
from clue_discovery.v02 import (Population, ReferenceConfig, FrozenCatalogue, fit_reference,
                                split_reference, reference_guided, run_discovery, test_perturbations)
from clue_discovery.v02.statistics import mfi_from_counts


def population(prefix, order=3, kind='parity', extra_independent=False):
    states = np.array(list(product((0, 1), repeat=order)), dtype=np.uint8)
    signs = (-1) ** states[:, :order-1 if extra_independent else order].sum(axis=1).astype(int)
    if kind == 'uniform':
        counts = np.full(len(states), 250)
    elif kind == 'reversed':
        counts = np.where(signs == 1, 100, 400)
    else:
        counts = np.where(signs == 1, 400, 100)
    matrix = np.repeat(states, counts, axis=0)
    genes = tuple(chr(65+i) for i in range(order))
    return Population(matrix, genes, tuple(f'{prefix}:{i}' for i in range(len(matrix))))


def config(**kwargs):
    return ReferenceConfig(n_bootstrap=80, max_order=3, **kwargs)


def fitted(validation_kind='parity', test_kind='parity'):
    d, v, t = population('d'), population('v', kind=validation_kind), population('t', kind=test_kind)
    return fit_reference(d, v, t, candidate_genes=d.gene_names, config=config()), t


def test_reference_discovery_and_locked_validation():
    result, _ = fitted()
    assert len(result.catalogue.patterns) == 4
    assert all(p.order == 3 for p in result.catalogue.patterns)
    assert result.order_summary.set_index('order').loc[3, 'replicated_in_reference_validation'] == 4
    assert set(result.validation.reference_id) == set(result.candidates.query('stable_in_discovery').reference_id)
    assert result.validation.replicated_in_reference_validation.all()
    assert set(result.search_log.query('order == 2').expansion_reason) == {'support_only'}
    assert not result.metadata['reference_test_values_accessed']


def test_shift_detected_without_any_perturbation_mfi_gate():
    result, test = fitted()
    # Uniform perturbation has exactly zero three-way MFI, yet a real prevalence shift.
    pert = population('p', kind='uniform')
    assert mfi_from_counts([250]*8) == 0
    shifts = test_perturbations(result.catalogue, test, {'KO': pert})
    assert set(shifts.shifts.status) == {'candidate_shift'}
    assert np.allclose(shifts.shifts.delta_frequency, -.075)
    assert set(shifts.shifts.replication_status) == {'not_available'}
    assert not shifts.metadata['perturbation_mfi_required']
    assert set(shifts.call_matrix.loc['KO']) == {'down'}


@pytest.mark.parametrize('kind', ['uniform', 'reversed'])
def test_nonreplicating_reference_patterns_excluded(kind):
    result, _ = fitted(validation_kind=kind)
    assert result.candidates.stable_in_discovery.sum() == 4
    assert not result.validation.replicated_in_reference_validation.any()
    assert not result.catalogue.patterns


def test_reference_blindspot_and_legacy_emergent_mode():
    d, v, t = [population(prefix, kind='uniform') for prefix in ['d', 'v', 't']]
    ref = fit_reference(d, v, t, candidate_genes=d.gene_names, config=config())
    p = population('p')
    assert not ref.catalogue.patterns
    assert test_perturbations(ref.catalogue, t, {'KO': p}).shifts.empty
    result = run_discovery(mode='perturbation_emergent', X_control=t.matrix, X_perturb=p.matrix,
                           gene_names=list(p.gene_names), config=DiscoveryConfig(n_bootstrap=80))
    assert len(result.clues.query("order == 3 and status == 'candidate_clue'")) > 0
    assert result.metadata['baseline_version'] == '0.1.0'


def test_sparse_joint_tables_stop_expansion_even_with_large_pattern_support():
    x = np.repeat([[0, 0, 0, 0], [1, 1, 1, 1]], 1000, axis=0)
    populations = [Population(x, tuple('ABCD'), tuple(f'{p}{i}' for i in range(len(x)))) for p in ['d', 'v', 't']]
    result = fit_reference(*populations, candidate_genes=tuple('ABCD'), config=ReferenceConfig(n_bootstrap=40))
    assert set(result.candidates.order) == {2}
    assert result.candidates.support.max() == 1000
    assert not result.candidates.table_quality_pass.any()
    assert not result.candidates.bootstrap_performed.any()
    assert not result.search_log.EXPAND.any()
    assert result.metadata['stop_reason'] == 'no_expandable_candidates'
    assert set(result.search_log.expansion_reason) == {'sparse_state_table'}


def test_validation_and_test_values_never_change_discovery():
    base, test = fitted()
    # Even invalid assay values in test must not be accessed by fit_reference.
    poisoned = Population(np.full(test.matrix.shape, -999), test.gene_names, test.cell_ids)
    d, v = population('d'), population('v', kind='uniform')
    other = fit_reference(d, v, poisoned, candidate_genes=d.gene_names, config=config())
    pd.testing.assert_frame_equal(base.candidates, other.candidates)
    pd.testing.assert_frame_equal(base.search_log, other.search_log)
    pd.testing.assert_frame_equal(base.gene_qc, other.gene_qc)
    pd.testing.assert_frame_equal(base.order_summary.drop(columns=['replicated_in_reference_validation', 'replication_rate']),
                                  other.order_summary.drop(columns=['replicated_in_reference_validation', 'replication_rate']))
    same = fit_reference(d, population('v'), poisoned, candidate_genes=d.gene_names, config=config())
    assert same.catalogue.sha256 == base.catalogue.sha256
    with pytest.raises(ValueError, match='counts'):
        test_perturbations(same.catalogue, poisoned, {'KO': population('p')})


@pytest.mark.parametrize('order', [2, 3, 4, 5, 6, 7])
def test_general_mfi_parity_formula(order):
    states = np.array(list(product((0, 1), repeat=order)))
    counts = np.where(states.sum(axis=1) % 2 == 0, 400, 100)
    expected = (-1)**order * 2**(order-1) * np.log(4)
    assert mfi_from_counts(counts, alpha=0) == pytest.approx(expected)


def test_four_way_candidates_come_from_three_way_joins_without_pair_signal():
    pops = [population(s, order=4) for s in ['d', 'v', 't']]
    result = fit_reference(*pops, candidate_genes=tuple('ABCD'), config=ReferenceConfig(max_order=4, n_bootstrap=80))
    assert len(result.catalogue.patterns) == 8
    assert all(p.order == 4 for p in result.catalogue.patterns)
    assert not result.candidates.query('order < 4').stable_in_discovery.any()
    assert all(result.search_log.query('order == 4').generated_from.map(bool))
    assert len(result.candidates.query('order == 4')) == 16
    assert not result.search_log.reference_id.duplicated().any()


def test_keep_and_expand_can_both_be_true():
    pops = [population(s, order=4, extra_independent=True) for s in ['d', 'v', 't']]
    result = fit_reference(*pops, candidate_genes=tuple('ABCD'), config=ReferenceConfig(max_order=4, n_bootstrap=80))
    accepted = result.search_log.query('order == 3 and KEEP_AS_REFERENCE')
    assert len(accepted) > 0 and accepted.EXPAND.all() and not accepted.PRUNE.any()


def test_seventh_order_end_to_end_and_deduplication():
    pops = [population(s, order=7) for s in ['d', 'v', 't']]
    result = fit_reference(*pops, candidate_genes=tuple('ABCDEFG'), config=ReferenceConfig(n_bootstrap=40))
    assert result.order_summary.order.tolist() == [2, 3, 4, 5, 6, 7]
    assert len(result.catalogue.patterns) == 64
    assert all(p.order == 7 for p in result.catalogue.patterns)
    assert len(result.candidates) == 3**7 - 1 - 2*7
    assert result.metadata['stop_reason'] == 'max_order'
    assert result.search_log.query('order > 2').generated_from.map(bool).all()


def test_cell_split_is_reproducible_complete_stratified_and_disjoint():
    nt = population('NT')
    cfg = config()
    strata = np.array(['batch1', 'batch2'] * (len(nt.cell_ids)//2))
    parts = split_reference(nt, cfg, strata)
    again = split_reference(nt, cfg, strata)
    assert [p.cell_ids for p in parts] == [p.cell_ids for p in again]
    flattened = sum([list(p.cell_ids) for p in parts], [])
    assert len(set(flattened)) == len(flattened) == len(nt.cell_ids)
    assert set(flattened) == set(nt.cell_ids)
    assert [len(p.cell_ids) for p in parts] == [1000, 500, 500]


def test_overlap_and_test_cohort_substitution_rejected():
    d, v, t = population('d'), population('v'), population('t')
    with pytest.raises(ValueError, match='overlap'):
        fit_reference(d, d, t, candidate_genes=d.gene_names, config=config())
    ref = fit_reference(d, v, t, candidate_genes=d.gene_names, config=config())
    with pytest.raises(ValueError, match='reserved'):
        test_perturbations(ref.catalogue, v, {'KO': population('p')})
    with pytest.raises(ValueError, match='overlap'):
        test_perturbations(ref.catalogue, t, {'KO': d})
    with pytest.raises(ValueError, match='overlap'):
        test_perturbations(ref.catalogue, t, {'KO1': population('p'), 'KO2': population('p')})


def test_serialized_catalogue_locked_and_all_outputs_exist(tmp_path):
    ref, test = fitted()
    ref.write(tmp_path)
    loaded = FrozenCatalogue.load(tmp_path/'frozen_reference_catalogue.json')
    assert loaded == ref.catalogue
    result = test_perturbations(loaded, test, {'KO': population('p', kind='uniform')})
    result.write(tmp_path)
    for name in ['reference_candidates', 'reference_search_log', 'reference_validation',
                 'frozen_reference_catalogue', 'perturbation_state_shifts', 'order_summary']:
        assert (tmp_path/(name + '.csv')).is_file()
    saved = json.loads((tmp_path/'frozen_reference_catalogue.json').read_text())
    saved['payload']['records'][0]['states'][0] ^= 1
    (tmp_path/'tampered.json').write_text(json.dumps(saved))
    with pytest.raises(ValueError, match='checksum'):
        FrozenCatalogue.load(tmp_path/'tampered.json')


def test_all_locked_tests_included_in_declared_fdr_family():
    from clue_discovery.statistics import benjamini_hochberg
    ref, test = fitted()
    result = test_perturbations(ref.catalogue, test, {'same': population('p'), 'shift': population('q', kind='uniform')})
    assert len(result.shifts) == 8
    assert np.allclose(result.shifts.q_value_shift, benjamini_hochberg(result.shifts.p_value_shift))
    assert set(result.shifts.query("perturbation == 'same'").status) == {'screened_out'}


def test_budget_exhaustion_is_explicit_and_empty_catalogue_has_schema(tmp_path):
    d, v, t = [population(s) for s in ['d', 'v', 't']]
    with pytest.raises(ValueError, match='budget'):
        fit_reference(d, v, t, candidate_genes=d.gene_names, config=config(max_candidates=13))
    ref = fit_reference(d, population('v', kind='uniform'), t, candidate_genes=d.gene_names, config=config())
    result = test_perturbations(ref.catalogue, t, {'KO': population('p')})
    result.write(tmp_path)
    assert pd.read_csv(tmp_path/'perturbation_state_shifts.csv').empty
    assert result.delta_matrix.shape == (1, 0)
    assert len(ref.order_summary) == 2


def test_high_level_mode_and_invalid_inputs():
    nt = population('NT')
    result = run_discovery(mode='reference_guided', nt=nt, perturbations={'KO': population('p', kind='uniform')},
                           candidate_genes=nt.gene_names, config=config())
    assert len(result.reference.catalogue.patterns) > 0
    assert set(result.testing.shifts.status) == {'candidate_shift'}
    for changes in [dict(max_order=8), dict(min_occupancy=0), dict(split_fractions=(.5, .5, 0)), dict(max_tests=0)]:
        with pytest.raises(ValueError):
            ReferenceConfig(**changes)
    with pytest.raises(ValueError, match='order'):
        Population(pd.DataFrame([[1, 0]], columns=['B', 'A']), ('A', 'B'), ('cell',))
    with pytest.raises(TypeError, match='DiscoveryConfig'):
        run_discovery(mode='perturbation_emergent', config=ReferenceConfig())
