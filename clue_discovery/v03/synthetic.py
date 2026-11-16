"""Predeclared statistical checks and null-error-rate audit for v0.3.

This benchmark checks a known candidate's statistics. It does not measure
candidate-search recall, cross-fold reproducibility, or real-data performance.
No observed result changes thresholds, seeds, simulations, or sample sizes.
"""
from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import softmax
from scipy.stats import beta
import yaml

from .artifacts import clean, digest, software_versions, write_csv, write_json
from .bootstrap import bootstrap_gene_set
from .config import ScalableConfig
from .estimator import state_space
from .estimability import assess_estimability
from .gain import HigherOrderGainEvaluator, GainNullCalibration, conditional_gain_test
from .mfi import contrast_signs, mfi_from_probabilities


@dataclass(frozen=True)
class StatisticalBenchmarkConfig:
    random_seed: int = 20260927
    smoothing_alpha: float = .5
    n_null_simulations: int = 1999
    n_bootstrap: int = 1000
    alpha_gain: float = .05
    ci_level: float = .95
    min_abs_mfi: float = .5
    min_sign_stability: float = .95
    null_repetitions: int = 24
    null_sample_size: int = 5345
    case_sample_size: int = 8000
    parity_strength: float = .45

    def __post_init__(self):
        for field in ("n_null_simulations", "null_repetitions", "null_sample_size", "case_sample_size"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field} must be a positive integer")
        if not isinstance(self.n_bootstrap, int) or self.n_bootstrap < 2:
            raise ValueError("n_bootstrap must be at least two")
        if not isinstance(self.random_seed, int) or self.random_seed < 0:
            raise ValueError("random_seed must be a nonnegative integer")
        if not np.isfinite(self.smoothing_alpha) or self.smoothing_alpha <= 0:
            raise ValueError("smoothing_alpha must be positive")
        if not np.isfinite(self.min_abs_mfi) or self.min_abs_mfi < 0:
            raise ValueError("min_abs_mfi must be nonnegative")
        for field in ("alpha_gain", "ci_level", "parity_strength", "min_sign_stability"):
            if not 0 < getattr(self, field) < 1:
                raise ValueError(f"{field} must be in (0,1)")


def pairwise_only_probabilities():
    """A true three-variable Ising/log-linear model, with no triple term."""
    x = state_space(3).astype(float)
    return softmax(.35 * x[:, 0] - .2 * x[:, 1] + .1 * x[:, 2]
                   + .8 * x[:, 0] * x[:, 1] - .5 * x[:, 0] * x[:, 2]
                   + .45 * x[:, 1] * x[:, 2])


def synthetic_cases(parity_strength=.45):
    """Known distributions, without any data-driven parameter choice."""
    if not 0 < parity_strength < 1:
        raise ValueError("parity_strength must be in (0,1)")
    triple = (1 + parity_strength * contrast_signs(3)) / 8
    return {
        "pairwise_only": {"probabilities": pairwise_only_probabilities(),
                          "genes": ["A", "B", "C"], "expected_gain_rejection": False,
                          "construction": "1-way and all 2-way Ising terms; no 3-way term"},
        "pure_three_way": {"probabilities": triple, "genes": ["A", "B", "C"],
                           "expected_gain_rejection": True,
                           "construction": "pure parity; all pairwise margins independent; useful extension"},
        "redundant_extension": {"probabilities": np.repeat(triple / 2, 2),
                                "genes": ["A", "B", "C", "D"], "expected_gain_rejection": False,
                                "construction": "genuine ABC times independent Bernoulli(0.5) D; no 4-way term"},
        "pure_four_way": {"probabilities": (1 + parity_strength * contrast_signs(4)) / 16,
                          "genes": ["A", "B", "C", "D"], "expected_gain_rejection": True,
                          "construction": "pure 4-way parity; all proper marginals independent; exploratory"},
    }


def integer_table(probabilities, total):
    """Deterministic largest-remainder allocation, only for named sanity cases."""
    expected = np.asarray(probabilities) * total
    counts = np.floor(expected).astype(np.int64)
    remainder = int(total - counts.sum())
    rank = np.argsort(-(expected - counts), kind="stable")
    counts[rank[:remainder]] += 1
    return counts


def _seed(root_seed, *parts):
    payload = json.dumps([root_seed, *parts], separators=(",", ":")).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _binomial_interval(successes, trials, ci_level=.95):
    tail = (1 - ci_level) / 2
    low = float(beta.ppf(tail, successes, trials - successes + 1)) if successes else 0.0
    high = float(beta.ppf(1 - tail, successes + 1, trials - successes)) if successes < trials else 1.0
    return {"rejections": successes, "repetitions": trials, "rate": successes / trials,
            "ci_low": low, "ci_high": high, "ci_level": ci_level,
            "ci_method": "Clopper_Pearson_exact_binomial"}


def _effective_config(config):
    if config is None:
        config = ScalableConfig()
    if isinstance(config, ScalableConfig):
        return StatisticalBenchmarkConfig(
            random_seed=config.random_seed, smoothing_alpha=config.smoothing_alpha,
            n_null_simulations=config.n_null_simulations, n_bootstrap=config.n_bootstrap,
            alpha_gain=config.alpha_gain, ci_level=config.ci_level,
            min_abs_mfi=config.min_abs_mfi, min_sign_stability=config.min_sign_stability), config.to_dict()
    if isinstance(config, StatisticalBenchmarkConfig):
        return config, None
    if isinstance(config, dict):
        return StatisticalBenchmarkConfig(**config), None
    raise TypeError("config must be ScalableConfig, StatisticalBenchmarkConfig, mapping, or None")


def _without_arrays(record):
    return {key: value for key, value in record.items() if not isinstance(value, np.ndarray)}


def run_statistical_benchmark(output_dir, config=None):
    """Freeze then run; return a JSON-serializable summary and never overwrite."""
    effective, source_config = _effective_config(config)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError("choose an empty benchmark output directory; prior results are immutable")
    started = time.perf_counter()
    plan = {"benchmark": "v03_statistical_known_candidate_audit", "run_role": "synthetic_only",
            "config": asdict(effective), "source_pipeline_config": source_config,
            "configuration_note": "statistical tests are forced on even if source pipeline ablations disable them",
            "case_order": ["pairwise_only", "pure_three_way", "redundant_extension", "pure_four_way"],
            "bootstrap_cases": ["pure_three_way", "redundant_extension"],
            "case_sampling": "deterministic_largest_remainder; random null draws audited separately",
            "null_repetition_sampling": "independent_multinomial_from_fixed_pairwise_only_true_distribution",
            "test_unit": "one_predeclared_gene_set_per_repetition",
            "seed_derivation": "sha256([root_seed,phase,case_or_repetition]) first 8 bytes big endian",
            "parameter_adaptation": False,
            "limitations": [f"{effective.null_repetitions} null repetitions give a finite-width false-positive-rate confidence interval",
                            "known-candidate statistics do not measure candidate search recall",
                            "no real NT cells or cross-fold biological conclusions",
                            "four-way calibration remains exploratory"]}
    plan["config_hash"] = digest(plan["config"])
    filenames = ("synthetic.py", "estimator.py", "estimability.py", "mfi.py", "gain.py",
                 "lower_order_null.py", "bootstrap.py", "config.py")
    plan["code_hashes"] = {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                            for name in filenames}
    plan["software_versions"] = software_versions()
    # Freeze before generating tables or inspecting any result.
    (output / "config_frozen.yaml").write_text(yaml.safe_dump(clean(plan), sort_keys=True, allow_unicode=True))
    write_json(output / "run_manifest.json", {**plan, "status": "started"})
    case_rows = []
    try:
        for name, case in synthetic_cases(effective.parity_strength).items():
            directory = output / "cases" / name
            directory.mkdir(parents=True)
            counts = integer_table(case["probabilities"], effective.case_sample_size)
            assessment = assess_estimability(counts)
            gain = HigherOrderGainEvaluator(effective.smoothing_alpha).evaluate(counts)
            calibration = GainNullCalibration(n_simulations=effective.n_null_simulations,
                alpha=effective.smoothing_alpha, seed=_seed(effective.random_seed, "case_null", name)).calibrate(counts)
            conditional = conditional_gain_test(counts, effective.smoothing_alpha)
            np.savez_compressed(directory / "null_calibration.npz", null_gain=calibration["null_gain"],
                                null_mfi=calibration["null_mfi"])
            np.savez_compressed(directory / "conditional_null.npz", null_gain=conditional["null_gain"],
                                null_mfi=conditional["null_mfi"], null_weights=conditional["null_weights"],
                                offsets=conditional["offsets"], tail=conditional["tail"])
            case_document = {"case": name, **case, "counts": counts, "estimability": assessment,
                             "true_distribution_mfi": mfi_from_probabilities(case["probabilities"]),
                             "gain": gain, "calibration": _without_arrays(calibration),
                             "conditional_test": _without_arrays(conditional)}
            p_gain = calibration["p_gain"]
            rejection = p_gain is not None and p_gain <= effective.alpha_gain
            expected = case["expected_gain_rejection"]
            mfi_behavior = (abs(gain["mfi"]) >= effective.min_abs_mfi) == expected
            row = {"case": name, "order": len(case["genes"]), "n_cells": int(counts.sum()),
                   "mfi": gain["mfi"], "set_level_gain": gain["set_level_gain"],
                   "p_gain": p_gain, "conditional_p_gain": conditional["p_gain"],
                   "conditional_log_p_gain": conditional["log_p_gain"],
                   "mc_standard_error": calibration["mc_standard_error"],
                   "p_resolution": calibration["p_resolution"], "fit_failures": calibration["fit_failures"],
                   "expected_gain_rejection": expected, "gain_rejected": rejection,
                   "mfi_behavior_met": bool(mfi_behavior),
                   "expectation_met": bool(calibration["status"] == "complete" and rejection == expected and mfi_behavior),
                   "bootstrap_performed": name in plan["bootstrap_cases"],
                   "formal_status": "exploratory" if len(case["genes"]) == 4 else "synthetic"}
            if name in plan["bootstrap_cases"]:
                boot = bootstrap_gene_set(counts, n_bootstrap=effective.n_bootstrap,
                    alpha=effective.smoothing_alpha, seed=_seed(effective.random_seed, "case_bootstrap", name),
                    ci_level=effective.ci_level)
                np.savez_compressed(directory / "bootstrap.npz", **boot["arrays"])
                write_json(directory / "bootstrap_summary.json", {key: value for key, value in boot.items() if key != "arrays"})
                case_document["bootstrap_summary"] = boot["summary"]
                row["bootstrap_fit_failures"] = boot["fit_failures"]
                row["bootstrap_mfi_ci_low"] = boot["summary"]["mfi"]["ci_low"]
                row["bootstrap_mfi_ci_high"] = boot["summary"]["mfi"]["ci_high"]
                row["bootstrap_mfi_sign_stability"] = boot["summary"]["mfi"]["sign_stability"]
                mfi_summary = boot["summary"]["mfi"]
                if name == "pure_three_way":
                    boot_behavior = (mfi_summary["sign_stability"] >= effective.min_sign_stability
                                     and (mfi_summary["ci_low"] > 0 or mfi_summary["ci_high"] < 0))
                else:
                    boot_behavior = mfi_summary["ci_low"] <= 0 <= mfi_summary["ci_high"]
                row["bootstrap_behavior_met"] = bool(boot_behavior)
                # A nonnegative KL CI is never a directional significance gate.
                row["expectation_met"] &= boot["fit_failures"] == 0 and boot_behavior
            write_json(directory / "statistics.json", case_document)
            write_json(directory / "counts.json", {"genes": case["genes"], "counts": counts,
                                                     "truth_probabilities": case["probabilities"]})
            case_rows.append(row)
        write_csv(output / "case_summary.csv", case_rows)

        repetitions = []
        null_probability = pairwise_only_probabilities()
        directory = output / "null_repetitions"
        directory.mkdir()
        for repeat in range(effective.null_repetitions):
            sample_seed = _seed(effective.random_seed, "null_sample", repeat)
            simulation_seed = _seed(effective.random_seed, "null_calibration", repeat)
            counts = np.random.default_rng(sample_seed).multinomial(effective.null_sample_size, null_probability)
            gain = HigherOrderGainEvaluator(effective.smoothing_alpha).evaluate(counts)
            calibration = GainNullCalibration(n_simulations=effective.n_null_simulations,
                alpha=effective.smoothing_alpha, seed=simulation_seed).calibrate(counts)
            conditional = conditional_gain_test(counts, effective.smoothing_alpha)
            np.savez_compressed(directory / f"replicate_{repeat:03}.npz", counts=counts,
                                null_gain=calibration["null_gain"], null_mfi=calibration["null_mfi"])
            repetitions.append({"repetition": repeat, "sample_seed": sample_seed,
                "simulation_seed": simulation_seed, "counts": counts, "n_cells": effective.null_sample_size,
                "mfi": gain["mfi"], "set_level_gain": gain["set_level_gain"],
                "p_gain": calibration["p_gain"], "conditional_p_gain": conditional["p_gain"],
                "conditional_log_p_gain": conditional["log_p_gain"],
                "fit_failures": calibration["fit_failures"], "status": calibration["status"],
                "mc_standard_error": calibration["mc_standard_error"], "p_resolution": calibration["p_resolution"],
                "parametric_rejected": calibration["p_gain"] is not None and calibration["p_gain"] <= effective.alpha_gain,
                "conditional_rejected": conditional["p_gain"] <= effective.alpha_gain})
        write_csv(output / "null_repetitions.csv", repetitions)
        failures = sum(row["status"] != "complete" for row in repetitions)
        fpr = {"nominal_alpha": effective.alpha_gain, "null": "fixed_true_pairwise_only_Ising",
               "parametric": (_binomial_interval(sum(row["parametric_rejected"] for row in repetitions),
                                                  effective.null_repetitions, effective.ci_level) if not failures else None),
               "conditional": _binomial_interval(sum(row["conditional_rejected"] for row in repetitions),
                                                   effective.null_repetitions, effective.ci_level),
               "failed_repetitions": failures,
               "interpretation": "finite synthetic calibration audit; not a global-FDR guarantee or proof of calibration"}
        write_json(output / "false_positive_audit.json", fpr)
        summary = {"status": "complete", "run_role": "synthetic_only", "config_hash": plan["config_hash"],
                   "config": asdict(effective), "output_dir": str(output.resolve()), "cases": case_rows,
                   "all_named_case_expectations_met": all(row["expectation_met"] for row in case_rows),
                   "false_positive_audit": fpr, "runtime_seconds": time.perf_counter() - started,
                   "limitations": plan["limitations"]}
        write_json(output / "summary.json", summary)
        lines = ["# v0.3 Statistical Synthetic Benchmark", "", "本报告仅检验预先指定候选的统计计算，不代表 search recovery 或真实 NT 结果。", "",
                 f"冻结配置 `{plan['config_hash']}`；seed={effective.random_seed}；null draws={effective.n_null_simulations}；bootstrap={effective.n_bootstrap}。", "",
                 "| Case | MFI | KL gain | Parametric p | Conditional p | Expected behavior met |",
                 "|---|---:|---:|---:|---:|---|"]
        for row in case_rows:
            conditional_display = f"{row['conditional_p_gain']:.5g}" if row['conditional_p_gain'] else "<1e-308"
            lines.append(f"| {row['case']} | {row['mfi']:.5g} | {row['set_level_gain']:.5g} | {row['p_gain']} | {conditional_display} | {row['expectation_met']} |")
        lines += ["", f"Pairwise-only null 重复 {effective.null_repetitions} 次，每次 n={effective.null_sample_size}：", ""]
        for key in ("parametric", "conditional"):
            result = fpr[key]
            if result is not None:
                lines.append(f"- {key}: {result['rejections']}/{result['repetitions']} 拒绝，FPR={result['rate']:.3f}，{effective.ci_level:.0%} Clopper–Pearson CI=[{result['ci_low']:.3f}, {result['ci_high']:.3f}]。")
        lines += ["", "此样本量的假阳性率区间较宽，不能据此声称总体 FDR 受控。MFI、KL 与各状态 residual 关联，不能视为独立证据。四阶仍是 exploratory。", "",
                  "极小 conditional p 若发生浮点下溢，表中显示 <1e-308；CSV/JSON 保留 log_p_gain，不能把数值下溢解释为数学概率为零。", "",
                  "完整 counts、拟合模型、各状态 gain、bootstrap 与 null distributions 保存在 cases/ 和 null_repetitions/；没有按结果重新选择参数。", ""]
        (output / "STATISTICAL_REPORT.md").write_text("\n".join(lines))
        write_json(output / "run_manifest.json", {**plan, "status": "complete", "runtime_seconds": summary["runtime_seconds"],
                                                  "all_named_case_expectations_met": summary["all_named_case_expectations_met"]})
        return clean(summary)
    except Exception as error:
        write_json(output / "run_manifest.json", {**plan, "status": "failed", "error": str(error),
                                                  "runtime_seconds": time.perf_counter() - started})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    summary = run_statistical_benchmark(args.output_dir)
    print(json.dumps({"status": summary["status"], "all_named_case_expectations_met": summary["all_named_case_expectations_met"],
                      "runtime_seconds": summary["runtime_seconds"], "output_dir": summary["output_dir"]}, indent=2))


if __name__ == "__main__":
    main()
