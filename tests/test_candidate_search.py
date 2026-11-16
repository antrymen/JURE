import numpy as np
import pytest
from clue_discovery import DiscoveryConfig, discover_clues
from clue_discovery.candidate_search import should_expand
from clue_discovery.synthetic import cells_from_counts, parity_probabilities, GENES, independent


def test_parity_not_pruned_with_zero_pairwise_signal():
    control = cells_from_counts([1000] * 8)
    perturb = cells_from_counts(np.rint(parity_probabilities(.6) * 8000).astype(int))
    result = discover_clues(control, perturb, GENES, config=DiscoveryConfig(n_bootstrap=50))
    assert len(result.clues) == 20
    assert set(result.search_log.query("order == 2").reason) == {"support_only"}
    target = result.clues.set_index("pattern_string").loc["A+B-C+"]
    assert target.status == "candidate_clue"
    assert target.min_subset_support == 2000
    assert target.max_subset_shift == 0
    assert len(target.subset_summary) == 3
    strict = discover_clues(control, perturb, GENES,
                            config=DiscoveryConfig(allow_support_only=False, n_bootstrap=50))
    assert set(strict.clues.order) == {2}


def test_expansion_rules_and_budget():
    base = dict(support=30, expected_count_control=10, expected_count_perturb=10,
                p_value_shift=.001, p_value_null_control=.5, p_value_null_perturb=.5)
    config = DiscoveryConfig()
    assert should_expand(base, config) == (True, "shift_signal")
    assert should_expand({**base, "support": 1}, config) == (False, "insufficient_support")
    assert should_expand({**base, "expected_count_control": 0, "expected_count_perturb": 0}, config)[1] == "insufficient_expected_count"
    with pytest.raises(ValueError, match="budget"):
        discover_clues(independent(), independent(), GENES, config=DiscoveryConfig(max_candidates=11))
    with pytest.raises(ValueError, match="budget"):
        discover_clues(independent(), independent(), GENES, config=DiscoveryConfig(max_candidates=12))
