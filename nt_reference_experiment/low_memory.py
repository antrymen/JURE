"""Two-pass NT-only preparation without retaining a cells x all-genes matrix.

The statistical design is unchanged: each fold selects its own raw-count Fano
module. The second pass retains only the union required for locked validation.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse


@dataclass(frozen=True)
class PreparedNT:
    matrix: sparse.csr_matrix
    genes: tuple[str, ...]
    modules: dict[str, list[str]]
    feature_tables: dict[str, pd.DataFrame]
    totals: np.ndarray
    detected: np.ndarray
    memory_strategy: dict


def _allowed_chunks(rows, chunk_rows):
    """Yield NT output offsets and contiguous source slices containing only NT."""
    start = 0
    while start < len(rows):
        stop = start + 1
        while (stop < len(rows) and stop-start < chunk_rows
               and rows[stop] == rows[stop-1]+1):
            stop += 1
        yield start, stop, slice(int(rows[start]), int(rows[stop-1])+1)
        start = stop


def _checked_block(values, expected_shape):
    if sparse.issparse(values):
        block = values.tocsr().astype(np.float64)
        block.sum_duplicates()
        data = block.data
    else:
        block = np.asarray(values, dtype=np.float64)
        data = block
    if block.shape != expected_shape:
        raise ValueError('count reader returned an unexpected block shape')
    if (not np.isfinite(data).all() or (data < 0).any()
            or not (data == np.floor(data)).all()):
        raise ValueError('Fano baseline requires finite nonnegative integer raw counts')
    return block


def _fano_table(genes, n, sums, squares, positive, module_size, config):
    mean = sums/n
    variance = (squares/n-mean**2)*n/(n-1)
    qc = pd.DataFrame(dict(gene=genes, mean=mean, variance=variance,
                           detection_rate=positive/n,
                           fano=np.divide(variance, mean, out=np.zeros_like(mean), where=mean > 0)))
    qc['eligible'] = qc.detection_rate.between(config.min_detection_rate, config.max_detection_rate)
    ranked = qc.loc[qc.eligible].sort_values(['fano', 'gene'], ascending=[False, True])
    module = ranked.head(module_size).gene.tolist()
    if len(module) != module_size:
        raise ValueError(f'fewer than {module_size} eligible discovery genes')
    qc['selected'] = qc.gene.isin(module)
    return module, qc


def prepare_nt_low_memory(reader, rows, fold_labels, gene_names, config, *,
                          module_size=12, chunk_rows=128):
    """Prepare two independently selected modules using bounded count blocks.

    ``rows`` are sorted, unique source NT row numbers; ``fold_labels`` correspond
    to that exact order. ``reader.X`` supports ordinary contiguous row slices
    returning dense or sparse matrices (including backed AnnData CSR data).
    Output rows retain NT order and columns retain source gene order. No count
    slice includes a row outside ``rows``. All-gene expression is never retained
    beyond a bounded block; the only persistent expression matrix has at most
    ``2 * module_size`` columns. This bounds preparation allocations, not total
    process RSS, which also depends on the reader/cache and runtime.
    """
    for key, value in [('module_size', module_size), ('chunk_rows', chunk_rows)]:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f'{key} must be a positive integer')
    rows = np.asarray(rows)
    if (rows.ndim != 1 or not np.issubdtype(rows.dtype, np.integer)
            or not len(rows) or rows[0] < 0 or np.any(rows[1:] <= rows[:-1])):
        raise ValueError('rows must be sorted unique nonempty integer source indices')
    genes = tuple(gene_names)
    if not genes or len(set(genes)) != len(genes) or any(not isinstance(g, str) or not g for g in genes):
        raise ValueError('gene_names must be unique nonempty strings')
    labels = np.asarray(fold_labels)
    if labels.shape != rows.shape or set(labels.tolist()) != {'A', 'B'}:
        raise ValueError('fold_labels must contain A and B aligned with NT rows')
    counts = {fold: int(np.count_nonzero(labels == fold)) for fold in ('A', 'B')}
    if min(counts.values()) < 2:
        raise ValueError('each discovery fold needs at least two cells')
    shape = reader.X.shape
    if len(shape) != 2 or shape[1] != len(genes) or rows[-1] >= shape[0]:
        raise ValueError('count matrix shape does not match source rows and genes')
    if not 0 <= config.min_detection_rate < config.max_detection_rate <= 1:
        raise ValueError('invalid detection rate bounds')

    ngenes = len(genes)
    sums = {fold: np.zeros(ngenes, dtype=np.float64) for fold in counts}
    squares = {fold: np.zeros(ngenes, dtype=np.float64) for fold in counts}
    positive = {fold: np.zeros(ngenes, dtype=np.int64) for fold in counts}
    totals = np.empty(len(rows), dtype=np.float64)
    detected = np.empty(len(rows), dtype=np.int64)
    blocks_read = 0
    max_rows_read = 0
    for start, stop, source_slice in _allowed_chunks(rows, chunk_rows):
        block = _checked_block(reader.X[source_slice], (stop-start, ngenes))
        totals[start:stop] = np.asarray(block.sum(axis=1)).ravel()
        detected[start:stop] = np.asarray((block > 0).sum(axis=1)).ravel()
        for fold in counts:
            mask = labels[start:stop] == fold
            if not mask.any():
                continue
            owned = block[mask]
            sums[fold] += np.asarray(owned.sum(axis=0)).ravel()
            squared = owned.power(2) if sparse.issparse(owned) else np.square(owned)
            squares[fold] += np.asarray(squared.sum(axis=0)).ravel()
            positive[fold] += np.asarray((owned > 0).sum(axis=0)).ravel()
            del owned, squared
        max_rows_read = max(max_rows_read, stop-start)
        blocks_read += 1
        del block

    modules, feature_tables = {}, {}
    for fold in counts:
        modules[fold], feature_tables[fold] = _fano_table(
            genes, counts[fold], sums[fold], squares[fold], positive[fold], module_size, config)
    selected = set(modules['A']) | set(modules['B'])
    columns = np.array([i for i, gene in enumerate(genes) if gene in selected], dtype=int)
    selected_genes = tuple(genes[i] for i in columns)
    # This array is only NT x module union, never NT x all source genes.
    compact = np.empty((len(rows), len(columns)), dtype=np.float64)
    for start, stop, source_slice in _allowed_chunks(rows, chunk_rows):
        block = _checked_block(reader.X[source_slice], (stop-start, ngenes))
        selected_block = block[:, columns]
        compact[start:stop] = selected_block.toarray() if sparse.issparse(selected_block) else selected_block
        del block, selected_block
    matrix = sparse.csr_matrix(compact)
    return PreparedNT(matrix=matrix, genes=selected_genes, modules=modules,
                      feature_tables=feature_tables, totals=totals, detected=detected,
                      memory_strategy=dict(mode='two_pass_nt_only', passes=2,
                          chunk_rows=chunk_rows, maximum_count_block_rows=max_rows_read,
                          count_blocks_per_pass=blocks_read, nt_cells=len(rows),
                          source_genes=ngenes, retained_genes=len(columns),
                          full_nt_all_gene_matrix_materialized=False,
                          excluded_source_rows_requested=False, fold_cells=counts,
                          accumulation_dtype='float64', compact_matrix_dtype='float64',
                          fano_definition='sample variance / mean; own-fold detection QC'))
