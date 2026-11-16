"""Statistical identification, conditional calibration, and baseline invariants."""
from itertools import combinations
import numpy as np
import pytest
from scipy.special import softmax
from scipy.stats import hypergeom

from clue_discovery.v02.statistics import mfi_from_counts as v02_mfi
from clue_discovery.v03.estimator import EmpiricalJointEstimator, smoothed_probabilities, state_space
from clue_discovery.v03.estimability import assess_estimability
from clue_discovery.v03.mfi import contrast_signs, mfi_from_counts
from clue_discovery.v03.lower_order_null import LowerOrderNullModel
from clue_discovery.v03.gain import HigherOrderGainEvaluator, GainNullCalibration, conditional_gain_test
from clue_discovery.v03.bootstrap import bootstrap_gene_set


def _parity_counts(order, strength=0.45, base=1000):
    return np.rint(base * (1 + strength * contrast_signs(order))).astype(int)


def test_empirical_interface_preserves_complete_table_and_v02_smoothing():
    counts = np.array([40, 10, 5, 50, 0, 25, 80, 90])
    cells = np.repeat(state_space(3), counts, axis=0)
    estimator = EmpiricalJointEstimator().fit(cells, genes=["A", "B", "C"])
    assert len(estimator.state_table()) == 8
    np.testing.assert_array_equal(estimator.counts, counts)
    np.testing.assert_allclose(estimator.probabilities, (counts + .5) / (counts.sum() + 4))
    assert estimator.joint_probability((1, 0, 0), raw=True) == 0
    assert estimator.joint_probability((1, 0, 0)) > 0
    np.testing.assert_allclose(estimator.marginal(["A", "C"]), estimator.probabilities.reshape(2, 2, 2).sum(axis=1).ravel())
    assert estimator.conditional_probability({"C": 1}, {"A": 1}) == pytest.approx(
        estimator.probabilities[[5, 7]].sum() / estimator.probabilities[4:].sum())
    assert mfi_from_counts(counts) == pytest.approx(v02_mfi(counts), abs=1e-12)
    intervals = estimator.uncertainty(n_bootstrap=100, seed=5)
    assert intervals["probabilities"].shape == (100, 8)
    with pytest.raises(ValueError):
        EmpiricalJointEstimator().fit(np.array([[0, 3], [1, 0]]))


@pytest.mark.parametrize("order", [2, 3, 4])
def test_projection_matches_all_proper_margins_and_removes_only_highest_term(order):
    states = state_space(order)
    rng = np.random.default_rng(74 + order)
    p = rng.dirichlet(np.ones(2 ** order))
    fit = LowerOrderNullModel().fit(p)
    assert fit.success
    assert fit.max_marginal_error < 1e-14
    assert abs(fit.highest_order_log_contrast) < 2e-9
    assert fit.probabilities.sum() == pytest.approx(1)
    for size in range(1, order):
        for axes in combinations(range(order), size):
            codes = states[:, axes] @ (2 ** np.arange(size - 1, -1, -1))
            np.testing.assert_allclose(np.bincount(codes, weights=p),
                                       np.bincount(codes, weights=fit.probabilities), atol=1e-13)


def test_pairwise_only_loglinear_null_and_pure_triplet_are_distinguished():
    states = state_space(3).astype(float)
    p = softmax(.35 * states[:, 0] - .2 * states[:, 1] + .1 * states[:, 2]
                + .8 * states[:, 0] * states[:, 1] - .5 * states[:, 0] * states[:, 2]
                + .45 * states[:, 1] * states[:, 2])
    fit = LowerOrderNullModel().fit(p)
    np.testing.assert_allclose(fit.probabilities, p, atol=1e-12)
    null_counts = np.rint(40000 * p).astype(int)
    null_gain = HigherOrderGainEvaluator().evaluate(null_counts)
    assert null_gain["set_level_gain"] < 1e-8
    assert GainNullCalibration(n_simulations=199, seed=48).calibrate(null_counts)["p_gain"] > .5
    signal_counts = _parity_counts(3)
    observed = HigherOrderGainEvaluator().evaluate(signal_counts)
    assert observed["set_level_gain"] > .1
    assert GainNullCalibration(n_simulations=199, seed=48).calibrate(signal_counts)["p_gain"] == .005
    # Pure parity has exactly independent pair margins, demonstrating why a
    # dependency-only screen is insufficient (search coverage is tested elsewhere).
    for axes in combinations(range(3), 2):
        codes = states[:, axes].astype(int) @ np.array([2, 1])
        np.testing.assert_array_equal(np.bincount(codes, weights=signal_counts), np.full(4, 2000))


def test_independent_redundant_extension_has_no_four_way_gain_but_parity_does():
    triple = _parity_counts(3)
    redundant = np.repeat(triple, 2)
    no_increment = HigherOrderGainEvaluator().evaluate(redundant)
    assert no_increment["set_level_gain"] < 1e-12
    assert abs(no_increment["mfi"]) < 1e-12
    true_quad = HigherOrderGainEvaluator().evaluate(_parity_counts(4))
    assert true_quad["set_level_gain"] > .1
    assert true_quad["null_parameters"]["formal_status"] == "exploratory"


def test_gain_probabilities_are_in_same_space_and_have_separate_effects():
    counts = np.array([5, 1, 20, 8, 14, 9, 2, 15])
    result = HigherOrderGainEvaluator().evaluate(counts)
    assert not np.allclose(result["raw_frequency"], result["observed_probability"])
    np.testing.assert_allclose(result["pattern_absolute_gain"],
                               result["observed_probability"] - result["lower_order_expected_probability"])
    np.testing.assert_allclose(np.exp(result["log_enrichment"]), result["relative_enrichment"])
    assert sum(result["pattern_absolute_gain"]) == pytest.approx(0, abs=1e-14)
    assert result["set_level_gain"] >= 0


def test_null_calibration_refits_every_draw_and_matches_manual_calculation():
    counts = np.array([100, 60, 70, 100, 90, 130, 75, 110])
    seed, total = 31, 19
    observed = HigherOrderGainEvaluator().evaluate(counts)
    draws = np.random.default_rng(seed).multinomial(sum(counts), observed["lower_order_expected_probability"], size=total)
    manual = [HigherOrderGainEvaluator().evaluate(row)["set_level_gain"] for row in draws]
    result = GainNullCalibration(n_simulations=total, seed=seed, batch_size=4).calibrate(counts)
    np.testing.assert_allclose(result["null_gain"], manual, atol=1e-13)
    expected_p = (1 + sum(x >= observed["set_level_gain"] - 1e-12 for x in manual)) / (total + 1)
    assert result["p_gain"] == expected_p
    assert result["null_refit_count"] == total
    assert result["fit_failures"] == 0
    assert result["p_resolution"] == .05
    assert result["q_gain"] is None


def test_bootstrap_reuses_one_table_draw_for_all_states_and_gains_are_not_signed():
    counts = _parity_counts(3)
    seed, total = 47, 51
    result = bootstrap_gene_set(counts, seed=seed, n_bootstrap=total, batch_size=7)
    draws = np.random.default_rng(seed).multinomial(sum(counts), counts / sum(counts), size=total)
    np.testing.assert_allclose(result["arrays"]["mfi"], [v02_mfi(row) for row in draws], atol=1e-12)
    manual = [HigherOrderGainEvaluator().evaluate(row) for row in draws]
    np.testing.assert_allclose(result["arrays"]["set_level_gain"], [x["set_level_gain"] for x in manual], atol=1e-12)
    np.testing.assert_allclose(result["arrays"]["pattern_absolute_gain"], [x["pattern_absolute_gain"] for x in manual], atol=1e-12)
    assert result["summary"]["set_level_gain"]["sign_stability"] is None
    assert len(result["summary"]["pattern_absolute_gain"]) == 8
    assert result["summary"]["mfi"]["sign_stability"] == 1
    no_gain = bootstrap_gene_set(counts, seed=seed, n_bootstrap=total, compute_gain=False)
    assert set(no_gain["arrays"]) == {"mfi"}
    np.testing.assert_allclose(no_gain["arrays"]["mfi"], result["arrays"]["mfi"])
    assert no_gain["null_refit_count"] == 0


@pytest.mark.parametrize("counts", [[3, 5, 7, 2], [2, 1, 4, 3, 1, 2, 3, 5], [0, 2, 0, 1, 4, 0, 3, 0]])
def test_conditional_fiber_weights_margins_and_gain_tail(counts):
    counts = np.array(counts)
    result = conditional_gain_test(counts, batch_size=2)
    signs = contrast_signs(int(np.log2(len(counts)))).astype(int)
    tables = counts[None, :] + result["offsets"][:, None] * signs
    assert (tables >= 0).all()
    assert result["null_weights"].sum() == pytest.approx(1)
    q = HigherOrderGainEvaluator().evaluate(counts)["lower_order_expected_probability"]
    for row in tables:
        np.testing.assert_allclose(HigherOrderGainEvaluator().evaluate(row)["lower_order_expected_probability"], q, atol=1e-9)
    manual = np.array([HigherOrderGainEvaluator().evaluate(row)["set_level_gain"] for row in tables])
    np.testing.assert_allclose(result["null_gain"], manual, atol=1e-10)
    tail = manual >= result["observed_gain"] - result["tail_tolerance"]
    assert result["p_gain"] == pytest.approx(result["null_weights"][tail].sum())
    if len(counts) == 4:
        expected = hypergeom.pmf(tables[:, 0], counts.sum(), counts[:2].sum(), counts[[0, 2]].sum())
        np.testing.assert_allclose(result["null_weights"], expected, atol=1e-12)


def test_conditional_zero_dimensional_fiber_and_sparse_estimability():
    counts = np.array([100, 0, 0, 0, 0, 0, 0, 100])
    result = conditional_gain_test(counts)
    assert result["support_size"] == 1
    assert result["p_gain"] == 1
    assessment = assess_estimability(counts)
    assert assessment["status"] == "poor"
    assert assessment["states_below_5"] == 6
    assert assessment["zero_state_fraction"] == .75
    assert assessment["min_state_count"] == 0
    assert assessment["min_observed_state_count"] == 100
    assert assessment["prune_reasons"]
    assert assess_estimability(np.full(8, 12), good_min_count=10)["status"] == "good"
    assert assess_estimability(np.full(8, 12), good_min_count=20)["status"] == "borderline"


def test_fit_failure_is_reported_without_silently_dropping_draws():
    counts = np.array([100, 60, 70, 100, 90, 130, 75, 110])

    class FailingBatchModel(LowerOrderNullModel):
        def fit_batch(self, probabilities):
            q, success = super().fit_batch(probabilities)
            if len(probabilities) > 1:
                success[0] = False
            return q, success

    result = GainNullCalibration(n_simulations=19, seed=4, null_model=FailingBatchModel()).calibrate(counts)
    assert result["fit_failures"] == 1
    assert result["p_gain"] is None
    assert result["status"] == "null_fit_failed"
    boot = bootstrap_gene_set(counts, n_bootstrap=19, null_model=FailingBatchModel())
    assert boot["fit_failures"] == 1
    assert boot["summary"]["set_level_gain"] is None


def test_sparse_boundary_null_fit_avoids_probability_cancellation():
    # The fitted minimum probability is ~1e-14, much smaller than the input
    # pseudocount mass ~1e-4. A naive p+delta*s loses log-contrast accuracy.
    counts = np.array([9, 1, 0, 412, 179, 205, 216, 1, 815, 569, 668, 3, 0, 4, 0, 2263])
    p = smoothed_probabilities(counts)
    fit = LowerOrderNullModel().fit(p)
    assert fit.success
    assert fit.probabilities.min() < 1e-13
    assert abs(fit.highest_order_log_contrast) < 2e-9
    assert fit.max_marginal_error < 1e-14
