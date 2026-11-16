from dataclasses import replace
import hashlib
from itertools import product
import json

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

import clue_discovery.nt_reference as nt
from clue_discovery.bootstrap import summarize_distribution
from clue_discovery.statistics import benjamini_hochberg
from clue_discovery.v02 import Population, ReferenceConfig


def parity(prefix, order=3, mode='parity', dependent_order=None):
    states = np.array(list(product((0, 1), repeat=order)), dtype=np.uint8)
    dependent_order = order if dependent_order is None else dependent_order
    even = states[:, :dependent_order].sum(axis=1) % 2 == 0
    counts = (np.full(len(states), 250) if mode == 'uniform'
              else np.where(even, 100, 400) if mode == 'reversed' else np.where(even, 400, 100))
    matrix = np.repeat(states, counts, axis=0)
    return Population(matrix, tuple('ABCDEFG'[:order]), tuple(f'{prefix}{i}' for i in range(len(matrix))))


def fit(a=None, b=None, **kwargs):
    a, b = parity('a') if a is None else a, parity('b') if b is None else b
    kwargs.setdefault('candidate_genes_a', a.gene_names)
    kwargs.setdefault('candidate_genes_b', b.gene_names)
    kwargs.setdefault('config', ReferenceConfig(max_order=3, n_bootstrap=80, random_seed=20260927))
    return nt.fit_twofold_nt(a, b, **kwargs)


def test_stratified_split_complete_balanced_expression_independent():
    n = 10691
    ids = tuple(f'NT{i}' for i in range(n))
    # Singleton and many odd strata cannot systematically give B all extras.
    strata = np.array(['one'] + ['odd1']*301 + ['odd2']*399 + ['even']*900 + ['large']*9090)
    a = Population(np.ones((n, 1)), ('G',), ids)
    b = Population(np.full((n, 1), -999), ('G',), ids)
    parts = nt.split_nt_twofold(a, random_seed=7, strata=strata)
    again = nt.split_nt_twofold(b, random_seed=7, strata=strata)
    assert [len(p.cell_ids) for p in parts] == [5345, 5346]
    assert [p.cell_ids for p in parts] == [p.cell_ids for p in again]
    assert not set(parts[0].cell_ids) & set(parts[1].cell_ids)
    assert set(parts[0].cell_ids) | set(parts[1].cell_ids) == set(ids)
    mapping = dict(zip(ids, strata))
    for label in set(strata):
        assert abs(sum(mapping[c] == label for c in parts[0].cell_ids)
                   - sum(mapping[c] == label for c in parts[1].cell_ids)) <= 1
    with pytest.raises(ValueError, match='nonmissing'):
        nt.split_nt_twofold(a, random_seed=7, strata=['x'])


def test_fano_matches_sample_variance_baseline_dense_and_sparse():
    matrix = np.array([[0, 0, 1, 0], [0, 1, 1, 1], [2, 0, 1, 0], [4, 3, 1, 1]])
    a = Population(matrix, ('D', 'C', 'B', 'A'), tuple('abcd'))
    genes, qc = nt.select_fano_module(a, module_size=2)
    assert genes == ['D', 'C']
    assert np.allclose(qc.variance, matrix.var(axis=0, ddof=1))
    assert np.allclose(qc.fano, matrix.var(axis=0, ddof=1)/matrix.mean(axis=0))
    assert not qc.set_index('gene').loc['B', 'eligible']
    other, sqc = nt.select_fano_module(replace(a, matrix=sparse.csr_matrix(matrix)), module_size=2)
    assert genes == other
    pd.testing.assert_frame_equal(qc, sqc)
    with pytest.raises(ValueError, match='raw counts'):
        nt.select_fano_module(replace(a, matrix=matrix+.1), module_size=2)


def test_threeway_signal_replicates_and_distinct_seeds_are_reproducible(tmp_path):
    result = fit()
    again = fit()
    pd.testing.assert_frame_equal(result.fold_a_discovery, again.fold_a_discovery)
    pd.testing.assert_frame_equal(result.cross_fold_summary, again.cross_fold_summary)
    cross = result.cross_fold_summary
    assert len(cross) == 4 and set(cross.order) == {3}
    assert cross.within_fold_stable.all()
    assert cross.cross_fold_replicated.all()
    assert cross.bidirectionally_rediscovered.all()
    assert len(set(result.metadata['stage_seeds'].values())) == 4
    assert result.metadata['both_discoveries_frozen_before_validation']
    assert 'split_fractions' not in result.metadata['experiment_config']
    result.write(tmp_path)
    stored = np.load(tmp_path/'mfi_bootstrap_distributions.npz', allow_pickle=False)
    assert set(stored.files) == set(result.bootstrap_distributions)
    for row in result.state_table_estimability.to_dict('records'):
        if row['bootstrap_performed']:
            values = stored[row['bootstrap_key']]
            assert np.array_equal(values, again.bootstrap_distributions[row['bootstrap_key']])
            assert len(values) == 80
            summary = summarize_distribution(values, row['mfi'])
            for metric, value in summary.items():
                assert row['mfi_bootstrap_'+metric] == pytest.approx(value)
            assert row['mfi_lambda'] == pytest.approx(1-summary['sign_stability'])
            assert row['states_below_20'] == sum(v < 20 for v in row['state_counts'])
            assert row['fraction_states_below_20'] == pytest.approx(row['states_below_20']/2**row['order'])


def test_other_fold_mutation_cannot_change_own_discovery_or_module():
    a, b = parity('a'), parity('b')
    module_a, qc_a = nt.select_fano_module(a, module_size=3)
    module_b, qc_b = nt.select_fano_module(b, module_size=3)
    original = fit(a, b, candidate_genes_a=module_a, candidate_genes_b=module_b)
    for changed, own in [('B', 'a'), ('A', 'b')]:
        other = fit(a if changed == 'B' else parity('a', mode='uniform'),
                    b if changed == 'A' else parity('b', mode='uniform'))
        for suffix in ['discovery', 'search_log', 'gene_qc']:
            pd.testing.assert_frame_equal(getattr(original, f'fold_{own}_{suffix}'),
                                          getattr(other, f'fold_{own}_{suffix}'))
        label = own.upper()
        assert original.metadata['discovery_binary_sha256'][label] == other.metadata['discovery_binary_sha256'][label]
        assert original.metadata['locked_candidates_sha256'][label] == other.metadata['locked_candidates_sha256'][label]
    pd.testing.assert_frame_equal(qc_a, nt.select_fano_module(a, module_size=3)[1])
    pd.testing.assert_frame_equal(qc_b, nt.select_fano_module(b, module_size=3)[1])


def test_searches_frozen_on_disk_before_locked_validation_without_reselection(tmp_path, monkeypatch):
    original_search, original_validate = nt.discovery_search, nt._validate
    calls = []
    def search(*args, **kwargs):
        assert not any(c == 'validation' for c in calls)
        calls.append('discovery')
        return original_search(*args, **kwargs)
    def validate(population, locked, config):
        assert calls[:2] == ['discovery', 'discovery']
        frozen = json.loads((tmp_path/'discoveries_frozen.json').read_text())
        assert frozen['both_discoveries_complete'] and not frozen['validation_started']
        assert (tmp_path/'fold_A_discovery.csv').exists() and (tmp_path/'fold_B_discovery.csv').exists()
        calls.append('validation')
        checked = original_validate(population, locked, config)
        assert [(r['genes'], r['states']) for r in checked] == [(r['genes'], r['states']) for r in locked]
        return checked
    monkeypatch.setattr(nt, 'discovery_search', search)
    monkeypatch.setattr(nt, '_validate', validate)
    # Different fold-owned modules: B's selection omits C but B must validate ABC.
    result = fit(parity('a', order=4, dependent_order=3), parity('b', order=4, dependent_order=3),
                 candidate_genes_a=list('ABC'), candidate_genes_b=list('ABD'), checkpoint_dir=tmp_path)
    assert calls == ['discovery', 'discovery', 'validation', 'validation']
    assert set(result.fold_b_validation.genes) == {tuple('ABC')}
    assert result.fold_a_validation.empty
    assert result.cross_fold_summary.A_to_B_replicated.all()
    assert not result.cross_fold_summary.B_to_A_replicated.any()
    assert result.cross_fold_summary.cross_fold_replicated.all()
    assert not result.cross_fold_summary.bidirectionally_rediscovered.any()
    frozen = json.loads((tmp_path/'discoveries_frozen.json').read_text())
    result.write(tmp_path)
    for name, expected_hash in frozen['files_sha256'].items():
        assert hashlib.sha256((tmp_path/name).read_bytes()).hexdigest() == expected_hash


def test_states_and_sign_direction_must_match_not_just_genes():
    result = fit(b=parity('b', mode='reversed'))
    cross = result.cross_fold_summary
    assert len(cross) == 8
    assert set(cross.genes) == {tuple('ABC')}
    assert not (cross.discovered_in_A & cross.discovered_in_B).any()
    assert not cross.cross_fold_replicated.any()
    assert not cross.bidirectionally_rediscovered.any()
    assert not result.fold_b_validation.reference_mfi_direction_consistent.any()
    assert not result.fold_a_validation.reference_mfi_direction_consistent.any()


def test_quality_failure_and_no_candidates_have_complete_output_schema(tmp_path):
    x = np.repeat([[0, 0, 0], [1, 1, 1]], 1000, axis=0)
    a = Population(x, tuple('ABC'), tuple(f'a{i}' for i in range(len(x))))
    b = Population(x, tuple('ABC'), tuple(f'b{i}' for i in range(len(x))))
    result = fit(a, b)
    assert result.cross_fold_summary.empty
    assert result.fold_b_validation.empty and result.fold_a_validation.empty
    assert not result.state_table_estimability.bootstrap_performed.any()
    assert result.state_table_estimability.mfi_bootstrap_ci_low.isna().all()
    assert result.state_table_estimability.mfi_lambda.isna().all()
    assert result.state_table_estimability.bootstrap_key.isna().all()
    assert not result.bootstrap_distributions
    assert set(result.state_table_estimability.order) == {2}
    result.write(tmp_path)
    for name in ['fold_A_discovery', 'fold_B_discovery', 'fold_A_validation', 'fold_B_validation',
                 'cross_fold_summary', 'state_table_estimability', 'order_reproducibility_summary']:
        assert len(pd.read_csv(tmp_path/(name+'.csv')).columns)
    assert len(np.load(tmp_path/'mfi_bootstrap_distributions.npz').files) == 0
    single = fit(candidate_genes_a=['A'], candidate_genes_b=['A'])
    assert single.fold_a_discovery.empty and single.state_table_estimability.empty
    assert single.order_reproducibility_summary.A_candidates_evaluated.sum() == 0


def test_bh_families_exactly_all_evaluated_or_locked_patterns_and_no_mfi_fdr_claim():
    result = fit()
    for role, frame in [('A_discovery', result.fold_a_discovery), ('B_discovery', result.fold_b_discovery),
                        ('B_validation_from_A', result.fold_b_validation), ('A_validation_from_B', result.fold_a_validation)]:
        family = result.metadata['bh_families'][role]
        assert family['n_tests'] == len(frame)
        assert family['reference_ids'] == frame.reference_id.tolist()
        assert family['reference_ids_sha256'] == hashlib.sha256(
            nt.canonical_json(frame.reference_id.tolist()).encode()).hexdigest()
        assert np.allclose(frame.q_value_null, benjamini_hochberg(frame.p_value_null))
    assert result.metadata['bh_families']['A_discovery']['n_tests'] == 20
    assert result.metadata['bh_families']['B_validation_from_A']['n_tests'] == 4
    assert not result.metadata['mfi_fdr_controlled'] and not result.metadata['union_fdr_controlled']
    with pytest.raises(ValueError, match='overlap'):
        fit(parity('a'), parity('a'))
    with pytest.raises(ValueError, match='union'):
        fit(candidate_genes_b=['Z'])


def test_fourway_pure_signal_is_supported_without_forcing_higher_orders():
    result = fit(parity('a', order=4), parity('b', order=4),
                 config=ReferenceConfig(max_order=4, n_bootstrap=80, random_seed=20260927))
    assert len(result.cross_fold_summary) == 8
    assert set(result.cross_fold_summary.order) == {4}
    assert result.cross_fold_summary.bidirectionally_rediscovered.all()
    assert not result.fold_a_discovery.query('order < 4').stable_in_discovery.any()
    assert result.metadata['stop_reason'] == {'A': 'max_order', 'B': 'max_order'}
    assert not (result.state_table_estimability.order > 4).any()
