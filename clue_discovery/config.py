"""All screening thresholds are explicit; no composite clue score."""
from dataclasses import dataclass, asdict
import math


@dataclass(frozen=True)
class DiscoveryConfig:
    threshold: float = 0.0
    input_kind: str = "counts"
    min_detection_rate: float = 0.01
    max_detection_rate: float = 0.99
    max_order: int = 3
    mfi_mode: str = "marginal"
    null_model: str = "independence"
    smoothing_alpha: float = 0.5
    epsilon: float = 0.5  # count-scale enrichment pseudocount
    frequency_epsilon: float = 1e-9
    min_support: int = 20  # max(condition-specific counts)
    min_delta: float = 0.02
    alpha_shift: float = 0.05
    alpha_null: float = 0.05
    min_abs_mfi: float = 0.5
    expansion_p: float = 0.1
    expansion_min_expected: float = 1.0
    allow_support_only: bool = True
    max_candidates: int = 100_000
    n_bootstrap: int = 200
    ci_level: float = 0.95
    min_sign_stability: float = 0.95
    random_seed: int = 42

    def __post_init__(self):
        if self.max_order not in (2, 3):
            raise NotImplementedError("v0.1 supports max_order 2 or 3; order 4 is reserved")
        if self.mfi_mode != "marginal" or self.null_model != "independence":
            raise NotImplementedError("conditional MFI / pairwise_maxent are future interfaces")
        if self.input_kind not in ("counts", "binary", "expression"):
            raise ValueError("input_kind must be counts, binary, or explicitly declared expression")
        for key, value in asdict(self).items():
            if isinstance(value, (float, int)) and not math.isfinite(value):
                raise ValueError(f"{key} must be finite")
        for key in ("min_support", "max_candidates", "n_bootstrap"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{key} must be a positive integer")
        if not isinstance(self.random_seed, int) or self.random_seed < 0:
            raise ValueError("random_seed must be a nonnegative integer")
        for key in ("alpha_shift", "alpha_null", "expansion_p", "ci_level", "min_sign_stability"):
            if not 0 < getattr(self, key) < 1:
                raise ValueError(f"{key} must lie in (0, 1)")
        if not 0 <= self.min_detection_rate < self.max_detection_rate <= 1:
            raise ValueError("invalid detection rate bounds")
        if not 0 <= self.min_delta <= 1:
            raise ValueError("min_delta must lie in [0, 1]")
        if min(self.smoothing_alpha, self.epsilon, self.frequency_epsilon) <= 0:
            raise ValueError("pseudocounts/epsilon must be positive")
        if min(self.min_abs_mfi, self.expansion_min_expected) < 0:
            raise ValueError("effect/expected thresholds must be nonnegative")
