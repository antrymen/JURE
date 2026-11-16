"""Audit-harness integrity tests; not substitutes for the real-data run."""
import numpy as np
import pandas as pd
import pytest
from scipy import sparse
from real_data_test.prepare import checked_counts, choose_targets, sample_matched
from real_data_test.report import recovery_metrics


def test_capacity_selection_excludes_locked_genes_and_is_deterministic():
    counts = {f"G{i}": n for i, n in enumerate([110, 120, 130, 160, 170, 180, 310, 400, 500])}
    chosen = choose_targets(counts, {"G0", "G3", "G6"})
    assert len(chosen) == 6
    assert not set(chosen) & {"G0", "G3", "G6"}
    assert chosen == choose_targets(counts, {"G0", "G3", "G6"})


def test_matching_counts_and_disjoint_null_groups():
    pool = np.arange(40)
    batches = np.array(["A"]*20 + ["B"]*20)
    rng = np.random.default_rng(4)
    pert = sample_matched(pool, batches, {"A": 2, "B": 3}, rng)
    ctrl = sample_matched(np.setdiff1d(pool, pert), batches, {"A": 2, "B": 3}, rng, 3)
    assert len(pert) == 5 and len(ctrl) == 15
    assert not set(pert) & set(ctrl)
    assert (batches[ctrl] == "B").sum() == 9
    with pytest.raises(ValueError, match="need"):
        sample_matched(pool, batches, {"A": 21}, rng)


def test_integer_counts_rejected_if_normalized():
    assert checked_counts(sparse.csr_matrix([[0., 1.], [2., 0.]])).nnz == 2
    with pytest.raises(ValueError):
        checked_counts([[0, .5]])


def test_recovery_measures_exact_pattern_and_zero_denominator():
    baseline = pd.DataFrame({"pattern_string": ["A+B-C+", "A-B+C-"], "order": [3, 3],
                             "status": ["candidate_clue"]*2, "delta_frequency": [.2, -.1]})
    sample = baseline.copy()
    sample.loc[1, "status"] = "insufficient_support"
    result = recovery_metrics(baseline, sample)
    assert result["exact_pattern_recall"] == .5
    assert result["baseline_patterns_still_searched"] == 2
    assert result["direction_consistent_fraction"] == 1
    assert result["top_effect_recall"] == .5
    assert recovery_metrics(baseline.iloc[:0], sample)["exact_pattern_recall"] is None
