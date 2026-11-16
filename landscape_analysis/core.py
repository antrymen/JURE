"""Pure numerical helpers. No model calls, retrieval, or significance claims."""
from __future__ import annotations

import numpy as np
from scipy.cluster.hierarchy import fcluster, leaves_list, linkage
from scipy.spatial.distance import pdist, squareform


def matrix_views(delta, candidate, tested, reason):
    """Keep observed zero, encoded absence, unsupported and untested distinct."""
    delta = np.asarray(delta, dtype=float)
    candidate, tested = np.asarray(candidate, bool), np.asarray(tested, bool)
    reason = np.asarray(reason)
    if not (delta.shape == candidate.shape == tested.shape == reason.shape):
        raise ValueError("matrix dimensions differ")
    if np.any(candidate & (~tested | ~np.isfinite(delta) | (delta == 0))):
        raise ValueError("candidate must be tested, finite, and directional")
    enough = np.isfinite(delta) & (tested | (reason == "effect_below_prespecified_minimum"))
    encoded = np.full_like(delta, np.nan)
    encoded[enough] = 0.0
    encoded[candidate] = delta[candidate]
    status = np.where(tested, "tested_not_qualified", "not_tested:" + reason.astype(str))
    status = np.where(candidate & (delta > 0), "candidate_enrichment", status)
    status = np.where(candidate & (delta < 0), "candidate_depletion", status)
    return dict(observed=delta.copy(), candidate_only=np.where(candidate, delta, np.nan),
                selection_encoded=encoded, candidate_mask=candidate.astype(np.uint8),
                status=status, enough_support=enough)


def hierarchy(x, metric, cutoff=0.30, optimal=True):
    """Exclude undefined profiles explicitly; invalid labels are zero."""
    x = np.asarray(x, float)
    centered = x - x.mean(1, keepdims=True) if metric == "correlation" else x
    valid = np.isfinite(x).all(1) & (np.linalg.norm(centered, axis=1) > 1e-12)
    indices = np.flatnonzero(valid)
    labels = np.zeros(len(x), dtype=int)
    if len(indices) < 2:
        labels[indices] = 1
        return dict(linkage=None, labels=labels, order=np.r_[indices, np.flatnonzero(~valid)],
                    valid=valid, condensed=np.array([]), metric=metric)
    distances = np.clip(pdist(x[valid], metric=metric), 0, 2)
    if not np.isfinite(distances).all():
        raise ValueError("undefined distance after profile filtering")
    tree = linkage(distances, method="average", optimal_ordering=optimal)
    labels[indices] = fcluster(tree, cutoff, criterion="distance")
    return dict(linkage=tree, labels=labels,
                order=np.r_[indices[leaves_list(tree)], np.flatnonzero(~valid)],
                valid=valid, condensed=distances, metric=metric)


def cut_labels(tree, cutoff):
    labels = tree['labels'].copy()
    if tree['linkage'] is not None:
        labels[tree['valid']] = fcluster(tree['linkage'], cutoff, criterion='distance')
    return labels


def stable_group_ids(labels, mass, names, prefix):
    """Largest candidate mass first, with deterministic tie breaking."""
    groups = [v for v in np.unique(labels) if v != 0]
    groups.sort(key=lambda v: (-float(np.asarray(mass)[labels == v].sum()),
                              min(np.asarray(names)[labels == v])))
    mapping = {v: f'{prefix}{i + 1:02d}' for i, v in enumerate(groups)}
    return np.array([mapping.get(v, 'unclustered') for v in labels])


def adjusted_rand(a, b):
    a, b = np.asarray(a), np.asarray(b)
    if len(a) != len(b):
        raise ValueError('partitions differ in length')
    if len(a) < 2:
        return 1.0
    _, ai = np.unique(a, return_inverse=True)
    _, bi = np.unique(b, return_inverse=True)
    tab = np.zeros((ai.max() + 1, bi.max() + 1), dtype=np.int64)
    np.add.at(tab, (ai, bi), 1)
    choose2 = lambda x: np.sum(x * (x - 1) / 2)
    total = len(a) * (len(a) - 1) / 2
    index, sa, sb = choose2(tab), choose2(tab.sum(1)), choose2(tab.sum(0))
    expected = sa * sb / total
    denom = (sa + sb) / 2 - expected
    return float((index - expected) / denom) if abs(denom) > 1e-14 else 1.0


def silhouette_from_tree(tree, labels):
    """Conventional silhouette; singleton silhouettes are zero."""
    labels = np.asarray(labels)[tree['valid']]
    groups = np.unique(labels)
    if len(groups) < 2 or len(groups) == len(labels):
        return None
    dist = squareform(tree['condensed'])
    score = np.zeros(len(labels))
    for i in range(len(labels)):
        own = labels == labels[i]
        if own.sum() <= 1:
            continue
        a = dist[i, own].sum() / (own.sum() - 1)
        b = min(dist[i, labels == g].mean() for g in groups if g != labels[i])
        score[i] = (b - a) / max(a, b) if max(a, b) else 0
    return float(score.mean())


def block_feature_weights(block_ids, sampled_blocks):
    """sqrt multiplicity preserves block resampling in cosine geometry."""
    block_ids = np.asarray(block_ids)
    return np.sqrt(np.array([(np.asarray(sampled_blocks) == g).sum() for g in block_ids], float))


def signed_candidate_jaccard(mask_a, delta_a, mask_b, delta_b):
    """Opposite signs at one pattern are two different set elements."""
    shared = int((mask_a & mask_b & (np.sign(delta_a) == np.sign(delta_b))).sum())
    union = int(mask_a.sum() + mask_b.sum() - shared)
    return (shared / union if union else None), shared


def resampling_stability(x, block_ids, row_labels, column_labels, *, repetitions=50,
                         seed=20260927, cutoff=0.30):
    rng = np.random.default_rng(seed)
    blocks = np.unique(block_ids)
    row_co = np.zeros((len(x), len(x)), dtype=np.uint16)
    col_co = np.zeros((x.shape[1], x.shape[1]), dtype=np.uint16)
    invalid_rows = invalid_columns = 0
    for _ in range(repetitions):
        sampled = rng.choice(blocks, size=len(blocks), replace=True)
        weights = block_feature_weights(block_ids, sampled)
        a = hierarchy(x * weights, 'cosine', cutoff, optimal=False)['labels']
        sampled_rows = rng.integers(0, len(x), size=len(x))
        b = hierarchy(x[sampled_rows].T, 'correlation', cutoff, optimal=False)['labels']
        row_co += (a[:, None] == a[None, :]) & (a[:, None] != 0) & (a[None, :] != 0)
        col_co += (b[:, None] == b[None, :]) & (b[:, None] != 0) & (b[None, :] != 0)
        invalid_rows += int((a == 0).sum())
        invalid_columns += int((b == 0).sum())
    def summarize(labels, counts):
        result = []
        for group in np.unique(labels):
            indices = np.flatnonzero(labels == group)
            sub = counts[np.ix_(indices, indices)] / repetitions
            pairs = sub[np.triu_indices(len(indices), 1)]
            result.append(dict(group=group, members=len(indices), pairs=len(pairs),
                mean_coassignment=float(pairs.mean()) if len(pairs) else None,
                q10_coassignment=float(np.quantile(pairs, .1)) if len(pairs) else None,
                minimum_coassignment=float(pairs.min()) if len(pairs) else None))
        return result
    return dict(targets=summarize(row_labels, row_co), patterns=summarize(column_labels, col_co),
                target_coassignment=row_co / repetitions, pattern_coassignment=col_co / repetitions,
                invalid_row_profiles=invalid_rows, invalid_column_profiles=invalid_columns)
