import numpy as np
import pytest
from clue_discovery.mfi import mfi_from_counts, calculate_mfi, joint_state_counts
from clue_discovery.synthetic import cells_from_counts, parity_probabilities


def test_eq1_log_odds():
    assert mfi_from_counts([10, 20, 30, 40], alpha=0).value == pytest.approx(np.log(10 * 40 / (20 * 30)))


def test_eq2_all_eight_states():
    counts = np.arange(1, 9)
    expected = np.log((8 * 5 * 3 * 2) / (7 * 6 * 4 * 1))
    result = calculate_mfi(cells_from_counts(counts), alpha=0)
    assert result.value == pytest.approx(expected)
    assert result.raw_state_counts["101"] == 6
    assert result.smoothing_alpha == 0
    assert joint_state_counts(cells_from_counts(counts)).tolist() == counts.tolist()


def test_smoothing_zero_and_invalid():
    result = mfi_from_counts([0, 1, 0, 10])
    assert np.isfinite(result.value)
    assert result.raw_state_counts == {"00": 0, "01": 1, "10": 0, "11": 10}
    with pytest.raises(ValueError):
        mfi_from_counts([0, 1, 0, 10], alpha=0)
    with pytest.raises(ValueError):
        mfi_from_counts([0, 0, 0, 0])
    with pytest.raises(NotImplementedError):
        mfi_from_counts([1] * 8, mode="conditional")


def test_independent_pairwise_and_parity_truth():
    assert mfi_from_counts([100] * 8).value == 0
    assert mfi_from_counts([225, 225, 25, 25, 25, 25, 225, 225]).value == 0
    S = cells_from_counts(np.rint(parity_probabilities(.6) * 8000).astype(int))
    assert calculate_mfi(S, alpha=0).value == pytest.approx(4 * np.log(.4 / 1.6))
    assert np.all(S.mean() == .5)
    for genes in (("A", "B"), ("A", "C"), ("B", "C")):
        assert calculate_mfi(S, genes, alpha=0).value == 0
        assert joint_state_counts(S, genes).tolist() == [2000] * 4
