from dataclasses import dataclass
import numpy as np
from scipy.stats import fisher_exact
from .preprocessing import binary_values


@dataclass(frozen=True)
class PatternFrequency:
    frequency: float
    cell_count: int
    total_cells: int


def pattern_frequency(S, pattern):
    """Arrays must already have columns in pattern.genes order; DataFrames align by name."""
    values = binary_values(S, pattern.genes)
    count = int(np.all(values == pattern.states, axis=1).sum())
    return PatternFrequency(count / len(values), count, len(values))


def benjamini_hochberg(p_values):
    p = np.asarray(p_values, dtype=float)
    if p.ndim != 1 or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("p-values must be finite and in [0, 1]")
    if not p.size:
        return p.copy()
    ix = np.argsort(p, kind="stable")
    adjusted = np.minimum.accumulate((p[ix] * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1]
    result = np.empty_like(p)
    result[ix] = np.minimum(adjusted, 1)
    return result


def pattern_shift(control, perturb, pattern, epsilon=1e-9):
    if not np.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("epsilon must be positive")
    c, p = pattern_frequency(control, pattern), pattern_frequency(perturb, pattern)
    odds, probability = fisher_exact([[p.cell_count, p.total_cells - p.cell_count],
                                     [c.cell_count, c.total_cells - c.cell_count]], alternative="two-sided")
    return {"control_frequency": c.frequency, "perturb_frequency": p.frequency,
            "control_count": c.cell_count, "perturb_count": p.cell_count,
            "control_total_cells": c.total_cells, "perturb_total_cells": p.total_cells,
            "delta_frequency": p.frequency - c.frequency,
            "risk_ratio": (p.frequency + epsilon) / (c.frequency + epsilon),
            "odds_ratio": float(odds), "p_value_shift": float(probability)}
