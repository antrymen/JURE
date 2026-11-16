"""Bounded binary parity fingerprints: data-aware triplet suggestions, not tests.

On discovery-cell subsets, match XOR(A,B) to C or its complement. No pairwise
edge, significant parent, truth tuple, or opposite-fold input is needed. This
heuristic favors strong parity-like signals; it does not guarantee arbitrary
higher-order coverage. Marginal bias can generate collisions without genuine
interaction; only the unchanged full-table statistical pipeline qualifies them.
"""
import hashlib
import math
import time

import numpy as np

from ..v03.artifacts import enforce_memory_budget
from ..v03.candidate import Candidate
from ..v03.evaluation import stage_seed


def _mix(values, seed):
    """Vectorized deterministic uint64 priorities; wraparound is intentional."""
    x = np.asarray(values, dtype=np.uint64) ^ np.uint64(seed)
    with np.errstate(over='ignore'):
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xbf58476d1ce4e5b9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94d049bb133111eb)
    return x ^ (x >> np.uint64(31))


def _retain(ids, cap, seed):
    if len(ids) <= cap:
        return ids
    # Bottom-hash sampling avoids retaining only early gene names/pair blocks.
    positions = np.argpartition(_mix(ids, seed), cap-1)[:cap]
    return ids[positions]


def _band_hits(codes, *, n_genes, config, seed, pair_i, pair_j):
    bins = 1 << config.fingerprint_bits
    bucket_cap = config.fingerprint_bucket_cap
    table = np.full((bins, bucket_cap), -1, dtype=np.int32)
    sizes = np.zeros(bins, dtype=np.int32)
    # Fixed random priorities within buckets, rather than gene-name truncation.
    order = np.argsort(_mix(np.arange(n_genes, dtype=np.uint64), seed), kind='stable')
    for gene in order:
        code = codes[gene]
        if sizes[code] < bucket_cap:
            table[code, sizes[code]] = gene
        sizes[code] += 1
    width = min(bucket_cap, int(sizes.max(initial=0)))
    table = table[:, :width]
    hits = np.empty(0, dtype=np.uint64)
    observed = 0
    for start in range(0, len(pair_i), config.fingerprint_pair_block):
        i = pair_i[start:start+config.fingerprint_pair_block]
        j = pair_j[start:start+config.fingerprint_pair_block]
        query = np.bitwise_xor(codes[i], codes[j])
        for complement in (0, bins-1):
            matches = table[np.bitwise_xor(query, complement)]
            # i < j < k gives each triple at most one collision per band.
            row, col = np.nonzero(matches > j[:, None])
            k = matches[row, col]
            ids = ((i[row].astype(np.uint64)*n_genes + j[row])*n_genes + k).astype(np.uint64)
            observed += len(ids)
            if len(ids):
                hits = _retain(np.concatenate((hits, ids)), config.fingerprint_hits_per_band, seed)
    return hits, dict(observed_collisions_after_bucket_cap=observed,
        retained_collisions=len(hits), collision_budget_truncated=observed > len(hits),
        bucket_entries_dropped=int(np.maximum(sizes-bucket_cap, 0).sum()),
        largest_bucket=int(sizes.max(initial=0)))


def screen_triplets(binary, genes, config, *, fold, quota=None):
    started = time.monotonic()
    matrix = np.asarray(binary)
    genes = tuple(map(str, genes))
    if matrix.ndim != 2 or matrix.shape[1] != len(genes) or len(set(genes)) != len(genes):
        raise ValueError('binary matrix columns must match unique gene names')
    if not np.isin(matrix, [0, 1]).all():
        raise ValueError('fingerprints require binary detection states')
    if matrix.shape[0] < config.fingerprint_bits:
        raise ValueError('fewer discovery cells than fingerprint bits')
    if len(genes) > 1000:
        raise ValueError('fingerprint implementation supports at most 1000 genes')
    # Canonical column ownership makes input column permutations reproducible.
    permutation = np.argsort(genes)
    genes = tuple(genes[i] for i in permutation)
    matrix = np.asarray(matrix[:, permutation], dtype=np.uint8)
    n, g = matrix.shape
    quota = config.fingerprint_quota if quota is None else quota
    if isinstance(quota, bool) or not isinstance(quota, int) or quota < 0:
        raise ValueError('quota must be a nonnegative integer')
    seed = stage_seed(config, fold, (), 'triplet_fingerprint')
    audit = dict(method='binary_parity_fingerprint', fold=fold, seed=seed,
        input_genes=g, input_cells=n, candidate_quota=quota,
        truth_used=False, opposite_fold_used=False, global_triplet_enumeration=False,
        complete_triplet_coverage=False, score_is_significance_test=False,
        full_triplet_universe=math.comb(g, 3) if g >= 3 else 0,
        collision_storage_limit_entries=config.fingerprint_bands*config.fingerprint_hits_per_band,
        source_budget_policy='fixed_reserved_quota_no_adaptive_refill',
        heuristic_scope='strong_binary_parity_like_patterns; weak_or_biased_signals_may_be_missed')
    if g < 3 or quota == 0:
        return (), dict(audit, status='disabled_or_empty', budget_exhausted=False,
                        screened_records=[], bands=[], candidates_proposed=0)
    rng = np.random.default_rng(seed)
    pair_i, pair_j = np.triu_indices(g, 1)
    pair_i, pair_j = pair_i.astype(np.int32), pair_j.astype(np.int32)
    bands, retained = [], []
    bit_weights = (1 << np.arange(config.fingerprint_bits)).astype(np.uint32)
    for band in range(config.fingerprint_bands):
        enforce_memory_budget(config)
        cells = rng.choice(n, config.fingerprint_bits, replace=False)
        codes = matrix[cells].T @ bit_weights
        band_seed = int(rng.integers(0, np.iinfo(np.uint64).max, dtype=np.uint64))
        hits, details = _band_hits(codes, n_genes=g, config=config, seed=band_seed,
                                  pair_i=pair_i, pair_j=pair_j)
        retained.append(hits)
        bands.append(dict(band=band, discovery_row_indices=cells.tolist(),
                          bucket_and_reservoir_seed=band_seed, **details))
    pooled = np.concatenate(retained)
    del retained
    ids, counts = np.unique(pooled, return_counts=True)
    del pooled
    unique_count = len(ids)
    enforce_memory_budget(config)
    # Rank by repeated collisions, then a seeded hash, before full-cell scoring.
    rank = np.lexsort((_mix(ids, seed), -counts))[:config.fingerprint_score_candidates]
    ids, counts = ids[rank], counts[rank]
    triples = np.column_stack((ids//(g*g), (ids//g) % g, ids % g)).astype(np.int32)
    means = matrix.mean(axis=0)
    variance = means*(1-means)
    scores = np.empty(len(triples), dtype=np.float64)
    # Only the bounded shortlist is scored across cells; no G^3 tensor is built.
    for start in range(0, len(triples), 64):
        indices = triples[start:start+64]
        sums = np.zeros(len(indices))
        for row in range(0, n, 1024):
            values = matrix[row:row+1024, indices].astype(np.float64)-means[indices]
            sums += np.prod(values, axis=2).sum(axis=0)
        denom = np.sqrt(np.prod(variance[indices], axis=1))
        scores[start:start+len(indices)] = np.divide(np.abs(sums/n), denom,
            out=np.zeros_like(sums), where=denom > 0)
    final_rank = np.lexsort((_mix(ids, seed), -counts, -scores))
    selected = set(final_rank[:quota].tolist())
    candidates, records = [], []
    for priority, index in enumerate(final_rank, 1):
        names = tuple(genes[i] for i in triples[index])
        candidate = Candidate(names, fold)
        provenance = dict(fingerprint_collision_bands=int(counts[index]),
            fingerprint_score=float(scores[index]), fingerprint_score_kind='abs_standardized_third_central_moment',
            fingerprint_rank=priority, seed=seed, fit_population='discovery_fold_only',
            requires_pairwise_parent=False, score_is_significance_test=False)
        records.append(dict(candidate_id=candidate.candidate_id, genes=names,
            selected=index in selected, **provenance))
        if index in selected:
            candidate.add_provenance('higher_order_fingerprint', **provenance)
            candidates.append(candidate)
    exhausted = (unique_count > config.fingerprint_score_candidates or len(ids) > quota
        or any(b['bucket_entries_dropped'] or b['collision_budget_truncated'] for b in bands))
    audit.update(status='budget_exhausted' if exhausted else 'complete', budget_exhausted=exhausted,
        pairs_queried_per_band=len(pair_i), bands=bands, observed_unique_collisions=unique_count,
        unique_count_scope='after_bucket_and_band_caps_not_full_collision_universe',
        score_budget_pruned=max(0, unique_count-config.fingerprint_score_candidates),
        candidates_scored=len(ids), candidates_proposed=len(candidates),
        candidate_budget_pruned=max(0, len(ids)-quota), screened_records=records,
        runtime_seconds=time.monotonic()-started)
    return tuple(candidates), audit
