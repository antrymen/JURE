"""Stator Methods Eq. 1/2 log-contrasts, here explicitly MARGINAL.

https://doi.org/10.1038/s44320-024-00074-1
No Markov blanket conditioning or causal identification is performed.
"""
from dataclasses import dataclass
from itertools import product
import numpy as np
from .preprocessing import binary_values


def state_space(order):
    return np.array(list(product((0, 1), repeat=order)), dtype=np.uint8)


def joint_state_counts(S, genes=None):
    values = binary_values(S, genes)
    order = values.shape[1]
    if order not in (2, 3):
        raise NotImplementedError("v0.1 MFI supports 2 or 3 genes")
    codes = values @ (2 ** np.arange(order - 1, -1, -1))
    return np.bincount(codes, minlength=2 ** order)


@dataclass(frozen=True)
class MFIResult:
    value: float
    smoothing_alpha: float
    raw_state_counts: dict[str, int]
    mode: str = "marginal"


def mfi_from_counts(counts, alpha=0.5, mode="marginal"):
    if mode != "marginal":
        raise NotImplementedError("conditional MFI reserved for a future version")
    counts = np.asarray(counts, dtype=float)
    if counts.shape not in ((4,), (8,)):
        raise ValueError("counts must contain 4 or 8 lexicographically ordered states")
    if not np.isfinite(counts).all() or (counts < 0).any() or counts.sum() <= 0 or not (counts == np.floor(counts)).all():
        raise ValueError("counts must be nonnegative integers with positive total")
    if not np.isfinite(alpha) or alpha < 0:
        raise ValueError("alpha must be finite and nonnegative")
    if alpha == 0 and (counts == 0).any():
        raise ValueError("zero state count requires positive smoothing_alpha")
    order = int(np.log2(len(counts)))
    states = state_space(order)
    signs = np.where((order - states.sum(axis=1).astype(int)) % 2 == 0, 1, -1)
    probs = (counts + alpha) / (counts.sum() + len(counts) * alpha)
    value = float(signs @ np.log(probs))
    if abs(value) < 1e-12:
        value = 0.0
    return MFIResult(value, alpha, {"".join(map(str, s)): int(c) for s, c in zip(states, counts)})


def calculate_mfi(S, genes=None, alpha=0.5, mode="marginal"):
    return mfi_from_counts(joint_state_counts(S, genes), alpha, mode)
