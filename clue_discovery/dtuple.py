import numpy as np
from scipy.stats import binom
from .preprocessing import binary_values
from .statistics import pattern_frequency


def dtuple_deviation(S, pattern, epsilon=0.5, null_model="independence"):
    if null_model != "independence":
        raise NotImplementedError("pairwise_maxent is a future interface")
    if not np.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("epsilon must be positive")
    values = binary_values(S, pattern.genes)
    frequency = pattern_frequency(values, pattern)
    marginals = values.mean(axis=0)
    probability = float(np.prod(np.where(pattern.states, marginals, 1 - marginals)))
    expected = len(values) * probability
    return {"observed_count": frequency.cell_count, "observed_frequency": frequency.frequency,
            "expected_count": expected, "expected_frequency": probability,
            "null_probability": probability,
            "log2_enrichment": float(np.log2((frequency.cell_count + epsilon) / (expected + epsilon))),
            "p_value_null": float(binom.sf(frequency.cell_count - 1, len(values), probability))}
