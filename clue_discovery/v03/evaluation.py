"""Shared locked gene-set evaluation without candidate selection."""
import hashlib
from itertools import product

import numpy as np
from scipy.stats import binom

from .artifacts import canonical, digest
from .estimability import assess_estimability
from .gain import HigherOrderGainEvaluator
from ..v02.statistics import mfi_from_counts


def stage_seed(config, role, genes, stage):
    return int.from_bytes(hashlib.sha256(canonical([config.random_seed, role, sorted(genes), stage]).encode()).digest()[:8], 'big')


def joint_counts(binary, columns, genes):
    values = binary[:, [columns[g] for g in genes]]
    codes = values @ (2 ** np.arange(len(genes)-1, -1, -1))
    return np.bincount(codes, minlength=2**len(genes))


def gain_enabled(config, order):
    return config.gain_mode == 'on' and (order <= 3 or config.quad_gain_enabled)


def evaluate_counts(counts, genes, config):
    order, n = len(genes), int(sum(counts))
    assessment = assess_estimability(counts, good_min_count=config.good_min_count,
        poor_max_zero_fraction=config.poor_max_zero_fraction,
        poor_min_observed_count=config.poor_min_observed_count)
    mfi = mfi_from_counts(counts, config.smoothing_alpha)
    gain = HigherOrderGainEvaluator(alpha=config.smoothing_alpha, epsilon=config.gain_epsilon).evaluate(counts) if gain_enabled(config, order) else None
    states = np.array(list(product((0, 1), repeat=order)), dtype=np.uint8)
    marginal = counts @ states / n
    independent = np.prod(np.where(states, marginal, 1-marginal), axis=1)
    patterns = []
    for i, state in enumerate(states):
        pattern = ''.join(str(x) for x in state)
        row = dict(reference_id='R'+digest([genes, pattern])[:20], genes=tuple(genes), order=order,
            states=tuple(map(int, state)), state_index=i, pattern=pattern,
            pattern_string=' '.join(g+('+' if s else '-') for g, s in zip(genes, state)),
            support=int(counts[i]), frequency=float(counts[i]/n),
            independent_expected_probability=float(independent[i]),
            dtuple_log2_enrichment=float(np.log2((counts[i]+.5)/(n*independent[i]+.5))),
            p_state=float(binom.sf(counts[i]-1, n, independent[i])),
            observed_probability=(float(gain['observed_probability'][i]) if gain is not None else None),
            lower_order_expected_probability=(float(gain['lower_order_expected_probability'][i]) if gain is not None else None),
            pattern_absolute_gain=(float(gain['pattern_absolute_gain'][i]) if gain is not None else None),
            relative_enrichment=(float(gain['relative_enrichment'][i]) if gain is not None else None),
            log_enrichment=(float(gain['log_enrichment'][i]) if gain is not None else None))
        patterns.append(row)
    return dict(assessment=assessment, mfi=float(mfi), gain=gain, patterns=patterns)


def eligible_pattern(row, config, *, compute_gain):
    return row['support'] >= config.min_support and (
        row['pattern_absolute_gain'] > 0 if compute_gain else row['dtuple_log2_enrichment'] > 0)


def mfi_bootstrap_pass(summary, config):
    return (summary['sign_stability'] >= config.min_sign_stability
            and (summary['ci_low'] > 0 or summary['ci_high'] < 0))
