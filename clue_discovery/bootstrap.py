"""Multinomial joint-table resampling is exactly cell bootstrap for these statistics."""
import numpy as np
from .mfi import joint_state_counts, mfi_from_counts, state_space


def summarize_distribution(samples, original, ci_level=0.95):
    values = np.asarray(samples, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
        raise ValueError("samples must be finite and nonempty")
    if not np.isfinite(original) or not 0 < ci_level < 1:
        raise ValueError("invalid original or ci_level")
    lo, hi = np.quantile(values, [(1 - ci_level) / 2, (1 + ci_level) / 2])
    # Original zero provides no direction; never call it stable.
    stability = float(np.mean(np.sign(values) == np.sign(original))) if original != 0 else 0.0
    return {"median": float(np.median(values)), "ci_low": float(lo), "ci_high": float(hi),
            "sign_stability": stability}


def bootstrap_pattern(control, perturb, pattern, config, rng=None):
    rng = np.random.default_rng(config.random_seed) if rng is None else rng
    states = state_space(pattern.order)
    target = int(np.flatnonzero(np.all(states == pattern.states, axis=1))[0])
    metrics, original = {}, {}
    for name, matrix in (("control", control), ("perturb", perturb)):
        counts = joint_state_counts(matrix, pattern.genes)
        n = int(counts.sum())
        draws = rng.multinomial(n, counts / n, size=config.n_bootstrap)
        metrics[f"mfi_{name}"] = np.array([mfi_from_counts(c, config.smoothing_alpha).value for c in draws])
        original[f"mfi_{name}"] = mfi_from_counts(counts, config.smoothing_alpha).value
        marginals = draws @ states / n
        expected = n * np.prod(np.where(pattern.states, marginals, 1 - marginals), axis=1)
        metrics[f"log2_enrichment_{name}"] = np.log2((draws[:, target] + config.epsilon) / (expected + config.epsilon))
        original_marginals = counts @ states / n
        original_expected = n * np.prod(np.where(pattern.states, original_marginals, 1 - original_marginals))
        original[f"log2_enrichment_{name}"] = float(np.log2((counts[target] + config.epsilon) / (original_expected + config.epsilon)))
        metrics[f"frequency_{name}"] = draws[:, target] / n
        original[f"frequency_{name}"] = counts[target] / n
    for key, left, right in (("delta", "frequency_perturb", "frequency_control"),
                              ("mfi_difference", "mfi_perturb", "mfi_control")):
        metrics[key] = metrics[left] - metrics[right]
        original[key] = original[left] - original[right]
    output = {"bootstrap_distributions": {k: v.tolist() for k, v in metrics.items()},
              "bootstrap_performed": True}
    for key in ("delta", "mfi_control", "mfi_perturb", "mfi_difference",
                "log2_enrichment_control", "log2_enrichment_perturb"):
        for metric, value in summarize_distribution(metrics[key], original[key], config.ci_level).items():
            output[f"{key}_sign_stability" if metric == "sign_stability" else f"bootstrap_{key}_{metric}"] = value
    return output


def higher_order_evidence(row, config):
    # Null enrichment alone cannot distinguish a pairwise effect from a 3-way effect.
    return any(abs(row[f"mfi_{name}"]) >= config.min_abs_mfi
               and row[f"q_value_null_{name}"] <= config.alpha_null
               and row[f"mfi_{name}_sign_stability"] >= config.min_sign_stability
               and (row[f"bootstrap_mfi_{name}_ci_low"] > 0
                    or row[f"bootstrap_mfi_{name}_ci_high"] < 0)
               for name in ("control", "perturb"))
