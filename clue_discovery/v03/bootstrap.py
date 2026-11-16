"""Bounded-memory cell bootstrap, once per shortlisted unique gene set.

All concrete states share the same multinomial draws and fitted low-order
nulls. Set KL has no signed direction; only MFI and pattern residuals do.
"""
import numpy as np
from ..bootstrap import summarize_distribution
from .estimator import validate_counts, smoothed_probabilities
from .mfi import mfi_from_probabilities
from .lower_order_null import LowerOrderNullModel
from .gain import DistributionGainStatistic, HigherOrderGainEvaluator


def bootstrap_gene_set(counts, *, n_bootstrap=1000, alpha=0.5, seed=0, ci_level=0.95,
                       batch_size=256, compute_gain=True, null_model=None):
    counts = validate_counts(counts)
    if not isinstance(n_bootstrap, int) or n_bootstrap < 2:
        raise ValueError("n_bootstrap must be at least two")
    if not isinstance(batch_size, int) or batch_size < 1 or not 0 < ci_level < 1:
        raise ValueError("invalid batch size or ci_level")
    p = smoothed_probabilities(counts, alpha)
    model = null_model or LowerOrderNullModel()
    original_mfi = mfi_from_probabilities(p)
    original = HigherOrderGainEvaluator(alpha, null_model=model).evaluate(counts) if compute_gain else None
    arrays = {"mfi": np.empty(n_bootstrap)}
    if compute_gain:
        arrays.update(set_level_gain=np.full(n_bootstrap, np.nan),
                      pattern_absolute_gain=np.full((n_bootstrap, len(counts)), np.nan))
    rng = np.random.default_rng(seed)
    failures = 0
    for start in range(0, n_bootstrap, batch_size):
        end = min(start + batch_size, n_bootstrap)
        draws = rng.multinomial(int(counts.sum()), counts / counts.sum(), size=end - start)
        p_draw = smoothed_probabilities(draws, alpha)
        arrays["mfi"][start:end] = mfi_from_probabilities(p_draw)
        if compute_gain:
            q_draw, success = model.fit_batch(p_draw)
            failures += int((~success).sum())
            good = np.flatnonzero(success) + start
            arrays["set_level_gain"][good] = DistributionGainStatistic.evaluate(p_draw[success], q_draw[success])
            arrays["pattern_absolute_gain"][good] = p_draw[success] - q_draw[success]
    summary = {"mfi": summarize_distribution(arrays["mfi"], original_mfi, ci_level),
               "set_level_gain": None, "pattern_absolute_gain": []}
    if compute_gain and failures == 0:
        gain_summary = summarize_distribution(arrays["set_level_gain"], original["set_level_gain"], ci_level)
        gain_summary["sign_stability"] = None
        gain_summary["direction_status"] = "not_applicable_KL_is_nonnegative"
        summary["set_level_gain"] = gain_summary
        summary["pattern_absolute_gain"] = [
            summarize_distribution(arrays["pattern_absolute_gain"][:, i], original["pattern_absolute_gain"][i], ci_level)
            for i in range(len(counts))]
    return {"arrays": arrays, "summary": summary, "n_bootstrap": n_bootstrap,
            "fit_failures": failures, "status": "complete" if failures == 0 else "null_fit_failed",
            "seed": seed, "compute_gain": compute_gain, "ci_level": ci_level,
            "smoothing_alpha": alpha, "method": "cell_multinomial_bootstrap_with_null_refit",
            "probability_space": "Dirichlet_smoothed", "null_refit_count": n_bootstrap if compute_gain else 0,
            "unit": "unique_gene_set", "pattern_order": "binary_lexicographic"}
