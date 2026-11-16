"""Marginal k-point log contrasts, joint-table occupancy and cell bootstrap."""
import hashlib
import json
from itertools import product
import numpy as np
from scipy.stats import binom
from ..bootstrap import summarize_distribution


def seeded_rng(seed, stage, genes):
    payload = json.dumps([seed, stage, list(genes)], separators=(',', ':')).encode()
    return np.random.default_rng(int.from_bytes(hashlib.sha256(payload).digest()[:8], 'big'))


def state_space(order):
    if not isinstance(order, int) or not 2 <= order <= 7:
        raise ValueError('supported order is 2 through 7')
    return np.array(list(product((0, 1), repeat=order)), dtype=np.uint8)


def mfi_from_counts(counts, alpha=0.5):
    counts = np.asarray(counts, dtype=float)
    if counts.ndim != 1 or len(counts) not in [2 ** k for k in range(2, 8)]:
        raise ValueError('counts must contain 2^k states for 2 <= k <= 7')
    if not np.isfinite(counts).all() or (counts < 0).any() or not (counts == np.floor(counts)).all() or counts.sum() <= 0:
        raise ValueError('counts must be nonnegative integer observations with positive total')
    if not np.isfinite(alpha) or alpha < 0 or (alpha == 0 and (counts == 0).any()):
        raise ValueError('zero cells require positive smoothing; alpha must be finite and nonnegative')
    states = state_space(int(np.log2(len(counts))))
    signs = np.where((states.shape[1] - states.sum(axis=1).astype(int)) % 2 == 0, 1, -1)
    value = float(np.log((counts + alpha) / (counts.sum() + len(counts) * alpha)) @ signs)
    return 0.0 if abs(value) < 1e-12 else value


def joint_table(matrix, genes, config, stage):
    values = matrix.loc[:, list(genes)].to_numpy(dtype=np.uint8)
    order, n = len(genes), len(values)
    states = state_space(order)
    codes = values @ (2 ** np.arange(order - 1, -1, -1))
    counts = np.bincount(codes, minlength=2 ** order)
    positive = counts[counts > 0]
    occupancy = float(len(positive) / len(counts))
    observed_min = int(positive.min())
    quality = occupancy >= config.min_occupancy and observed_min >= config.min_observed_state_count
    raw = {''.join(map(str, s)): int(c) for s, c in zip(states, counts)}
    shared = dict(order=order, total_cells=n, mfi=mfi_from_counts(counts, config.smoothing_alpha),
                  mfi_mode='marginal', smoothing_alpha=config.smoothing_alpha,
                  state_table_occupancy=occupancy, zero_state_count=int((counts == 0).sum()),
                  zero_state_fraction=float((counts == 0).mean()), min_state_count=int(counts.min()),
                  min_observed_state_count=observed_min, raw_state_counts=raw,
                  table_quality_pass=quality, bootstrap_performed=quality)
    marginal = counts @ states / n
    expected = n * np.prod(np.where(states, marginal, 1 - marginal), axis=1)
    enrichment = np.log2((counts + config.epsilon) / (expected + config.epsilon))
    boot_mfi = None
    boot_enrichment = None
    if quality:
        draws = seeded_rng(config.random_seed, stage, genes).multinomial(n, counts/n, size=config.n_bootstrap)
        signs = np.where((order - states.sum(axis=1).astype(int)) % 2 == 0, 1, -1)
        boot_mfi = np.log((draws + config.smoothing_alpha) / (n + len(states)*config.smoothing_alpha)) @ signs
        marginal_draws = draws @ states / n
        boot_expected = n * np.prod(np.where(states[None, :, :], marginal_draws[:, None, :],
                                             1 - marginal_draws[:, None, :]), axis=2)
        boot_enrichment = np.log2((draws + config.epsilon)/(boot_expected + config.epsilon))
    for key, value in (summarize_distribution(boot_mfi, shared['mfi'], config.ci_level).items()
                       if quality else {k: None for k in ('median', 'ci_low', 'ci_high', 'sign_stability')}.items()):
        shared['mfi_bootstrap_' + key] = value
    rows = []
    for i, state in enumerate(states):
        row = dict(shared, support=int(counts[i]), state_support=int(counts[i]),
                   frequency=float(counts[i]/n), expected_support=float(expected[i]),
                   log2_enrichment=float(enrichment[i]),
                   p_value_null=float(binom.sf(counts[i]-1, n, np.clip(expected[i]/n, 0, 1))))
        summary = (summarize_distribution(boot_enrichment[:, i], enrichment[i], config.ci_level)
                   if quality else {k: None for k in ('median', 'ci_low', 'ci_high', 'sign_stability')})
        row.update({'enrichment_bootstrap_' + key: value for key, value in summary.items()})
        rows.append(row)
    return rows


def stable_reference(row, config):
    return (row['table_quality_pass'] and row['support'] >= config.min_support
            and abs(row['mfi']) >= config.min_abs_mfi and row['q_value_null'] <= config.alpha_null
            and row['mfi_bootstrap_sign_stability'] >= config.min_sign_stability
            and (row['mfi_bootstrap_ci_low'] > 0 or row['mfi_bootstrap_ci_high'] < 0)
            and row['enrichment_bootstrap_sign_stability'] >= config.min_sign_stability
            and row['enrichment_bootstrap_ci_low'] > 0)


def pattern_code(pattern):
    return int(np.array(pattern.states) @ (2 ** np.arange(pattern.order - 1, -1, -1)))
