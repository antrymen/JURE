import pytest
from clue_discovery import JointPattern, pattern_frequency, pattern_shift, benjamini_hochberg
from clue_discovery.synthetic import cells_from_counts


def test_frequency_alignment():
    S = cells_from_counts([1, 2, 3, 4, 5, 6, 7, 8])
    pattern = JointPattern(("C", "A", "B"), (1, 1, 0))
    result = pattern_frequency(S[["C", "B", "A"]], pattern)
    assert (result.cell_count, result.total_cells) == (6, 36)
    assert result.frequency == pytest.approx(1 / 6)


def test_fisher_against_known_table_and_zero_support():
    pattern = JointPattern(("A", "B"), (1, 1))
    control = cells_from_counts([3, 0, 0, 11])
    perturb = cells_from_counts([9, 0, 0, 1])
    result = pattern_shift(control, perturb, pattern)
    assert result["odds_ratio"] == pytest.approx(1 / 33)
    assert result["p_value_shift"] == pytest.approx(0.0027594561852200836)
    assert result["delta_frequency"] == pytest.approx(.1 - 11 / 14)
    zero = cells_from_counts([10, 0, 0, 0])
    assert pattern_shift(zero, zero, pattern)["p_value_shift"] == 1
    assert pattern_shift(zero, perturb, pattern)["risk_ratio"] > 1e6


def test_bh_known_values_ties_empty_and_invalid():
    assert benjamini_hochberg([.01, .04, .03, .002]).tolist() == pytest.approx([.02, .04, .04, .008])
    assert benjamini_hochberg([.1, .1]).tolist() == pytest.approx([.1, .1])
    assert len(benjamini_hochberg([])) == 0
    with pytest.raises(ValueError):
        benjamini_hochberg([float("nan")])
