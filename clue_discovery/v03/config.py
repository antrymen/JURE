"""Frozen engineering defaults; they are not universal scientific thresholds."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math


@dataclass(frozen=True)
class ScalableConfig:
    run_version: str = 'v03b'
    hvg_pool_size: int = 50
    hvg_method: str = 'raw_count_fano'
    min_detection_rate: float = .01
    max_detection_rate: float = .99
    threshold: float = 0.0
    input_kind: str = 'counts'
    max_order: int = 4
    candidate_mode: str = 'hybrid'
    dependency_top_k: int = 3
    dependency_min_abs_phi: float = .08
    dependency_block_size: int = 128
    exploration_fraction: float = .2
    max_exploration_candidates_per_order: int = 300
    max_exploration_candidates: int = 900
    max_pair_candidates: int = 4000
    max_triplet_candidates: int = 4000
    max_quad_candidates: int = 1000
    max_bootstrap_gene_sets: int = 128
    max_gain_calibration_gene_sets: int = 512
    random_seed: int = 20260927
    estimability_filter: str = 'on'
    good_min_count: int = 10
    poor_max_zero_fraction: float = .125
    poor_min_observed_count: int = 3
    min_support: int = 30
    smoothing_alpha: float = .5
    min_abs_mfi: float = .5
    gain_mode: str = 'on'
    quad_gain_enabled: bool = False
    n_null_simulations: int = 1999
    alpha_gain: float = .05
    gain_qualification: str = 'p_gain_exploratory'
    gain_epsilon: float = 1e-12
    bootstrap: str = 'on'
    n_bootstrap: int = 1000
    ci_level: float = .95
    min_sign_stability: float = .95
    cross_fold_validation: str = 'on'
    validation_gain_method: str = 'exact_conditional'
    primary_requires_good_estimability: bool = True
    primary_requires_dependency_source: bool = True
    max_process_rss_mib: int = 1400
    threshold_source: str = 'frozen_engineering_preset_not_empirically_calibrated'

    def __post_init__(self):
        for name in ('hvg_pool_size', 'dependency_top_k', 'dependency_block_size',
                     'max_pair_candidates', 'max_triplet_candidates', 'max_quad_candidates',
                     'max_bootstrap_gene_sets', 'max_gain_calibration_gene_sets', 'n_bootstrap',
                     'n_null_simulations', 'min_support', 'good_min_count', 'poor_min_observed_count',
                     'max_process_rss_mib'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        for name in ('max_exploration_candidates_per_order', 'max_exploration_candidates', 'random_seed'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f'{name} must be a nonnegative integer')
        if self.hvg_pool_size > 1000 or self.max_order not in (2, 3, 4):
            raise ValueError('v0.3 supports pools up to 1000 and orders 2–4')
        if self.n_bootstrap < 2:
            raise ValueError('n_bootstrap must be at least two')
        if self.candidate_mode not in ('dependency_only', 'exploration_only', 'hybrid'):
            raise ValueError('invalid candidate_mode')
        for name in ('gain_mode', 'estimability_filter', 'bootstrap', 'cross_fold_validation'):
            if getattr(self, name) not in ('on', 'off'):
                raise ValueError(f'{name} must be on or off')
        for name in ('dependency_min_abs_phi', 'exploration_fraction', 'poor_max_zero_fraction'):
            if not math.isfinite(getattr(self, name)) or not 0 <= getattr(self, name) <= 1:
                raise ValueError(f'{name} must be within [0,1]')
        for name in ('alpha_gain', 'ci_level', 'min_sign_stability'):
            if not 0 < getattr(self, name) < 1:
                raise ValueError(f'{name} must be within (0,1)')
        if not 0 <= self.min_detection_rate < self.max_detection_rate <= 1:
            raise ValueError('invalid detection bounds')
        if (not math.isfinite(self.smoothing_alpha) or self.smoothing_alpha <= 0
                or not math.isfinite(self.min_abs_mfi) or self.min_abs_mfi < 0):
            raise ValueError('invalid MFI parameters')
        if not math.isfinite(self.gain_epsilon) or self.gain_epsilon <= 0:
            raise ValueError('gain_epsilon must be positive and finite')
        if self.hvg_method != 'raw_count_fano' or self.gain_qualification != 'p_gain_exploratory':
            raise NotImplementedError('only the documented Fano proxy and exploratory calibrated p gate are implemented')
        if self.validation_gain_method != 'exact_conditional':
            raise NotImplementedError('validation never trains a new parametric null calibration')
        if self.input_kind != 'counts' or self.threshold != 0:
            raise NotImplementedError('v0.3 currently uses raw-count detected/undetected states')

    def to_dict(self):
        return asdict(self)

    @property
    def sha256(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
