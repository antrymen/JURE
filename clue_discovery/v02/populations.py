"""Explicit cell identities make discovery/validation/test overlap detectable."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy import sparse
from ..preprocessing import encode_binary_states


@dataclass(frozen=True)
class Population:
    matrix: object
    gene_names: tuple[str, ...]
    cell_ids: tuple[str, ...]

    def __post_init__(self):
        genes, cells = tuple(self.gene_names), tuple(self.cell_ids)
        if getattr(self.matrix, 'shape', None) != (len(cells), len(genes)) or not cells or not genes:
            raise ValueError('Population requires a nonempty cells x genes matrix and matching identities')
        for name, values in [('gene_names', genes), ('cell_ids', cells)]:
            if len(set(values)) != len(values) or any(not isinstance(x, str) or not x for x in values):
                raise ValueError(f'{name} must be unique nonempty strings')
        if isinstance(self.matrix, pd.DataFrame) and list(self.matrix.columns) != list(genes):
            raise ValueError('DataFrame gene order must match gene_names')
        object.__setattr__(self, 'gene_names', genes)
        object.__setattr__(self, 'cell_ids', cells)

    def subset(self, rows):
        rows = np.asarray(rows, dtype=int)
        if isinstance(self.matrix, pd.DataFrame):
            matrix = self.matrix.iloc[rows]
        elif sparse.issparse(self.matrix):
            matrix = self.matrix.tocsr()[rows]
        else:
            matrix = np.asarray(self.matrix)[rows]
        return Population(matrix, self.gene_names, tuple(self.cell_ids[i] for i in rows))

    def encode(self, genes, config):
        indices = [self.gene_names.index(g) for g in genes]
        if isinstance(self.matrix, pd.DataFrame):
            selected = self.matrix.loc[:, list(genes)]
        elif sparse.issparse(self.matrix):
            selected = self.matrix.tocsr()[:, indices]
        else:
            selected = np.asarray(self.matrix)[:, indices]
        # Only the explicitly supplied module is ever densified.
        return encode_binary_states(selected, config.threshold, gene_names=list(genes),
                                    input_kind=config.input_kind)


def assert_disjoint(*populations):
    seen = set()
    for population in populations:
        if seen.intersection(population.cell_ids):
            raise ValueError('cell identity overlap between populations')
        seen.update(population.cell_ids)


def split_reference(population, config, strata=None):
    """Fixed random cell holdouts, optionally stratified; NOT biological replication."""
    n = len(population.cell_ids)
    labels = np.zeros(n, dtype=str) if strata is None else np.asarray(strata)
    if labels.shape != (n,) or any(pd.isna(x) for x in labels):
        raise ValueError('strata must be nonmissing labels matching NT cells')
    rng, partitions = np.random.default_rng(config.random_seed), [[], [], []]
    for label in sorted(set(map(str, labels))):
        rows = np.flatnonzero(labels.astype(str) == label)
        rows = rng.permutation(rows)
        a = int(len(rows) * config.split_fractions[0])
        b = int(len(rows) * config.split_fractions[1])
        if min(a, b, len(rows) - a - b) < 1:
            raise ValueError('each stratum needs enough cells for three nonempty partitions')
        for dest, selected in zip(partitions, (rows[:a], rows[a:a+b], rows[a+b:])):
            dest.extend(selected.tolist())
    return tuple(population.subset(sorted(rows)) for rows in partitions)
