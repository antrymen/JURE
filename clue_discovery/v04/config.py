"""Versioned engineering presets, not empirically calibrated guarantees."""
from dataclasses import dataclass

from ..v03.config import ScalableConfig as V03Config


@dataclass(frozen=True)
class ScalableConfig(V03Config):
    run_version: str = 'v04a'
    triplet_screen: str = 'parity_fingerprint'
    fingerprint_bands: int = 64
    fingerprint_bits: int = 12
    fingerprint_bucket_cap: int = 16
    fingerprint_pair_block: int = 4096
    fingerprint_hits_per_band: int = 100000
    fingerprint_score_candidates: int = 4096
    fingerprint_candidate_budget: int = 1000
    # Provenance is recorded separately; pure-HO discoveries need no pairwise edge.
    primary_requires_dependency_source: bool = False
    bootstrap_priority: str = 'estimability_p_gain_effect_support'

    def __post_init__(self):
        super().__post_init__()
        if self.triplet_screen not in ('parity_fingerprint', 'off'):
            raise ValueError('unsupported triplet_screen')
        if self.bootstrap_priority != 'estimability_p_gain_effect_support':
            raise ValueError('unsupported bootstrap_priority')
        for name in ('fingerprint_bands', 'fingerprint_bits', 'fingerprint_bucket_cap',
                     'fingerprint_pair_block', 'fingerprint_hits_per_band',
                     'fingerprint_score_candidates', 'fingerprint_candidate_budget'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        if not 4 <= self.fingerprint_bits <= 16:
            raise ValueError('fingerprint_bits must be in [4,16]')
        if self.fingerprint_bands > 128 or self.fingerprint_bucket_cap > 32:
            raise ValueError('fingerprint bands/buckets exceed the bounded implementation')
        if self.fingerprint_pair_block > 16384 or self.fingerprint_score_candidates > 16384:
            raise ValueError('fingerprint working block/score budget too large')
        if self.fingerprint_bands * self.fingerprint_hits_per_band > 6400000:
            raise ValueError('fingerprint collision storage exceeds 6.4 million uint64 entries')

    @property
    def fingerprint_quota(self):
        if self.triplet_screen == 'off' or self.candidate_mode != 'hybrid' or self.max_order < 3:
            return 0
        # Reserve at most half the L3 budget; no adaptive refill after outcomes.
        return min(self.fingerprint_candidate_budget, self.max_triplet_candidates // 2)
