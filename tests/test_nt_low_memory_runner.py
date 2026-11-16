import json
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from clue_discovery.nt_reference import select_fano_module
from clue_discovery.v02 import Population, ReferenceConfig
from nt_reference_experiment import run as runner
from real_data_test.prepare import file_hash


@pytest.mark.parametrize('storage', ['dense', 'csr'])
def test_streaming_runner_uses_only_nt_and_own_fold_features(tmp_path, monkeypatch, storage):
    rng = np.random.default_rng(981)
    values = rng.poisson(.6, size=(160, 14)).astype(np.float32)
    selected = np.arange(0, 160, 2)
    values[1::2] = -123.5  # Any expression access outside NT must fail raw-count checks.
    genes = tuple(f'g{i:02}' for i in range(14))
    obs = pd.DataFrame({'gene': ['non-targeting' if i % 2 == 0 else 'perturbed' for i in range(160)],
                        'nperts': [i % 2 for i in range(160)],
                        'guide_id': ['NT' if i % 2 == 0 else 'P' for i in range(160)],
                        'batch': [f'GEM{i % 7}' for i in range(160)]},
                       index=[f'cell{i}' for i in range(160)])
    source = tmp_path/'source.h5ad'
    ad.AnnData(values if storage == 'dense' else sparse.csr_matrix(values),
               obs=obs, var=pd.DataFrame(index=genes)).write_h5ad(source)
    with h5py.File(source, 'r+') as handle:
        # A deliberately unsupported encoding proves unrelated metadata is not loaded.
        handle['uns'].attrs['encoding-type'] = 'must-not-read-this'
    monkeypatch.setattr(runner, 'SOURCE_MD5', file_hash(source, 'md5'))
    monkeypatch.setattr(runner, 'SOURCE_SHAPE', values.shape)
    monkeypatch.setattr(runner, 'SOURCE_NT_CELLS', len(selected))
    monkeypatch.setattr(runner, 'FORMAL_CONFIG', ReferenceConfig(max_order=2, n_bootstrap=20))
    output = tmp_path/'output'
    runner.run(source, output, Path(__file__).resolve().parents[1])
    manifest = json.loads((output/'nt_fold_manifest.json').read_text())
    assert json.loads((output/'execution_status.json').read_text())['complete'] is True
    assert manifest['fold_counts'] == {'A': 40, 'B': 40}
    assert manifest['memory_strategy']['full_expression_matrix_materialized'] is False
    memberships = manifest['fold_cell_ids']
    assert set(memberships['A']).isdisjoint(memberships['B'])
    assert set(memberships['A']) | set(memberships['B']) == set(obs.index[selected])
    for fold, ids in memberships.items():
        row_ids = obs.index.get_indexer(ids)
        expected_genes, expected_qc = select_fano_module(
            Population(sparse.csr_matrix(values[row_ids]), genes, tuple(ids)))
        # Downstream search canonicalizes gene sets. Exactly tied Fano scores
        # can swap display rank through sparse-mean rounding; membership must agree.
        assert set(manifest['module_genes'][fold]) == set(expected_genes)
        actual_qc = pd.read_csv(output/f'fold_{fold}_feature_selection.csv')
        for column in ('mean', 'variance', 'detection_rate', 'fano'):
            np.testing.assert_allclose(actual_qc[column], expected_qc[column], rtol=1e-12, atol=1e-12)
    cell_metadata = pd.read_csv(output/'nt_cell_metadata.csv.gz')
    np.testing.assert_array_equal(cell_metadata.measured_total_counts, values[selected].sum(axis=1))
    np.testing.assert_array_equal(cell_metadata.measured_detected_genes, (values[selected] > 0).sum(axis=1))
