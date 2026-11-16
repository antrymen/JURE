"""Empirical joint distributions; the replaceable interface does not train a TN.

Raw frequencies and Dirichlet-smoothed probabilities are deliberately distinct.
State codes are binary lexicographic codes (the first gene is the high bit).
"""
from abc import ABC, abstractmethod
from itertools import product
import numpy as np


def validate_counts(counts, *, allow_batch=False):
    values = np.asarray(counts, dtype=np.float64)
    ndim = (1, 2) if allow_batch else (1,)
    if values.ndim not in ndim or values.shape[-1] < 2:
        raise ValueError("counts must contain a complete binary state table")
    size = values.shape[-1]
    if size & (size - 1) or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("counts must contain finite nonnegative observations in 2^k states")
    if not (values == np.floor(values)).all() or (values.sum(axis=-1) <= 0).any():
        raise ValueError("counts must be integers with positive total")
    return values


def state_space(order):
    if isinstance(order, bool) or not isinstance(order, (int, np.integer)) or not 1 <= order <= 12:
        raise ValueError("order must be an integer from 1 through 12")
    return np.array(list(product((0, 1), repeat=int(order))), dtype=np.uint8)


def smoothed_probabilities(counts, alpha=0.5):
    values = validate_counts(counts, allow_batch=True)
    if not np.isfinite(alpha) or alpha < 0 or (alpha == 0 and (values == 0).any()):
        raise ValueError("alpha must be finite and nonnegative; zero counts need positive smoothing")
    return (values + alpha) / (values.sum(axis=-1, keepdims=True) + values.shape[-1] * alpha)


class JointDistributionEstimator(ABC):
    """Future estimators must preserve these query semantics and uncertainty labels."""

    @abstractmethod
    def fit(self, data=None, *, counts=None, genes=None): ...

    @abstractmethod
    def joint_probability(self, state, *, raw=False): ...

    @abstractmethod
    def marginal(self, axes, *, raw=False): ...

    @abstractmethod
    def conditional_probability(self, state, given, *, raw=False): ...

    @abstractmethod
    def state_table(self): ...

    @abstractmethod
    def uncertainty(self, **kwargs): ...


class EmpiricalJointEstimator(JointDistributionEstimator):
    def __init__(self, alpha=0.5):
        self.alpha = alpha
        self.counts = None

    def fit(self, data=None, *, counts=None, genes=None):
        if data is not None and counts is not None:
            raise ValueError("provide either cells or counts")
        if counts is None:
            values = np.asarray(data)
            if values.ndim == 1:
                counts = values
            elif values.ndim == 2 and values.shape[0] and values.shape[1]:
                if not np.isin(values, [0, 1]).all():
                    raise ValueError("fit cells must be binary; raw-count encoding is external")
                states = state_space(values.shape[1])
                codes = values.astype(np.int64) @ (2 ** np.arange(values.shape[1] - 1, -1, -1))
                counts = np.bincount(codes, minlength=len(states))
            else:
                raise ValueError("fit requires a nonempty cell by binary-variable matrix or counts")
        self.counts = validate_counts(counts).astype(np.int64)
        self.order = int(np.log2(len(self.counts)))
        self.states = state_space(self.order)
        self.genes = tuple(genes) if genes is not None else tuple(range(self.order))
        if len(self.genes) != self.order or len(set(self.genes)) != self.order:
            raise ValueError("genes must uniquely label every variable")
        self.probabilities = smoothed_probabilities(self.counts, self.alpha)
        self.raw_frequencies = self.counts / self.counts.sum()
        return self

    def _ready(self):
        if self.counts is None:
            raise RuntimeError("fit must be called first")

    def _axes(self, axes):
        axes = tuple(axes)
        result = tuple(self.genes.index(x) if x in self.genes else int(x) for x in axes)
        if len(set(result)) != len(result) or any(x < 0 or x >= self.order for x in result):
            raise ValueError("invalid or repeated variable")
        return result

    def joint_probability(self, state, *, raw=False):
        self._ready()
        bits = np.asarray(state)
        if bits.shape != (self.order,) or not np.isin(bits, [0, 1]).all():
            raise ValueError("state must specify all binary variables")
        index = int(bits @ (2 ** np.arange(self.order - 1, -1, -1)))
        return float((self.raw_frequencies if raw else self.probabilities)[index])

    def marginal(self, axes, *, raw=False):
        self._ready()
        axes = self._axes(axes)
        if not axes:
            return np.array([1.0])
        codes = self.states[:, axes] @ (2 ** np.arange(len(axes) - 1, -1, -1))
        return np.bincount(codes, weights=self.raw_frequencies if raw else self.probabilities,
                           minlength=2 ** len(axes))

    def conditional_probability(self, state, given, *, raw=False):
        """P(state mapping | given mapping); keys are gene labels or axis indices."""
        self._ready()
        target = {self._axes([key])[0]: value for key, value in state.items()}
        condition = {self._axes([key])[0]: value for key, value in given.items()}
        if any(x not in (0, 1) for x in [*target.values(), *condition.values()]):
            raise ValueError("conditional states must be binary")
        if any(key in condition and condition[key] != value for key, value in target.items()):
            return 0.0
        p = self.raw_frequencies if raw else self.probabilities
        mask = np.ones(len(self.states), dtype=bool)
        for key, value in condition.items():
            mask &= self.states[:, key] == value
        denominator = p[mask].sum()
        if denominator == 0:
            raise ValueError("conditioning event has zero probability")
        for key, value in target.items():
            mask &= self.states[:, key] == value
        return float(p[mask].sum() / denominator)

    conditional = conditional_probability

    def state_table(self):
        self._ready()
        return [{"state": "".join(map(str, state)), "count": int(count),
                 "raw_frequency": float(raw), "probability": float(probability)}
                for state, count, raw, probability in zip(self.states, self.counts,
                                                         self.raw_frequencies, self.probabilities)]

    def uncertainty(self, *, n_bootstrap=1000, seed=0, ci_level=0.95):
        self._ready()
        if not isinstance(n_bootstrap, int) or n_bootstrap < 2 or not 0 < ci_level < 1:
            raise ValueError("require at least two bootstrap draws and a CI level in (0,1)")
        draws = np.random.default_rng(seed).multinomial(int(self.counts.sum()), self.raw_frequencies,
                                                       size=n_bootstrap)
        distributions = smoothed_probabilities(draws, self.alpha)
        tail = (1 - ci_level) / 2
        return {"method": "cell_multinomial_bootstrap", "n_bootstrap": n_bootstrap,
                "probability_space": "Dirichlet_smoothed", "ci_level": ci_level,
                "ci_low": np.quantile(distributions, tail, axis=0),
                "ci_high": np.quantile(distributions, 1 - tail, axis=0),
                "probabilities": distributions}
