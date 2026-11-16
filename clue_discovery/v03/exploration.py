"""Fixed-budget uniform sampling of gene combinations without enumeration."""
from __future__ import annotations

import hashlib
import json
import math
import random

from .candidate import Candidate


def unrank_combination(rank: int, n: int, k: int) -> tuple[int, ...]:
    """Lexicographic combinatorial unranking in O(k log n), using integer ranks."""
    if k < 0 or n < k or rank < 0 or rank >= math.comb(n, k):
        raise ValueError('invalid combination rank')
    answer, start = [], 0
    for position in range(k):
        remaining = k-position
        total = math.comb(n-start, remaining)
        lo, hi = start, n-remaining
        # Number of combinations skipped before choosing x is monotone in x.
        while lo < hi:
            mid = (lo+hi+1)//2
            skipped = total-math.comb(n-mid, remaining)
            if skipped <= rank:
                lo = mid
            else:
                hi = mid-1
        rank -= total-math.comb(n-lo, remaining)
        answer.append(lo)
        start = lo+1
    return tuple(answer)


def sample_exploration(genes, order, *, n_candidates, random_seed, proposal_round=0,
                       fold='A') -> tuple[tuple[Candidate, ...], dict]:
    """A fixed simple random sample of k-subsets; never resample for positives.

    sampling_probability is the unconditional inclusion probability within this
    prespecified exploration draw, not total hybrid-search inclusion probability.
    """
    genes = tuple(sorted(map(str, genes)))
    if len(set(genes)) != len(genes):
        raise ValueError('gene names must be unique')
    for value, name in ((order, 'order'), (n_candidates, 'n_candidates'),
                        (random_seed, 'random_seed'), (proposal_round, 'proposal_round')):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f'{name} must be a nonnegative integer')
    if order < 2:
        raise ValueError('exploration requires order >=2')
    universe = math.comb(len(genes), order) if order <= len(genes) else 0
    n_sample = min(n_candidates, universe)
    seed_payload = json.dumps([random_seed, str(fold), order, proposal_round, 'exploration'], separators=(',', ':'))
    effective_seed = int.from_bytes(hashlib.sha256(seed_payload.encode()).digest()[:8], 'big')
    ranks = sorted(random.Random(effective_seed).sample(range(universe), n_sample))
    probability = n_sample/universe if universe else 0.
    candidates = []
    for rank in ranks:
        candidate = Candidate(tuple(genes[i] for i in unrank_combination(rank, len(genes), order)), str(fold))
        candidate.add_provenance('exploration', random_seed=random_seed, effective_seed=effective_seed,
            proposal_round=proposal_round, sampling_probability=probability,
            inclusion_probability=probability, combination_rank=rank,
            sampling_rule='uniform_without_replacement_combinatorial_rank',
            inclusion_probability_scope='prespecified_exploration_draw',
            n_sample=n_sample, universe_size=universe)
        candidates.append(candidate)
    return tuple(candidates), {'order': order, 'random_seed': random_seed,
        'effective_seed': effective_seed, 'proposal_round': proposal_round,
        'sampling_rule': 'uniform_without_replacement_combinatorial_rank',
        'requested': n_candidates, 'n_sample': n_sample, 'universe_size': universe,
        'inclusion_probability': probability, 'sampling_probability': probability,
        'positive_dependent_resampling': False}
