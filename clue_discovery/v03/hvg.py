"""Discovery-owned HVG proxy; raw-count Fano baseline is explicitly labelled.

This does not claim to implement normalized/dispersion-adjusted scRNA-seq HVGs.
Only the supplied discovery matrix is accepted, avoiding an opposite-fold input.
"""
from dataclasses import dataclass
import json

import numpy as np
import pandas as pd
from scipy import sparse


HVG_METHOD = 'raw_count_sample_fano_hvg_proxy'
SUPPORTED_BENCHMARK_SIZES = (50, 100, 250, 500, 1000)


@dataclass
class HVGSelection:
    genes: tuple[str, ...]
    table: pd.DataFrame
    metadata: dict


def select_hvgs(counts, genes, *, n_top=50, fold='A', min_detection_rate=.01,
                max_detection_rate=.99) -> HVGSelection:
    """Rank eligible genes by sample variance / mean, tie-breaking by gene name."""
    genes = tuple(map(str, genes))
    if len(set(genes)) != len(genes):
        raise ValueError('gene names must be unique')
    if isinstance(n_top, bool) or not isinstance(n_top, int) or n_top < 1:
        raise ValueError('n_top must be a positive integer')
    if not 0 <= min_detection_rate < max_detection_rate <= 1:
        raise ValueError('invalid detection-rate bounds')
    if len(counts.shape) != 2 or counts.shape[1] != len(genes) or counts.shape[0] < 2:
        raise ValueError('matrix must contain >=2 discovery cells and match gene names')
    if sparse.issparse(counts):
        matrix = counts.tocsr().astype(np.float64)
        matrix.sum_duplicates()
        values = matrix.data
    else:
        matrix = np.asarray(counts, dtype=np.float64)
        values = matrix
    if not np.isfinite(values).all() or (values < 0).any() or (values != np.floor(values)).any():
        raise ValueError('HVG proxy requires finite nonnegative integer raw counts')
    n = matrix.shape[0]
    mean = np.asarray(matrix.mean(axis=0)).ravel()
    second = np.asarray(matrix.power(2).mean(axis=0)).ravel() if sparse.issparse(matrix) else np.einsum('ij,ij->j', matrix, matrix)/n
    variance = np.maximum(0, (second-mean**2)*n/(n-1))
    detection = np.asarray((matrix > 0).mean(axis=0)).ravel()
    fano = np.divide(variance, mean, out=np.zeros_like(mean), where=mean > 0)
    table = pd.DataFrame({'gene': genes, 'mean': mean, 'variance': variance,
                          'detection_rate': detection, 'selection_metric': fano})
    table['eligible'] = (mean > 0) & table.detection_rate.between(min_detection_rate, max_detection_rate)
    ranked = table.loc[table.eligible].sort_values(['selection_metric', 'gene'], ascending=[False, True])
    if len(ranked) < n_top:
        raise ValueError(f'only {len(ranked)} eligible discovery genes; requested {n_top}')
    selected = tuple(ranked.head(n_top).gene)
    ranks = {gene: i+1 for i, gene in enumerate(ranked.gene)}
    table['rank'] = pd.array([ranks.get(gene) for gene in genes], dtype='Int64')
    table['selected'] = table.gene.isin(selected)
    table['fold'] = str(fold)
    table['selection_method'] = HVG_METHOD
    parameters = {'n_top': n_top, 'min_detection_rate': min_detection_rate,
                  'max_detection_rate': max_detection_rate, 'variance_ddof': 1,
                  'tie_breaker': 'gene_lexical', 'fit_population': 'discovery_fold_only'}
    table['selection_parameters'] = json.dumps(parameters, sort_keys=True)
    return HVGSelection(selected, table, {'method': HVG_METHOD, 'fold': str(fold),
        'n_discovery_cells': n, 'n_input_genes': len(genes), 'n_selected': n_top,
        'n_eligible': len(ranked), 'parameters': parameters})
