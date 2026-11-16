import numpy as np
import pandas as pd
import pytest
from clue_discovery import DiscoveryConfig, discover_clues
from clue_discovery.synthetic import GENES, independent, parity


def replicated(strength=.6):
    c1, c2 = independent(seed=21), independent(seed=23)
    p1, p2 = parity(seed=22), parity(seed=24, strength=strength)
    labels = np.repeat(["Rep1", "Rep2"], 8000)
    return discover_clues(pd.concat([c1, c2]), pd.concat([p1, p2]), GENES,
                          config=DiscoveryConfig(n_bootstrap=50), replicate_control=labels,
                          replicate_perturb=labels, discovery_replicate="Rep1")


def test_same_direction_and_opposite_locked_replicate():
    positive, negative = replicated(), replicated(-.6)
    r1 = positive.clues.set_index("pattern_string").loc["A+B-C+"]
    r2 = negative.clues.set_index("pattern_string").loc["A+B-C+"]
    assert r1.status == "reproducible_clue"
    assert r1.replicate_direction_consistent
    assert r1.delta_direction_consistent and r1.mfi_direction_consistent
    assert r1.replicate_delta_values["Rep1"] > 0 and r1.replicate_delta_values["Rep2"] > 0
    assert r2.status == "not_replicated"
    assert not r2.replicate_direction_consistent
    assert r2.replicate_delta_values["Rep2"] < 0
    assert r1.absolute_delta_difference["Rep2"] == pytest.approx(abs(
        r1.replicate_delta_values["Rep1"] - r1.replicate_delta_values["Rep2"]))
    # Held-out data cannot influence discovery candidates, filtering, FDR or bootstrap.
    pd.testing.assert_frame_equal(positive.search_log, negative.search_log)
    pd.testing.assert_frame_equal(positive.gene_qc, negative.gene_qc)
    columns = ["pattern_string", "delta_frequency", "mfi_perturb", "q_value_shift",
               "q_value_null_perturb", "bootstrap_distributions"]
    pd.testing.assert_frame_equal(positive.clues[columns], negative.clues[columns])
    single = discover_clues(independent(seed=21), parity(seed=22), GENES,
                            config=DiscoveryConfig(n_bootstrap=50))
    pd.testing.assert_frame_equal(single.clues[columns], positive.clues[columns])
    tested = positive.clues.query("replication_status != 'not_tested'")
    assert set(tested.pattern_string) == set(single.clues.query("status == 'candidate_clue'").pattern_string)


def test_invalid_labels_and_explicit_discovery_required():
    c, p = independent(n=100), parity(n=100)
    labels = ["R1"] * 50 + ["R2"] * 50
    with pytest.raises(ValueError, match="explicitly"):
        discover_clues(c, p, GENES, replicate_control=labels, replicate_perturb=labels)
    with pytest.raises(ValueError, match="both"):
        discover_clues(c, p, GENES, replicate_control=labels)
    with pytest.raises(ValueError, match="matching"):
        discover_clues(c, p, GENES, replicate_control=labels, replicate_perturb=["R3"] * 100)
    with pytest.raises(ValueError, match="labels"):
        discover_clues(c, p, GENES, replicate_control=labels[:-1], replicate_perturb=labels)


def test_low_support_validation_not_claimed_reproduced():
    c1, p1 = independent(seed=21), parity(seed=22)
    c2, p2 = independent(n=20, seed=23), parity(n=20, seed=24)
    labels = ["R1"] * 8000 + ["R2"] * 20
    result = discover_clues(pd.concat([c1, c2]), pd.concat([p1, p2]), GENES,
                            config=DiscoveryConfig(n_bootstrap=50), replicate_control=labels,
                            replicate_perturb=labels, discovery_replicate="R1")
    assert not (result.clues.status == "reproducible_clue").any()
