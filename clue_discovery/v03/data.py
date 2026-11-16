"""NT-only bounded preparation and deterministic scale-benchmark inputs."""
from dataclasses import replace
import gc
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy import sparse

from ..nt_reference import split_nt_twofold
from ..v02.populations import Population
from .artifacts import canonical, digest, write_csv, write_json
from .hvg import HVG_METHOD, HVGSelection


KNOWN_REPLOGLE_MD5 = 'd8cba17576d1a8afc0f7d71b79cad0f7'


def file_hash(path, algorithm='sha256'):
    h = hashlib.new(algorithm)
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024**2), b''):
            h.update(chunk)
    return h.hexdigest()


def save_prepared(path, matrix, genes, cells, labels, metadata, feature_tables=None):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    sparse.save_npz(path/'counts.npz', sparse.csr_matrix(matrix))
    write_json(path/'identities.json', dict(genes=genes, cells=cells, fold_labels=labels))
    for fold, table in (feature_tables or {}).items():
        write_csv(path/f'feature_moments_{fold}.csv', table)
    metadata = dict(metadata, count_matrix_sha256=file_hash(path/'counts.npz'),
                    identities_sha256=file_hash(path/'identities.json'),
                    feature_table_hashes={f'feature_moments_{f}.csv': file_hash(path/f'feature_moments_{f}.csv')
                                          for f in (feature_tables or {})})
    write_json(path/'data_manifest.json', metadata)
    return metadata


def prepare_synthetic(path, config, *, n_cells=10691, n_genes=1200):
    """Fixed mixed-density modules for resource stress, not biological validation.

    Groups of four have pairwise + three-way terms, independent low-detection
    genes exercise sparse tables. Selection sees counts, not known module labels.
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    specification = dict(kind='synthetic_resource_scale_stress', seed=config.random_seed,
        n_cells=n_cells, n_genes=n_genes, module_size=4, loglinear_pair_coefficient=.35,
        loglinear_triplet_coefficient=.25, loglinear_main_coefficient=.15,
        sparse_gene_fraction=.2, sparse_detection=.015, positive_count_lambda='1+(gene_index%17)/2',
        cannot_replace_real_NT_qualification=True)
    write_json(path/'generation_config_frozen.json', specification)
    rng = np.random.default_rng(config.random_seed)
    states = np.array([[int(c) for c in f'{i:04b}'] for i in range(16)])
    spins = 2*states-1
    logits = .15*spins.sum(1)+.35*(spins[:, 0]*spins[:, 1]+spins[:, 1]*spins[:, 2]+spins[:, 2]*spins[:, 3])+.25*np.prod(spins[:, :3], axis=1)
    p = np.exp(logits-logits.max()); p /= p.sum()
    binary = np.empty((n_cells, n_genes), dtype=np.uint8)
    for start in range(0, n_genes, 4):
        width = min(4, n_genes-start)
        binary[:, start:start+width] = states[rng.choice(16, n_cells, p=p), :width]
    sparse_columns = np.arange(0, n_genes, 5)
    binary[:, sparse_columns] = rng.binomial(1, .015, (n_cells, len(sparse_columns)))
    matrix = binary*(1+rng.poisson(1+(np.arange(n_genes)%17)/2, size=binary.shape))
    genes = tuple(f'G{i:04}' for i in range(n_genes))
    cells = tuple(f'scale_synthetic_{i:05}' for i in range(n_cells))
    labels = np.array(['A']*(n_cells//2)+['B']*(n_cells-n_cells//2))
    metadata = dict(source='synthetic_resource_scale_stress', nt_only=False, real_data_used=False,
        synthetic_reference_only=True, n_cells=n_cells, n_genes=n_genes,
        split='independent_iid_rows_first_half_A_second_half_B', generation=specification,
        generation_hash=digest(specification))
    return save_prepared(path, matrix, genes, cells, labels, metadata)


def prepare_real_nt(source, path, config):
    """Verify the frozen raw source and project own-fold top1000 in two passes."""
    import anndata as ad
    import h5py
    from nt_reference_experiment.low_memory import prepare_nt_low_memory
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    write_json(path/'preparation_config_frozen.json', dict(config=config.to_dict(), config_hash=config.sha256,
        projection_pool_size=1000, chunk_rows=128, hdf5_cache_bytes=64*1024**2,
        preparation_is_not_1000_gene_discovery=True))
    if file_hash(source, 'md5') != KNOWN_REPLOGLE_MD5:
        raise ValueError('raw source checksum mismatch: use the previously audited Replogle K562 essential source')
    sha = file_hash(source)
    with h5py.File(source, 'r', rdcc_nbytes=64*1024**2, rdcc_nslots=100003) as handle:
        obs = ad.io.read_elem(handle['obs'])
        key = handle['var'].attrs['_index']
        if isinstance(key, bytes):
            key = key.decode()
        genes = tuple(ad.io.read_elem(handle['var'][key]).astype(str))
        values = handle['X']
        reader = SimpleNamespace(X=values if isinstance(values, h5py.Dataset) else ad.io.sparse_dataset(values))
        if reader.X.shape != (310385, 8563) or not obs.index.is_unique or len(set(genes)) != len(genes):
            raise ValueError('unexpected source shape or non-unique identities')
        rows = np.flatnonzero(obs.gene.astype(str).to_numpy() == 'non-targeting')
        if len(rows) != 10691 or not (obs.iloc[rows].nperts.to_numpy() == 0).all():
            raise ValueError('NT identity/count mismatch')
        nt = obs.iloc[rows].copy()
        if nt[['batch', 'guide_id']].isna().any().any():
            raise ValueError('NT stratification or guide metadata is missing')
        cells = tuple(nt.index.astype(str))
        dummy = Population(sparse.csr_matrix((len(cells), 1)), ('__identity_only__',), cells)
        a, b = split_nt_twofold(dummy, random_seed=config.random_seed, strata=nt.batch.astype(str).to_numpy())
        a_cells = set(a.cell_ids)
        labels = np.array(['A' if c in a_cells else 'B' for c in cells])
        write_csv(path/'nt_fold_membership.csv', pd.DataFrame(dict(cell_id=cells, source_row=rows,
            fold=labels, batch=nt.batch.astype(str).to_numpy())))
        del obs, dummy, a, b
        gc.collect()
        prepared = prepare_nt_low_memory(reader, rows, labels, genes, config, module_size=1000, chunk_rows=128)
        metadata = dict(source='Replogle K562 Essential day 6', nt_only=True, real_data_used=True,
            source_sha256=sha, source_md5=KNOWN_REPLOGLE_MD5, source_shape=[310385, 8563],
            n_cells=len(cells), projected_gene_union=len(prepared.genes),
            raw_source_genes=len(genes), fold_counts={'A': int(sum(labels == 'A')), 'B': int(sum(labels == 'B'))},
            split='GEM-stratified twofold random cell holdout, not biological replication',
            split_seed=config.random_seed, memory_strategy=prepared.memory_strategy,
            scientific_selection='own-fold raw-count sample Fano moments; scale runs use own-fold ranked prefixes',
            perturbation_rows_requested=False, preparation_is_not_discovery=True)
        return save_prepared(path, prepared.matrix, prepared.genes, cells, labels, metadata, prepared.feature_tables)


def load_prepared(path, config):
    path = Path(path)
    metadata = json.loads((path/'data_manifest.json').read_text())
    if file_hash(path/'counts.npz') != metadata['count_matrix_sha256'] or file_hash(path/'identities.json') != metadata['identities_sha256']:
        raise ValueError('prepared data hash mismatch')
    identities = json.loads((path/'identities.json').read_text())
    labels = np.array(identities['fold_labels'])
    population = Population(sparse.load_npz(path/'counts.npz'), tuple(identities['genes']), tuple(identities['cells']))
    folds = {f: population.subset(np.flatnonzero(labels == f)) for f in ('A', 'B')}
    selections = {}
    if metadata.get('real_data_used'):
        for fold in ('A', 'B'):
            moment_file = f'feature_moments_{fold}.csv'
            if file_hash(path/moment_file) != metadata.get('feature_table_hashes', {}).get(moment_file):
                raise ValueError('feature moments hash mismatch')
            table = pd.read_csv(path/f'feature_moments_{fold}.csv')
            table['selection_metric'] = table.fano
            table['eligible'] = (table['mean'] > 0) & table.detection_rate.between(config.min_detection_rate, config.max_detection_rate)
            ranked = table.loc[table.eligible].sort_values(['selection_metric', 'gene'], ascending=[False, True])
            genes = tuple(ranked.head(config.hvg_pool_size).gene)
            if len(genes) != config.hvg_pool_size or not set(genes).issubset(identities['genes']):
                raise ValueError('prepared projection lacks eligible genes for this configuration; prepare a new run')
            ranks = {g: i+1 for i, g in enumerate(ranked.gene)}
            table['rank'] = pd.array([ranks.get(g) for g in table.gene], dtype='Int64')
            table['selected'] = table.gene.isin(genes)
            table['fold'], table['selection_method'] = fold, HVG_METHOD
            parameters = dict(n_top=config.hvg_pool_size, min_detection_rate=config.min_detection_rate,
                max_detection_rate=config.max_detection_rate, variance_ddof=1, tie_breaker='gene_lexical',
                fit_population='discovery_fold_only', implementation='streamed_own_fold_moments')
            table['selection_parameters'] = canonical(parameters)
            selections[fold] = HVGSelection(genes, table, dict(fold=fold, method=HVG_METHOD,
                n_discovery_cells=len(folds[fold].cell_ids), n_input_genes=len(table),
                n_selected=len(genes), n_eligible=len(ranked), parameters=parameters))
    return folds, selections, metadata
