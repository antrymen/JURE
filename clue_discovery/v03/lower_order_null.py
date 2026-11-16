"""Exact complete (k-1)-order binary maximum-entropy projections.

Fixing every (k-1)-variable margin leaves a one-dimensional fiber, p + t*s,
where s is the alternating parity vector. Entropy is strictly concave on this
fiber. Its unique interior maximum has sum(s*log(q))=0, i.e. no k-way
log-linear term. The monotone equation is solved in batch; this is NOT merely
an independence null for triplets/quads. Inputs must be strictly positive.
"""
from dataclasses import dataclass
import numpy as np
from .mfi import contrast_signs
from .estimator import state_space


@dataclass(frozen=True)
class NullFit:
    probabilities: np.ndarray
    parameters: dict
    max_marginal_error: float
    highest_order_log_contrast: float
    success: bool

    def metadata(self):
        return {"method": "complete_lower_order_maximum_entropy", **self.parameters,
                "max_marginal_error": self.max_marginal_error,
                "highest_order_log_contrast": self.highest_order_log_contrast,
                "success": self.success}


class LowerOrderNullModel:
    """Keep all proper marginals; remove only the highest-order interaction.

    This complete hierarchical model is pairwise for k=3 and includes all
    triple terms for k=4. A k=4 result remains exploratory in v0.3.
    """

    def __init__(self, *, tolerance=1e-9, max_iterations=80):
        if not np.isfinite(tolerance) or tolerance <= 0:
            raise ValueError("tolerance must be positive")
        if not isinstance(max_iterations, int) or max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        self.tolerance = tolerance
        self.max_iterations = max_iterations

    @staticmethod
    def _validate(probabilities):
        p = np.asarray(probabilities, dtype=np.float64)
        if p.ndim not in (1, 2) or p.shape[-1] not in (4, 8, 16):
            raise ValueError("lower-order null supports complete binary tables of orders 2, 3, 4")
        if not np.isfinite(p).all() or (p <= 0).any() or not np.allclose(p.sum(axis=-1), 1, atol=1e-12, rtol=0):
            raise ValueError("probabilities must be positive and sum to one")
        return p

    def fit_batch(self, probabilities):
        p = self._validate(probabilities)
        if p.ndim != 2:
            raise ValueError("fit_batch expects one table per row")
        signs = contrast_signs(int(np.log2(p.shape[1])))
        low = -p[:, signs > 0].min(axis=1)
        high = p[:, signs < 0].min(axis=1)
        half_width = (high - low) / 2
        midpoint_q = p + ((low + high) / 2)[:, None] * signs
        # Parameterize distance from the nearer fiber boundary. Computing a
        # tiny q as p +/- delta otherwise loses many significant digits. The
        # log-distance coordinate also reaches highly skewed solutions fast.
        from_low = (np.log(midpoint_q) @ signs) >= 0
        boundary = np.where(from_low, low, high)
        orientation = np.where(from_low[:, None], signs, -signs)
        base = p + boundary[:, None] * signs
        log_low = np.full(len(p), np.log(np.finfo(float).tiny))
        log_high = np.log(half_width)
        log_distance = log_high.copy()
        active = np.ones(len(p), dtype=bool)
        for _ in range(self.max_iterations):
            distance = np.exp(log_distance)
            q = base + distance[:, None] * orientation
            with np.errstate(divide="ignore", invalid="ignore"):
                value = (np.log(q) * orientation).sum(axis=1)
            active &= np.abs(value) > self.tolerance
            if not active.any():
                break
            log_high = np.where(active & (value > 0), log_distance, log_high)
            log_low = np.where(active & (value <= 0), log_distance, log_low)
            derivative = (distance[:, None] / q).sum(axis=1)
            newton = log_distance - value / derivative
            midpoint = (log_low + log_high) / 2
            next_distance = np.where(np.isfinite(newton) & (newton > log_low) & (newton < log_high), newton, midpoint)
            log_distance = np.where(active, next_distance, log_distance)
        q = base + np.exp(log_distance)[:, None] * orientation
        with np.errstate(divide="ignore", invalid="ignore"):
            contrast = np.log(q) @ signs
        success = np.isfinite(q).all(axis=1) & (q > 0).all(axis=1) & (np.abs(contrast) <= self.tolerance * 2)
        return q, success

    def fit(self, probabilities):
        p = self._validate(probabilities)
        if p.ndim != 1:
            raise ValueError("fit expects one table")
        q, success = self.fit_batch(p[None, :])
        q = q[0]
        order = int(np.log2(len(p)))
        states = state_space(order)
        max_error = 0.0
        for excluded in range(order):
            remaining = [i for i in range(order) if i != excluded]
            codes = states[:, remaining] @ (2 ** np.arange(order - 2, -1, -1))
            difference = np.bincount(codes, weights=p - q, minlength=2 ** (order - 1))
            max_error = max(max_error, float(np.abs(difference).max()))
        contrast = float(np.log(q) @ contrast_signs(order))
        return NullFit(q, {"order": order, "max_interaction_order": order - 1,
                           "preserved_marginals": "all_proper_marginals",
                           "solver": "safeguarded_log_distance_newton_on_binary_parity_fiber",
                           "tolerance": self.tolerance, "max_iterations": self.max_iterations,
                           "formal_status": "exploratory" if order == 4 else "implemented"},
                       max_error, contrast, bool(success[0] and max_error <= self.tolerance))
