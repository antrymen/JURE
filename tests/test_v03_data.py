from dataclasses import replace
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from clue_discovery.v03.config import ScalableConfig
from clue_discovery.v03.data import save_prepared, load_prepared
from clue_discovery.v03.hvg import select_hvgs
from nt_reference_experiment.low_memory import prepare_nt_low_memory


def test_streamed_prefix_equals_own_fold_hvg_and_preserves_opposite_measurement(tmp_path):
    rng = np.random.default_rng(17)
    x = rng.poisson(1.3, (120, 14))
    labels = np.array(['A']*60+['B']*60)
    genes = tuple(f'g{i:02}' for i in range(14))
    config = replace(ScalableConfig(), hvg_pool_size=5)
    prepared = prepare_nt_low_memory(SimpleNamespace(X=x), np.arange(120), labels, genes, config, module_size=10, chunk_rows=11)
    save_prepared(tmp_path, prepared.matrix, prepared.genes, [f'c{i}' for i in range(120)], labels,
                  dict(source='test_raw', real_data_used=True), prepared.feature_tables)
    folds, selections, _ = load_prepared(tmp_path, config)
    for f in ('A', 'B'):
        expected = select_hvgs(x[labels == f], genes, n_top=5, fold=f)
        assert selections[f].genes == expected.genes
        opposite = 'B' if f == 'A' else 'A'
        encoded, _ = folds[opposite].encode(selections[f].genes, config)
        assert np.array_equal(encoded.to_numpy(), (x[labels == opposite][:, [genes.index(g) for g in expected.genes]] > 0))
    data = json.loads((tmp_path/'identities.json').read_text())
    data['genes'][0] = 'changed'
    (tmp_path/'identities.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='hash'):
        load_prepared(tmp_path, config)
