"""Reproducible benchmark contract and analytically specified signal labels."""
import json
import numpy as np
import pytest
import yaml

from clue_discovery.v03.mfi import mfi_from_probabilities
from clue_discovery.v03.config import ScalableConfig
from clue_discovery.v03.synthetic import (
    StatisticalBenchmarkConfig, integer_table, pairwise_only_probabilities,
    run_statistical_benchmark, synthetic_cases, _binomial_interval, _effective_config,
)


def test_known_distributions_do_not_accidentally_encode_wrong_order():
    cases = synthetic_cases()
    assert abs(mfi_from_probabilities(pairwise_only_probabilities())) < 1e-12
    assert abs(mfi_from_probabilities(cases["redundant_extension"]["probabilities"])) < 1e-12
    assert abs(mfi_from_probabilities(cases["pure_three_way"]["probabilities"])) > 1
    assert abs(mfi_from_probabilities(cases["pure_four_way"]["probabilities"])) > 1
    for case in cases.values():
        counts = integer_table(case["probabilities"], 5345)
        assert counts.sum() == 5345
        assert (counts >= 0).all()
        assert np.abs(counts - case["probabilities"] * 5345).max() < 1


def test_config_preserves_main_scientific_parameters_and_binomial_boundaries():
    main = ScalableConfig(n_null_simulations=999, n_bootstrap=1000, random_seed=93)
    effective, source = _effective_config(main)
    assert effective.n_null_simulations == 999
    assert effective.n_bootstrap == 1000
    assert effective.random_seed == 93
    assert source == main.to_dict()
    interval = _binomial_interval(0, 24)
    assert interval["ci_low"] == 0
    assert .1 < interval["ci_high"] < .2
    assert _binomial_interval(24, 24)["ci_high"] == 1
    with pytest.raises(ValueError):
        StatisticalBenchmarkConfig(null_repetitions=0)


def test_benchmark_freezes_before_analysis_and_exports_full_artifacts(tmp_path, monkeypatch):
    from clue_discovery.v03 import synthetic
    original = synthetic.HigherOrderGainEvaluator.evaluate
    path = tmp_path / "audit"
    snapshots = []

    def checked_evaluate(self, counts):
        assert (path / "config_frozen.yaml").exists()
        snapshots.append((path / "config_frozen.yaml").read_bytes())
        return original(self, counts)

    monkeypatch.setattr(synthetic.HigherOrderGainEvaluator, "evaluate", checked_evaluate)
    config = StatisticalBenchmarkConfig(n_null_simulations=39, n_bootstrap=30, null_repetitions=3)
    summary = run_statistical_benchmark(path, config)
    assert summary["all_named_case_expectations_met"]
    assert len(set(snapshots)) == 1
    frozen = yaml.safe_load((path / "config_frozen.yaml").read_text())
    assert frozen["config"]["n_null_simulations"] == 39
    assert frozen["parameter_adaptation"] is False
    assert summary["false_positive_audit"]["parametric"]["repetitions"] == 3
    assert json.loads((path / "run_manifest.json").read_text())["status"] == "complete"
    for name in ("pure_three_way", "redundant_extension"):
        arrays = np.load(path / "cases" / name / "bootstrap.npz")
        assert arrays["mfi"].shape == (30,)
        assert arrays["pattern_absolute_gain"].shape[0] == 30
        document = json.loads((path / "cases" / name / "statistics.json").read_text())
        assert document["bootstrap_summary"]["set_level_gain"]["sign_stability"] is None
    with pytest.raises(FileExistsError):
        run_statistical_benchmark(path, config)


def test_benchmark_stochastic_draws_reproduce_with_frozen_seed(tmp_path):
    config = StatisticalBenchmarkConfig(n_null_simulations=39, n_bootstrap=20, null_repetitions=2)
    left = run_statistical_benchmark(tmp_path / "left", config)
    right = run_statistical_benchmark(tmp_path / "right", config)
    assert left["config_hash"] == right["config_hash"]
    assert left["cases"] == right["cases"]
    assert left["false_positive_audit"] == right["false_positive_audit"]
    for repeat in range(config.null_repetitions):
        a = np.load(tmp_path / "left" / "null_repetitions" / f"replicate_{repeat:03}.npz")
        b = np.load(tmp_path / "right" / "null_repetitions" / f"replicate_{repeat:03}.npz")
        for key in a.files:
            np.testing.assert_array_equal(a[key], b[key])
