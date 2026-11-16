import numpy as np
import pytest
from scipy.stats import binom
from clue_discovery import JointPattern, dtuple_deviation
from clue_discovery.synthetic import cells_from_counts, parity_probabilities


def test_independence_and_exact_upper_tail():
    pattern = JointPattern(("A", "B", "C"), (1, 0, 1))
    result = dtuple_deviation(cells_from_counts([10] * 8), pattern)
    assert result["null_probability"] == .125
    assert result["expected_count"] == result["observed_count"] == 10
    assert result["log2_enrichment"] == 0
    expected_tail = sum(binom.pmf(k, 80, .125) for k in range(10, 81))
    assert result["p_value_null"] == pytest.approx(expected_tail)


def test_true_parity_deviating_tuple():
    S = cells_from_counts(np.rint(parity_probabilities(.6) * 8000).astype(int))
    result = dtuple_deviation(S, JointPattern(("A", "B", "C"), (1, 0, 1)))
    assert result["observed_frequency"] == .2
    assert result["expected_frequency"] == .125
    assert result["log2_enrichment"] > .67
    assert result["p_value_null"] < 1e-70


def test_boundary_null_and_reserved():
    S = cells_from_counts([10, 0, 0, 0])
    assert dtuple_deviation(S, JointPattern(("A", "B"), (1, 1)))["p_value_null"] == 1
    assert dtuple_deviation(S, JointPattern(("A", "B"), (0, 0)))["p_value_null"] == 1
    with pytest.raises(NotImplementedError):
        dtuple_deviation(S, JointPattern(("A", "B"), (0, 0)), null_model="pairwise_maxent")
