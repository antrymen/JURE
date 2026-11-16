"""Descriptive full-table support checks; thresholds are engineering defaults.

No threshold here is claimed to establish statistical reliability. Simulation
and held-out calibration must establish an appropriate operating regime.
"""
from dataclasses import dataclass
import numpy as np
from .estimator import validate_counts, state_space


@dataclass(frozen=True)
class EstimabilityAssessment:
    good_min_count: int = 20
    poor_max_zero_fraction: float = 0.25
    poor_min_observed_count: int = 3

    def __post_init__(self):
        for field in ("good_min_count", "poor_min_observed_count"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a nonnegative integer")
        if not 0 <= self.poor_max_zero_fraction <= 1:
            raise ValueError("poor_max_zero_fraction must be in [0,1]")

    def assess(self, counts):
        values = validate_counts(counts).astype(np.int64)
        states = state_space(int(np.log2(len(values))))
        positive = values[values > 0]
        zero_fraction = float((values == 0).mean())
        reasons = []
        if zero_fraction > self.poor_max_zero_fraction:
            reasons.append("zero_state_fraction_exceeds_configured_limit")
        if positive.min() < self.poor_min_observed_count:
            reasons.append("min_observed_state_count_below_configured_limit")
        status = "poor" if reasons else ("good" if values.min() >= self.good_min_count else "borderline")
        result = {"status": status, "estimability_status": status,
                  "threshold_status": "engineering_defaults_not_empirically_calibrated",
                  "thresholds": {"good_min_count": self.good_min_count,
                                 "poor_max_zero_fraction": self.poor_max_zero_fraction,
                                 "poor_min_observed_count": self.poor_min_observed_count},
                  "prune": status == "poor", "prune_reasons": reasons,
                  "order": int(np.log2(len(values))), "total_cells": int(values.sum()),
                  "state_counts": {"".join(map(str, state)): int(count) for state, count in zip(states, values)},
                  "min_state_count": int(values.min()), "max_state_count": int(values.max()),
                  "min_observed_state_count": int(positive.min()),
                  "zero_state_count": int((values == 0).sum()), "zero_state_fraction": zero_fraction,
                  "state_table_occupancy": 1 - zero_fraction,
                  "pattern_support": values.tolist()}
        for minimum in (5, 10, 20):
            result[f"states_below_{minimum}"] = int((values < minimum).sum())
            result[f"fraction_states_below_{minimum}"] = float((values < minimum).mean())
        return result

    __call__ = assess


def assess_estimability(counts, *, good_min_count=20, poor_max_zero_fraction=0.25,
                       poor_min_observed_count=3):
    return EstimabilityAssessment(good_min_count, poor_max_zero_fraction,
                                  poor_min_observed_count).assess(counts)
