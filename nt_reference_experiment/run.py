"""Prepare and execute the fixed, NT-only two-fold experiment on verified raw counts."""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
import gc
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys
import time
from types import SimpleNamespace

import anndata as ad
import h5py
import numpy as np
import pandas as pd
from scipy import sparse

from clue_discovery.nt_reference import split_nt_twofold, select_fano_module, fit_twofold_nt
from clue_discovery.v02 import Population, ReferenceConfig
from clue_discovery.v02.reference import canonical_json
from real_data_test.prepare import SOURCE_MD5, file_hash
from .low_memory import prepare_nt_low_memory


ROOT_SEED = 20260927
FORMAL_CONFIG = ReferenceConfig(random_seed=ROOT_SEED, max_order=4, n_bootstrap=1000)
SOURCE_SHAPE = (310385, 8563)
SOURCE_NT_CELLS = 10691
HDF5_CACHE_BYTES = 64 * 1024**2


def save(path, value):
    Path(path).write_text(canonical_json(value) + '\n')


def event(stage, **values):
    print(json.dumps(dict(stage=stage, **values), ensure_ascii=False), flush=True)


def environment():
    packages = {}
    for name in ('numpy', 'scipy', 'pandas', 'anndata', 'h5py', 'matplotlib', 'pytest'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return dict(python=sys.version, platform=platform.platform(), packages=packages)


def code_hashes(project_root):
    root = Path(project_root)
    return {str(p.relative_to(root)): file_hash(p)
            for folder in ('clue_discovery', 'real_data_test', 'real_data_v02', 'nt_reference_experiment')
            for p in sorted((root/folder).rglob('*'))
            if p.is_file() and p.suffix in ('.py', '.md', '.sh')}


def effective_config(config):
    # Three-way split and perturbation testing fields belong only to the reused
    # v0.2 config type; none defines this experiment's two-fold design.
    unused = {'split_fractions', 'shift_fdr_scope', 'max_tests', 'min_delta', 'alpha_shift', 'frequency_epsilon'}
    return {k: v for k, v in asdict(config).items() if k not in unused}


def make_output(path):
    folder = Path(path)
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.iterdir()):
        raise FileExistsError('run directory must be empty; never overwrite a previous experiment')
    return folder


def choose_modules(folds, output, config, module_size=12):
    modules = {}
    for name, population in folds.items():
        module, qc = select_fano_module(population, module_size=module_size,
                                       min_detection_rate=config.min_detection_rate,
                                       max_detection_rate=config.max_detection_rate)
        if len(module) != module_size:
            raise ValueError(f'{name} has fewer than {module_size} eligible genes')
        modules[name] = list(module)
        qc.to_csv(output/f'fold_{name}_feature_selection.csv', index=False)
    return modules


def read_source_metadata(handle):
    """Load obs and gene identities only; never materialize uns/obsm/raw/layers."""
    obs = ad.io.read_elem(handle['obs'])
    var = handle['var']
    index_key = var.attrs['_index']
    if isinstance(index_key, bytes):
        index_key = index_key.decode()
    genes = pd.Index(ad.io.read_elem(var[index_key]).astype(str))
    values = handle['X']
    reader = SimpleNamespace(X=values if isinstance(values, h5py.Dataset)
                             else ad.io.sparse_dataset(values))
    return obs, genes, reader


def run(source, run_dir, project_root='.'):
    """Only the known Replogle source is accepted for the formal experiment."""
    output = make_output(run_dir)
    start = time.monotonic()
    root = Path(project_root).resolve()
    try:
        with ExitStack() as resources:
            config = FORMAL_CONFIG
            hashes, versions = code_hashes(root), environment()
            save(output/'code_hashes.json', hashes)
            save(output/'environment.json', versions)
            shutil.copyfile(root/'nt_reference_experiment/PROTOCOL.md', output/'PROTOCOL.md')
            if file_hash(source, 'md5') != SOURCE_MD5:
                raise ValueError('source checksum mismatch; formal experiment requires the frozen Replogle source')
            source_sha256 = file_hash(source)
            handle = resources.enter_context(h5py.File(source, 'r', rdcc_nbytes=HDF5_CACHE_BYTES,
                                                       rdcc_nslots=100003))
            obs, gene_names, reader = read_source_metadata(handle)
            source_shape = tuple(reader.X.shape)
            if source_shape != SOURCE_SHAPE or not obs.index.is_unique or not gene_names.is_unique:
                raise ValueError('source shape or identities do not match the frozen source')
            if not {'gene', 'batch', 'guide_id', 'nperts'} <= set(obs.columns):
                raise ValueError('required NT metadata missing')
            rows = np.flatnonzero(obs.gene.astype(str).to_numpy() == 'non-targeting')
            if len(rows) != SOURCE_NT_CELLS or not (obs.iloc[rows].nperts.to_numpy() == 0).all():
                raise ValueError('NT identity/count mismatch')
            nt_meta = obs.iloc[rows].copy()
            if nt_meta[['batch', 'guide_id']].isna().any().any():
                raise ValueError('NT batch/guide metadata missing')
            cells = tuple(nt_meta.index.astype(str))
            dummy = Population(sparse.csr_matrix((len(cells), 1)), ('__identity_only__',), cells)
            a_ids, b_ids = split_nt_twofold(dummy, random_seed=ROOT_SEED,
                                           strata=nt_meta.batch.astype(str).to_numpy())
            id_to_fold = {c: name for name, fold in [('A', a_ids), ('B', b_ids)] for c in fold.cell_ids}
            if len(id_to_fold) != len(cells) or set(a_ids.cell_ids) & set(b_ids.cell_ids):
                raise ValueError('two-fold identity integrity failed')
            membership = pd.DataFrame(dict(cell_id=cells, source_row=rows,
                                           batch=nt_meta.batch.astype(str).to_numpy(),
                                           fold=[id_to_fold[c] for c in cells]))
            membership.to_csv(output/'nt_fold_membership.csv.gz', index=False,
                              compression={'method': 'gzip', 'mtime': 0})
            preanalysis = dict(dataset='Replogle K562 Essential day 6', source_shape=list(source_shape),
                               source_md5=SOURCE_MD5, source_sha256=source_sha256,
                               nt_cells=len(cells), split_design='GEM-stratified two-fold',
                               split_seed=ROOT_SEED, fold_counts={'A': len(a_ids.cell_ids), 'B': len(b_ids.cell_ids)},
                               fold_cell_ids={'A': a_ids.cell_ids, 'B': b_ids.cell_ids},
                               config=effective_config(config), module_selection='own-fold raw-count Fano top12',
                               software_versions=versions, code_hashes=hashes,
                               perturbation_cells_materialized=False, no_perturbation_analysis=True,
                               run_role='development_nt_twofold', nt_only=True)
            preanalysis['memory_strategy'] = dict(mode='two_pass_streaming', chunk_rows=128,
                hdf5_cache_bytes=HDF5_CACHE_BYTES, full_expression_matrix_materialized=False,
                metadata_scope='obs and var index only', scientific_parameters_unchanged=True)
            save(output/'preanalysis_manifest.json', preanalysis)
            event('nt_fold_ids_frozen', fold_counts=preanalysis['fold_counts'])

            # First pass accumulates fold-specific Fano moments in bounded blocks;
            # second pass keeps only the frozen module union (at most 24 genes).
            del obs
            gc.collect()
            prepared = prepare_nt_low_memory(reader, rows, membership.fold.to_numpy(),
                                             tuple(gene_names), config, chunk_rows=128)
            modules = prepared.modules
            for name, qc in prepared.feature_tables.items():
                qc.to_csv(output/f'fold_{name}_feature_selection.csv', index=False)
            population = Population(prepared.matrix, prepared.genes, cells)
            lookup = {cell: i for i, cell in enumerate(cells)}
            folds = {name: population.subset([lookup[c] for c in ids.cell_ids])
                     for name, ids in [('A', a_ids), ('B', b_ids)]}
            nt_meta['cell_id'] = cells
            nt_meta = nt_meta[['cell_id'] + [c for c in nt_meta.columns if c != 'cell_id']]
            nt_meta['nt_reference_fold'] = [id_to_fold[c] for c in cells]
            nt_meta['measured_total_counts'] = prepared.totals
            nt_meta['measured_detected_genes'] = prepared.detected
            nt_meta.to_csv(output/'nt_cell_metadata.csv.gz', index=False,
                           compression={'method': 'gzip', 'mtime': 0})
            manifest = dict(preanalysis, module_genes=modules,
                            preparation_memory_strategy=prepared.memory_strategy,
                            module_intersection=sorted(set(modules['A']) & set(modules['B'])),
                            preanalysis_manifest_sha256=file_hash(output/'preanalysis_manifest.json'),
                            fold_membership_sha256=file_hash(output/'nt_fold_membership.csv.gz'),
                            statistics_metadata_file='nt_reference_metadata.json',
                            bootstrap_seed_policy='all actual fold/stage/gene-set RNG seeds recorded in statistics metadata and estimability table')
            save(output/'nt_fold_manifest.json', manifest)
            handle.close()
            del prepared, population, reader
            gc.collect()
            event('both_modules_frozen', module_genes=modules)
            result = fit_twofold_nt(folds['A'], folds['B'], candidate_genes_a=modules['A'],
                                   candidate_genes_b=modules['B'], config=config, checkpoint_dir=output)
            result.write(output)
            for filename, digest in hashes.items():
                if file_hash(root/filename) != digest:
                    raise RuntimeError(f'code or protocol changed during run: {filename}')
            save(output/'execution_status.json', dict(complete=True, run_role='development_nt_twofold',
                 analysis_seconds=time.monotonic()-start, nt_only=True, no_perturbation_analysis=True,
                 original_code_unchanged_during_run=True, n_bootstrap=config.n_bootstrap))
            event('nt_twofold_complete', seconds=time.monotonic()-start)
            return result
    except BaseException as exc:
        save(output/'execution_status.json', dict(complete=False, elapsed_seconds=time.monotonic()-start,
                                                  error_type=type(exc).__name__, error=str(exc)))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--project-root', default='.')
    args = parser.parse_args()
    run(args.source, args.run_dir, args.project_root)
