from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from clue_discovery.nt_reference import select_fano_module
from clue_discovery.v02 import Population, ReferenceConfig
from nt_reference_experiment.low_memory import prepare_nt_low_memory


class RestrictedReader:
    """Reject excluded rows and blocks larger than the configured memory bound."""
    def __init__(self, matrix, allowed, maximum_rows):
        self.matrix, self.shape = matrix, matrix.shape
        self.allowed, self.maximum_rows, self.calls = set(allowed), maximum_rows, []

    def __getitem__(self, key):
        assert isinstance(key, slice) and key.step is None
        requested = list(range(key.start, key.stop))
        assert set(requested) <= self.allowed
        assert len(requested) <= self.maximum_rows
        self.calls.append(requested)
        return self.matrix[key]


def example():
    rng = np.random.default_rng(143)
    matrix = rng.poisson(np.linspace(.08, 2, 15), size=(59, 15))
    rows = np.array([i for i in range(len(matrix)) if i % 7 not in (0, 4)])
    labels = np.where(np.arange(len(rows)) % 3 == 0, 'B', 'A')
    genes = tuple(f'G{i:02}' for i in range(matrix.shape[1]))
    return matrix, rows, labels, genes


@pytest.mark.parametrize('storage', ['dense', 'csr', 'hdf5', 'backed_csr'])
def test_streaming_matches_original_fold_fano_and_exact_nt_counts(tmp_path, storage):
    matrix, rows, labels, genes = example()
    config = ReferenceConfig()
    with h5py.File(tmp_path/'counts.h5', 'w') as handle:
        if storage == 'backed_csr':
            from anndata.io import sparse_dataset, write_elem
            write_elem(handle, 'X', sparse.csr_matrix(matrix))
            backing = sparse_dataset(handle['X'])
        else:
            backing = (sparse.csr_matrix(matrix) if storage == 'csr'
                       else handle.create_dataset('X', data=matrix, chunks=(4, len(genes)))
                       if storage == 'hdf5' else matrix)
        tracker = RestrictedReader(backing, rows, maximum_rows=3)
        result = prepare_nt_low_memory(SimpleNamespace(X=tracker), rows, labels, genes,
                                       config, module_size=4, chunk_rows=3)
        for fold in ('A', 'B'):
            owned = matrix[rows[labels == fold]]
            population = Population(owned, genes, tuple(f'{fold}{i}' for i in range(len(owned))))
            module, qc = select_fano_module(population, module_size=4,
                min_detection_rate=config.min_detection_rate, max_detection_rate=config.max_detection_rate)
            assert result.modules[fold] == module
            pd.testing.assert_frame_equal(result.feature_tables[fold], qc, rtol=1e-12, atol=1e-12)
        assert result.genes == tuple(g for g in genes if g in set(sum(result.modules.values(), [])))
        columns = [genes.index(g) for g in result.genes]
        np.testing.assert_array_equal(result.matrix.toarray(), matrix[rows][:, columns])
        np.testing.assert_array_equal(result.totals, matrix[rows].sum(axis=1))
        np.testing.assert_array_equal(result.detected, (matrix[rows] > 0).sum(axis=1))
        assert result.memory_strategy['maximum_count_block_rows'] <= 3
        visits = [row for call in tracker.calls for row in call]
        assert visits == rows.tolist()*2


def test_other_fold_poison_and_chunk_size_do_not_change_own_selection():
    matrix, rows, labels, genes = example()
    config = ReferenceConfig()
    first = prepare_nt_low_memory(SimpleNamespace(X=matrix), rows, labels, genes, config,
                                  module_size=4, chunk_rows=1)
    changed = matrix.copy()
    b_rows = rows[labels == 'B']
    changed[b_rows, 0] = np.where(np.arange(len(b_rows)) % 2, 1000, 0)
    second = prepare_nt_low_memory(SimpleNamespace(X=changed), rows, labels, genes, config,
                                   module_size=4, chunk_rows=128)
    assert first.modules['A'] == second.modules['A']
    pd.testing.assert_frame_equal(first.feature_tables['A'], second.feature_tables['A'])
    assert first.modules['B'] != second.modules['B']


def test_sparse_duplicates_and_explicit_zeros_follow_count_semantics():
    # Two entries for column 0 on row 0 sum to the raw count 3. Stored zeros
    # must not increase measured detected genes or fold detection rates.
    matrix = sparse.csr_matrix((np.array([1., 2., 0., 1., 3., 2., 4.]),
        np.array([0, 0, 1, 1, 0, 1, 0]), np.array([0, 3, 4, 6, 7])), shape=(4, 2))
    dense = matrix.toarray()
    result = prepare_nt_low_memory(SimpleNamespace(X=matrix), np.arange(4), ['A', 'A', 'B', 'B'],
                                   ('G1', 'G2'), ReferenceConfig(), module_size=1, chunk_rows=1)
    np.testing.assert_array_equal(result.detected, (dense > 0).sum(axis=1))
    np.testing.assert_array_equal(result.totals, dense.sum(axis=1))
    for fold, indices in [('A', [0, 1]), ('B', [2, 3])]:
        _, expected = select_fano_module(Population(dense[indices], ('G1', 'G2'), tuple(f'{fold}{i}' for i in indices)), module_size=1)
        pd.testing.assert_frame_equal(result.feature_tables[fold], expected)


@pytest.mark.parametrize('invalid', [-1., .5, np.nan, np.inf])
def test_invalid_selected_raw_counts_fail_but_excluded_rows_are_not_read(invalid):
    matrix, rows, labels, genes = example()
    matrix = matrix.astype(float)
    matrix[0, 0] = invalid  # excluded source row is never observed
    prepare_nt_low_memory(SimpleNamespace(X=matrix), rows, labels, genes, ReferenceConfig(), module_size=2)
    matrix[rows[0], 0] = invalid
    with pytest.raises(ValueError, match='raw counts'):
        prepare_nt_low_memory(SimpleNamespace(X=matrix), rows, labels, genes, ReferenceConfig(), module_size=2)


def test_invalid_input_and_underpowered_fold_are_rejected_before_counts_read():
    matrix, rows, labels, genes = example()
    tracker = RestrictedReader(matrix, rows, maximum_rows=1)
    options = dict(reader=SimpleNamespace(X=tracker), rows=rows, fold_labels=labels,
                   gene_names=genes, config=ReferenceConfig(), module_size=2, chunk_rows=1)
    for changes in ({'rows': rows[::-1]}, {'rows': rows.astype(float)}, {'chunk_rows': 0},
                    {'module_size': True}, {'gene_names': ('G',)*len(genes)},
                    {'fold_labels': ['A']*len(rows)},
                    {'fold_labels': ['B']+['A']*(len(rows)-1)}):
        with pytest.raises(ValueError):
            prepare_nt_low_memory(**(options | changes))
    assert not tracker.calls
