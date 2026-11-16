import numpy as np
import pandas as pd
import pytest
from scipy.sparse import csr_matrix
from clue_discovery import encode_binary_states, DiscoveryConfig, discover_clues


def test_counts_threshold_and_qc():
    S, qc = encode_binary_states([[0, 1], [2, 3]], gene_names=["A", "B"], threshold=1)
    assert S.values.tolist() == [[0, 0], [1, 1]]
    assert qc.number_detected.tolist() == [1, 1]
    assert qc.detection_rate.tolist() == [.5, .5]
    assert qc.number_undetected.tolist() == [1, 1]


@pytest.mark.parametrize("bad", [[[np.nan]], [[-1]], [[.5]], [[]], [1, 2]])
def test_invalid_counts(bad):
    with pytest.raises(ValueError):
        encode_binary_states(bad)


def test_expression_explicit_and_sparse():
    S, _ = encode_binary_states([[0.0, .5]], input_kind="expression", threshold=.1)
    assert S.values.tolist() == [[0, 1]]
    S, _ = encode_binary_states(csr_matrix([[0, 2]]))
    assert S.values.tolist() == [[0, 1]]


def test_config_and_reserved_modes():
    for kwargs in ({"n_bootstrap": 0}, {"min_support": -1}, {"ci_level": 1},
                   {"smoothing_alpha": 0}, {"min_delta": np.nan}):
        with pytest.raises(ValueError):
            DiscoveryConfig(**kwargs)
    for kwargs in ({"mfi_mode": "conditional"}, {"null_model": "pairwise_maxent"}, {"max_order": 4}):
        with pytest.raises(NotImplementedError):
            DiscoveryConfig(**kwargs)


def test_filtering_and_candidate_module():
    X = pd.DataFrame({"A": [0, 1] * 100, "B": [1, 0] * 100, "constant": [0] * 200})
    result = discover_clues(X, X, X.columns)
    assert result.metadata["retained_genes"] == ["A", "B"]
    assert len(result.clues) == 4
    subset = discover_clues(csr_matrix(X), csr_matrix(X), X.columns, candidate_genes=["A", "B"])
    pd.testing.assert_frame_equal(result.clues, subset.clues)
    with pytest.raises(ValueError):
        discover_clues(X, X[["B", "A", "constant"]], X.columns)
