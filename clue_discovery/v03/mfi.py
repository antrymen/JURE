"""The v0.2 marginal log contrast, vectorized over complete binary tables."""
import numpy as np
from .estimator import smoothed_probabilities, state_space


def contrast_signs(order):
    states = state_space(order)
    return np.where((order - states.sum(axis=1).astype(int)) % 2 == 0, 1.0, -1.0)


def mfi_from_probabilities(probabilities):
    p = np.asarray(probabilities, dtype=float)
    size = p.shape[-1] if p.ndim else 0
    if p.ndim not in (1, 2) or size < 4 or size & (size - 1):
        raise ValueError("MFI requires complete tables of order at least two")
    if not np.isfinite(p).all() or (p <= 0).any() or not np.allclose(p.sum(axis=-1), 1):
        raise ValueError("probabilities must be positive and sum to one")
    values = np.log(p) @ contrast_signs(int(np.log2(size)))
    values = np.where(np.abs(values) < 1e-12, 0.0, values)
    return float(values) if values.ndim == 0 else values


def mfi_from_counts(counts, alpha=0.5):
    return mfi_from_probabilities(smoothed_probabilities(counts, alpha))


mfi_from_counts_matrix = mfi_from_counts
