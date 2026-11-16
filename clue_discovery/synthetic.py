"""Known distributions, including pure parity structure with unchanged pair marginals."""
import numpy as np
import pandas as pd
from .mfi import state_space

GENES = ("A", "B", "C")


def parity_probabilities(strength=0.6):
    if not -1 < strength < 1:
        raise ValueError("strength must be in (-1, 1)")
    even = np.where(state_space(3).sum(axis=1) % 2 == 0, 1, -1)
    return (1 + strength * even) / 8


def cells_from_counts(counts):
    counts = np.asarray(counts)
    if counts.shape not in ((4,), (8,)) or (counts < 0).any() or not (counts == np.floor(counts)).all():
        raise ValueError("expected four or eight integer counts")
    order = int(np.log2(len(counts)))
    return pd.DataFrame(np.repeat(state_space(order), counts.astype(int), axis=0), columns=GENES[:order])


def sample_distribution(probabilities, n=8000, seed=1):
    counts = np.random.default_rng(seed).multinomial(n, probabilities)
    return cells_from_counts(counts)


def independent(n=8000, seed=1):
    return sample_distribution(np.full(8, 1 / 8), n, seed)


def parity(n=8000, strength=0.6, seed=2):
    return sample_distribution(parity_probabilities(strength), n, seed)


def pairwise_only(n=8000, seed=3):
    # A==B with probability 0.9; C independent Bernoulli(0.5).
    return sample_distribution([.225, .225, .025, .025, .025, .025, .225, .225], n, seed)


def rare_pattern():
    # All pairs have plentiful support, but 101 has only three cells.
    # Rare marginals make 101 enriched above independence despite tiny support.
    ctrl = cells_from_counts([20, 30, 1400, 20, 30, 0, 20, 30])
    pert = cells_from_counts([20, 30, 1400, 20, 30, 3, 20, 30])
    return ctrl, pert
