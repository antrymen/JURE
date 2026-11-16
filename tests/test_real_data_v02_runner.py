import anndata as ad
from contextlib import ExitStack
import h5py
import numpy as np
import pandas as pd
from scipy import sparse

from clue_discovery.v02 import ReferenceConfig
from real_data_v02.run import extract, reclassify, cached_counts_reader


def test_allowed_row_extraction_preserves_counts_and_skips_excluded_rows(tmp_path):
    values = np.arange(100, dtype=float).reshape(20, 5)
    # If excluded response rows were processed, checked_counts would reject them.
    values[[3, 8, 15], :] = -123.5
    path = tmp_path/'small.h5ad'
    ad.AnnData(sparse.csr_matrix(values)).write_h5ad(path)
    data = ad.read_h5ad(path, backed='r')
    rows = np.array([0, 1, 2, 4, 5, 9, 10, 11, 19])
    result, total, detected = extract(data, rows, [1, 4])
    np.testing.assert_array_equal(result.toarray(), values[rows][:, [1, 4]])
    np.testing.assert_array_equal(total, values[rows].sum(axis=1))
    np.testing.assert_array_equal(detected, (values[rows] != 0).sum(axis=1))
    data.file.close()


def test_full_family_downsample_reclassification_uses_frozen_thresholds():
    row = pd.Series(dict(support=25, delta_frequency=.1, q_value_shift=.01,
                         delta_sign_stability=.98, bootstrap_delta_ci_low=.02, bootstrap_delta_ci_high=.2))
    config = ReferenceConfig()
    assert reclassify(row, config) == 'candidate_shift'
    row.q_value_shift = .1
    assert reclassify(row, config) == 'screened_out'
    row.q_value_shift = .01
    row.bootstrap_delta_ci_low = -.01
    assert reclassify(row, config) == 'unstable_shift'


def test_dense_cached_reads_equal_backed_reads_across_chunks(tmp_path):
    values = np.arange(100, dtype=np.float32).reshape(20, 5)
    values[[3, 8, 15], :] = -123.5
    path = tmp_path/'dense.h5ad'
    ad.AnnData(values).write_h5ad(path, compression='gzip')
    # Make explicit small chunks to exercise multiple rows and column blocks.
    with h5py.File(path, 'r+') as handle:
        del handle['X']
        handle.create_dataset('X', data=values, chunks=(4, 2), compression='gzip')
    data = ad.read_h5ad(path, backed='r')
    rows = np.array([0, 1, 2, 4, 5, 9, 10, 11, 19])
    with ExitStack() as resources:
        reader = cached_counts_reader(path, data, resources)
        assert reader.X.id.get_access_plist().get_chunk_cache()[1] == 128*1024**2
        expected = extract(data, rows, [4, 1])
        actual = extract(reader, rows, [4, 1])
        np.testing.assert_array_equal(actual[0].toarray(), expected[0].toarray())
        np.testing.assert_array_equal(actual[0].toarray(), values[rows][:, [4, 1]])
        np.testing.assert_array_equal(actual[1], expected[1])
        np.testing.assert_array_equal(actual[2], expected[2])
    assert not reader.X.id.valid
    data.file.close()
