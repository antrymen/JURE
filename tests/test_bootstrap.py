import numpy as np
import pytest
from clue_discovery import DiscoveryConfig, JointPattern, discover_clues
from clue_discovery.bootstrap import bootstrap_pattern, summarize_distribution
from clue_discovery.synthetic import independent, parity, cells_from_counts, GENES


def test_bootstrap_reproducible_ci_direction_and_distributions():
    c, p = independent(seed=31), parity(seed=32)
    config = DiscoveryConfig(n_bootstrap=50)
    pattern = JointPattern(GENES, (1, 0, 1))
    result = bootstrap_pattern(c, p, pattern, config)
    assert result == bootstrap_pattern(c, p, pattern, config)
    assert result["bootstrap_delta_ci_low"] > 0
    assert result["bootstrap_mfi_perturb_ci_high"] < 0
    assert result["delta_sign_stability"] == result["mfi_perturb_sign_stability"] == 1
    assert len(result["bootstrap_distributions"]["delta"]) == 50
    assert result["bootstrap_delta_median"] == pytest.approx(np.median(result["bootstrap_distributions"]["delta"]))


def test_summary_sign_zero_and_percentiles():
    result = summarize_distribution([-1, 0, 1, 2], 1, .5)
    assert result["sign_stability"] == .5
    assert result["ci_low"] == -.25
    assert result["ci_high"] == 1.25
    assert summarize_distribution([0, 0], 0)["sign_stability"] == 0


def test_rare_pattern_bootstrap_instability_if_support_gate_relaxed():
    c = cells_from_counts([199, 0, 0, 0, 0, 1, 0, 0])
    p = cells_from_counts([196, 0, 0, 0, 0, 4, 0, 0])
    config = DiscoveryConfig(min_support=1, min_delta=0, min_detection_rate=0,
                             max_detection_rate=1, alpha_shift=.999, alpha_null=.999,
                             n_bootstrap=200, expansion_min_expected=0)
    result = discover_clues(c, p, GENES, config=config)
    target = result.clues.set_index("pattern_string").loc["A+B-C+"]
    assert target.bootstrap_performed
    assert target.delta_sign_stability < .95
    assert target.status == "unstable"
