import json
import numpy as np
import pandas as pd
import pytest
from clue_discovery import DiscoveryConfig, discover_clues
from clue_discovery.synthetic import GENES, independent, pairwise_only, parity, rare_pattern
from clue_discovery.io import CLUE_COLUMNS


@pytest.mark.parametrize("scenario", ["independent", "pairwise", "three_way", "perturbation", "rare"])
def test_required_synthetic_scenarios(scenario):
    c = independent(seed=1)
    p = {"independent": lambda: independent(seed=2), "pairwise": pairwise_only,
         "three_way": parity, "perturbation": lambda: parity(seed=12), "rare": lambda: None}[scenario]()
    if scenario == "rare":
        c, p = rare_pattern()
    result = discover_clues(c, p, GENES, config=DiscoveryConfig(n_bootstrap=50))
    target = result.clues.set_index("pattern_string").loc["A+B-C+"]
    triples = result.clues.query("order == 3")
    if scenario in ("independent", "pairwise"):
        assert not triples.status.isin(["candidate_clue", "reproducible_clue"]).any()
        assert abs(target.mfi_perturb) < .5
        if scenario == "pairwise":
            assert result.clues.set_index("pattern_string").loc["A+B+", "mfi_perturb"] > 3
            assert triples.q_value_null_perturb.min() < .05
    elif scenario in ("three_way", "perturbation"):
        assert target.status == "candidate_clue"
        assert target.perturb_frequency > target.control_frequency
        assert target.delta_frequency > .05
        assert target.q_value_shift < .05
        assert target.q_value_null_perturb < .05
        assert target.mfi_perturb < -4
        assert abs(target.mfi_control) < .5
        assert target.delta_sign_stability >= .95
        assert target.mfi_perturb_sign_stability >= .95
        assert target.replication_status == "not_available"
    else:
        assert target.risk_ratio > 1e6
        assert target.log2_enrichment_perturb > 2
        assert target.q_value_null_perturb < .05
        assert target.perturb_count == 3
        assert target.status == "insufficient_support"
        assert not target.bootstrap_performed


def test_csv_json_audit_and_empty_output(tmp_path):
    result = discover_clues(independent(), parity(), GENES, config=DiscoveryConfig(n_bootstrap=50))
    result.write(tmp_path)
    clues = pd.read_csv(tmp_path / "clues.csv")
    assert set(CLUE_COLUMNS) <= set(clues.columns)
    assert len(pd.read_csv(tmp_path / "candidate_search_log.csv")) == len(clues)
    row = clues.set_index("pattern_string").loc["A+B-C+"]
    assert json.loads(row.genes) == list(GENES)
    assert json.loads(row.raw_state_counts_control)["101"] == row.control_count
    assert len(json.loads(row.subset_summary)) == 3
    assert len(json.loads(row.bootstrap_distributions)["delta"]) == 50
    meta = json.loads((tmp_path / "run_metadata.json").read_text())
    assert meta["tested_patterns"] == 20
    empty = discover_clues(np.zeros((20, 3)), np.zeros((20, 3)), GENES)
    assert empty.clues.empty
    empty.write(tmp_path / "empty")
    assert set(CLUE_COLUMNS) <= set(pd.read_csv(tmp_path / "empty" / "clues.csv").columns)
    assert pd.read_csv(tmp_path / "empty" / "candidate_search_log.csv").empty
