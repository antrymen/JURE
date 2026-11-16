import numpy as np
import pandas as pd
from scipy import sparse


def encode_binary_states(X, threshold=0, mode="detected", *, gene_names=None,
                         input_kind="counts"):
    """Return binary DataFrame and gene QC table. Normalized input requires opt-in."""
    if mode != "detected":
        raise NotImplementedError("only detected encoding is implemented")
    if not np.isfinite(threshold):
        raise ValueError("threshold must be finite")
    names = list(X.columns) if gene_names is None and isinstance(X, pd.DataFrame) else gene_names
    if sparse.issparse(X):
        X = X.toarray()  # select a candidate module before encoding large sparse matrices
    values = np.asarray(X)
    if values.ndim != 2 or not all(values.shape):
        raise ValueError("X must be a nonempty cells x genes matrix")
    if not np.issubdtype(values.dtype, np.number) and values.dtype != bool:
        raise ValueError("X must be numeric")
    if not np.isfinite(values).all():
        raise ValueError("X contains nonfinite values")
    if input_kind == "counts":
        if (values < 0).any() or not (values == np.floor(values)).all():
            raise ValueError("counts must be nonnegative integers; declare expression explicitly")
    elif input_kind == "binary":
        if not np.isin(values, [0, 1]).all() or threshold != 0:
            raise ValueError("binary input requires 0/1 data and threshold=0")
    elif input_kind != "expression":
        raise ValueError("unknown input_kind")
    names = list(names) if names is not None else [f"G{i}" for i in range(values.shape[1])]
    if len(names) != values.shape[1] or len(set(names)) != len(names):
        raise ValueError("gene_names must match columns and be unique")
    if any(not isinstance(g, str) or not g for g in names):
        raise ValueError("gene_names must be nonempty strings")
    S = pd.DataFrame((values > threshold).astype(np.uint8), columns=names)
    detected = S.sum(axis=0).astype(int)
    qc = pd.DataFrame({"gene": names, "detection_rate": S.mean().to_numpy(),
                       "number_detected": detected.to_numpy(),
                       "number_undetected": len(S) - detected.to_numpy()})
    return S, qc


def binary_values(S, genes=None):
    values = S.loc[:, list(genes)].to_numpy() if isinstance(S, pd.DataFrame) and genes is not None else np.asarray(S)
    if values.ndim != 2 or not all(values.shape) or not np.isin(values, [0, 1]).all():
        raise ValueError("expected a nonempty binary matrix")
    if genes is not None and values.shape[1] != len(genes):
        raise ValueError("array columns must match requested genes in their supplied order")
    return values.astype(np.uint8, copy=False)
