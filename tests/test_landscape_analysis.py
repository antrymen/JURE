"""Checks for failure modes that would change scientific interpretation."""
import numpy as np
import pytest
from landscape_analysis.core import (adjusted_rand, block_feature_weights, hierarchy,
    matrix_views, resampling_stability, signed_candidate_jaccard)


def test_nonselected_effect_is_not_zero_or_missing_observation():
    delta = np.array([[.20, -.22, .06, .15, .30, np.nan, 0.]])
    candidate = np.array([[True, True, False, False, False, False, False]])
    tested = np.array([[True, True, False, True, False, False, False]])
    reason = np.array([['', '', 'effect_below_prespecified_minimum', '',
                       'insufficient_perturbation_cells', 'missing_matched_NT',
                       'effect_below_prespecified_minimum']])
    v = matrix_views(delta, candidate, tested, reason)
    assert v['observed'][0, 2] == .06
    assert np.isnan(v['candidate_only'][0, 2])
    assert v['selection_encoded'][0, 2] == 0
    assert np.isnan(v['selection_encoded'][0, 4])
    assert v['observed'][0, 4] == .30
    assert v['status'][0, 3] == 'tested_not_qualified'
    assert v['status'][0, 1] == 'candidate_depletion'
    assert v['status'][0, 2] != v['status'][0, 4]
    assert v['observed'][0, 6] == 0


def test_candidate_requires_finite_tested_directional_effect():
    with pytest.raises(ValueError):
        matrix_views([[.2]], [[True]], [[False]], [['']])
    with pytest.raises(ValueError):
        matrix_views([[np.nan]], [[True]], [[True]], [['']])


def test_signed_shape_groups_scaled_profiles_and_separates_opposites():
    x = np.array([[.2, -.1, .3], [.4, -.2, .6], [-.2, .1, -.3], [0, 0, 0]])
    result = hierarchy(x, 'cosine')
    assert result['labels'][0] == result['labels'][1]
    assert result['labels'][0] != result['labels'][2]
    assert result['labels'][3] == 0
    assert not result['valid'][3]
    constant = hierarchy(np.array([[1, 1, 1], [1, 2, 3], [3, 2, 1]]), 'correlation')
    assert not constant['valid'][0]


def test_triplet_bootstrap_keeps_states_together_and_multiplicity():
    block = np.array(['abc', 'abc', 'def'])
    weights = block_feature_weights(block, np.array(['abc', 'abc']))
    np.testing.assert_allclose(weights, [np.sqrt(2), np.sqrt(2), 0])
    x = np.array([[1., 2., 3.], [-1., 0., 2.]])
    repeated = x[:, [0, 1, 0, 1]]
    original = x * weights
    def cosine(a): return a[0] @ a[1] / np.linalg.norm(a[0]) / np.linalg.norm(a[1])
    assert cosine(original) == pytest.approx(cosine(repeated))


def test_signed_jaccard_counts_opposing_states_as_distinct_elements():
    a = np.array([True, True])
    value, shared = signed_candidate_jaccard(a, np.array([.2, .2]), a, np.array([.3, -.3]))
    assert shared == 1
    assert value == pytest.approx(1 / 3)


def test_adjusted_rand_is_invariant_to_group_names_and_detects_split():
    assert adjusted_rand([1, 1, 2, 2], [7, 7, 8, 8]) == 1
    assert adjusted_rand([1, 1, 2, 2], [7, 8, 7, 8]) == pytest.approx(-.5)


def test_resampling_reproducible_and_pair_values_bounded():
    rng = np.random.default_rng(123)
    x = rng.normal(size=(10, 6))
    args = (x, np.array(['a', 'a', 'a', 'b', 'b', 'b']),
            np.array(['T1'] * 5 + ['T2'] * 5), np.array(['M1'] * 3 + ['M2'] * 3))
    first = resampling_stability(*args, repetitions=4)
    second = resampling_stability(*args, repetitions=4)
    np.testing.assert_array_equal(first['target_coassignment'], second['target_coassignment'])
    for key in ('target_coassignment', 'pattern_coassignment'):
        assert ((first[key] >= 0) & (first[key] <= 1)).all()
        np.testing.assert_array_equal(first[key], first[key].T)
