"""Separate probability, pattern gain, distribution gain, and null calibration.

MFI and KL are different summaries of the same one-dimensional departure in a
complete binary k-table: they are not independent evidence. No global FDR is
claimed by these per-candidate tests, especially after adaptive proposal.
"""
import numpy as np
from scipy.special import gammaln, logsumexp
from .estimator import validate_counts, smoothed_probabilities
from .mfi import contrast_signs, mfi_from_probabilities
from .lower_order_null import LowerOrderNullModel


class DistributionGainStatistic:
    @staticmethod
    def evaluate(observed_probability, expected_probability):
        p = np.asarray(observed_probability, dtype=float)
        q = np.asarray(expected_probability, dtype=float)
        if p.shape != q.shape or p.ndim not in (1, 2) or not np.isfinite(p).all() or not np.isfinite(q).all():
            raise ValueError("observed and expected probabilities must have matching finite tables")
        if (p <= 0).any() or (q <= 0).any() or not np.allclose(p.sum(axis=-1), 1) or not np.allclose(q.sum(axis=-1), 1):
            raise ValueError("gain requires positive normalized probabilities")
        result = (p * np.log(p / q)).sum(axis=-1)
        if (result < -1e-10).any():
            raise ArithmeticError("KL divergence was unexpectedly negative")
        result = np.maximum(result, 0.0)
        return float(result) if result.ndim == 0 else result


class HigherOrderGainEvaluator:
    def __init__(self, alpha=0.5, *, null_model=None, epsilon=1e-12):
        if not np.isfinite(epsilon) or epsilon <= 0:
            raise ValueError("epsilon must be positive")
        self.alpha = alpha
        self.null_model = null_model or LowerOrderNullModel()
        self.epsilon = epsilon

    def evaluate(self, counts):
        counts = validate_counts(counts)
        p = smoothed_probabilities(counts, self.alpha)
        fit = self.null_model.fit(p)
        if not fit.success:
            raise ArithmeticError("lower-order maximum entropy fit did not converge")
        q = fit.probabilities
        absolute = p - q
        ratio = (p + self.epsilon) / (q + self.epsilon)
        kl = DistributionGainStatistic.evaluate(p, q)
        return {"order": int(np.log2(len(counts))), "total_cells": int(counts.sum()),
                "counts": counts.astype(np.int64), "raw_frequency": counts / counts.sum(),
                "observed_probability": p, "lower_order_expected_probability": q,
                "probability_space": "Dirichlet_smoothed_observed_and_null_same_marginals",
                "smoothing_alpha": self.alpha, "pattern_absolute_gain": absolute,
                "relative_enrichment": ratio, "log_enrichment": np.log(ratio),
                "set_level_gain": kl, "gain_statistic": kl, "gain_statistic_name": "KL_nats",
                "deviance": float(2 * counts.sum() * kl),
                "deviance_definition": "2*n_observed*KL(p_smoothed||p_lower); calibrated_by_resampling",
                "null_method": "complete_lower_order_maximum_entropy", "null_parameters": fit.metadata(),
                "null_fit": fit.metadata(), "uncertainty": None,
                "calibration_reference": "not_yet_calibrated", "mfi": mfi_from_probabilities(p)}


class GainNullCalibration:
    """Discovery parametric bootstrap, refitting the null in every null draw.

    p_gain is a Monte Carlo, candidate-level exploratory p value. The fitted
    composite null and any data-dependent candidate selection preclude an
    automatic assertion of exact/global FDR control.
    """

    def __init__(self, n_simulations=1999, alpha=0.5, seed=0, *, batch_size=256, null_model=None):
        if not isinstance(n_simulations, int) or n_simulations < 1:
            raise ValueError("n_simulations must be positive")
        if not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.n_simulations = n_simulations
        self.alpha = alpha
        self.seed = seed
        self.batch_size = batch_size
        self.null_model = null_model or LowerOrderNullModel()

    def calibrate(self, counts, *, fit=None):
        counts = validate_counts(counts)
        observed = HigherOrderGainEvaluator(self.alpha, null_model=self.null_model).evaluate(counts)
        # A supplied fit is a consistency assertion, not permission to mix spaces.
        if fit is not None:
            q_supplied = fit.probabilities if hasattr(fit, "probabilities") else np.asarray(fit)
            if not np.allclose(q_supplied, observed["lower_order_expected_probability"], atol=1e-10):
                raise ValueError("supplied null must fit these counts in the same smoothing space")
        q = observed["lower_order_expected_probability"]
        n = int(counts.sum())
        rng = np.random.default_rng(self.seed)
        gains = np.full(self.n_simulations, np.nan)
        mfis = np.full(self.n_simulations, np.nan)
        failures = 0
        for start in range(0, self.n_simulations, self.batch_size):
            end = min(start + self.batch_size, self.n_simulations)
            draws = rng.multinomial(n, q, size=end - start)
            p_draw = smoothed_probabilities(draws, self.alpha)
            refit_q, success = self.null_model.fit_batch(p_draw)
            failures += int((~success).sum())
            local_gains = np.full(end - start, np.nan)
            local_gains[success] = DistributionGainStatistic.evaluate(p_draw[success], refit_q[success])
            gains[start:end] = local_gains
            mfis[start:end] = mfi_from_probabilities(p_draw)
        tolerance = 1e-12 * max(1.0, observed["set_level_gain"])
        exceedances = int((gains >= observed["set_level_gain"] - tolerance).sum())
        p_gain = (1 + exceedances) / (1 + self.n_simulations) if failures == 0 else None
        se = float(np.sqrt(p_gain * (1 - p_gain) / (self.n_simulations + 1))) if p_gain is not None else None
        return {"p_gain": p_gain, "q_gain": None, "null_gain": gains, "null_mfi": mfis,
                "observed_gain": observed["set_level_gain"], "n_simulations": self.n_simulations,
                "null_refit_count": self.n_simulations, "fit_failures": failures,
                "status": "complete" if failures == 0 else "null_fit_failed",
                "exceedances": exceedances, "mc_standard_error": se,
                "p_resolution": 1 / (self.n_simulations + 1), "tail_tolerance": tolerance,
                "null_parameters": observed["null_parameters"], "smoothing_alpha": self.alpha,
                "seed": self.seed, "method": "parametric_multinomial_null_with_per_draw_refit",
                "testing_scope": "candidate_level_exploratory_no_global_FDR",
                "calibration_reference": "fitted_complete_lower_order_null"}


def conditional_gain_test(counts, alpha=0.5, *, batch_size=4096, tail_tolerance=1e-12):
    """Exact conditional gain tail, fixing every (k-1)-way observed margin.

    The binary fiber consists of n+t*s for integer t. Under the complete
    lower-order log-linear null its conditional mass is proportional to
    1/prod(cell!), independent of nuisance model parameters. Smoothing is
    applied equally to each fiber table, so all fitted null distributions
    are identical. The test statistic is KL(smoothed table || that null).

    This is valid for a preselected fixed table under multinomial sampling;
    it is not a biological-replicate test or a selection-adjusted p value.
    """
    counts = validate_counts(counts).astype(np.int64)
    if not isinstance(batch_size, int) or batch_size < 1 or not np.isfinite(tail_tolerance) or tail_tolerance < 0:
        raise ValueError("invalid batch size or tail tolerance")
    observed = HigherOrderGainEvaluator(alpha).evaluate(counts)
    order = int(np.log2(len(counts)))
    signs = contrast_signs(order).astype(np.int64)
    lower = -int(counts[signs > 0].min())
    upper = int(counts[signs < 0].min())
    offsets = np.arange(lower, upper + 1, dtype=np.int64)
    log_weights = np.empty(len(offsets))
    gains = np.empty(len(offsets))
    mfis = np.empty(len(offsets))
    q = observed["lower_order_expected_probability"]
    for start in range(0, len(offsets), batch_size):
        end = min(start + batch_size, len(offsets))
        tables = counts[None, :] + offsets[start:end, None] * signs
        log_weights[start:end] = -gammaln(tables + 1).sum(axis=1)
        p = smoothed_probabilities(tables, alpha)
        gains[start:end] = DistributionGainStatistic.evaluate(p, np.broadcast_to(q, p.shape))
        mfis[start:end] = mfi_from_probabilities(p)
    tolerance = tail_tolerance * max(1.0, observed["set_level_gain"])
    tail = gains >= observed["set_level_gain"] - tolerance
    normalizer = logsumexp(log_weights)
    log_p = min(0.0, float(logsumexp(log_weights[tail]) - normalizer))
    return {"p_gain": float(np.exp(log_p)), "log_p_gain": log_p, "q_gain": None,
            "observed_gain": observed["set_level_gain"], "null_gain": gains, "null_mfi": mfis,
            "null_weights": np.exp(log_weights - normalizer), "offsets": offsets,
            "tail": tail, "support_size": len(offsets), "tail_tolerance": tolerance,
            "null_parameters": observed["null_parameters"], "conditioning_marginals": f"all_{order - 1}_way_margins",
            "method": "exact_conditional_complete_lower_order_fiber", "smoothing_alpha": alpha,
            "fit_failures": 0, "status": "complete", "mc_standard_error": None, "p_resolution": None,
            "testing_scope": "fixed_candidate_conditional_no_global_FDR",
            "uncertainty": "exact_conditional_enumeration_no_Monte_Carlo",
            "formal_status": "exploratory" if order == 4 else "implemented"}
