"""Local synthetic acceptance run; never reads Replogle or perturbation data."""
import argparse
from itertools import product
from pathlib import Path
import time

import numpy as np
import pandas as pd

from clue_discovery.nt_reference import split_nt_twofold, fit_twofold_nt
from clue_discovery.v02 import Population
from .run import (FORMAL_CONFIG, ROOT_SEED, choose_modules, code_hashes, effective_config,
                  environment, make_output, save)


def main(run_dir, kind='parity'):
    output = make_output(run_dir)
    start = time.monotonic()
    states = np.array(list(product((0, 1), repeat=4)), dtype=np.uint8)
    if kind == 'parity':
        # Strictly positive distribution with genuine 3- and 4-way log contrasts.
        s3 = (-1) ** states[:, :3].sum(axis=1).astype(int)
        s4 = (-1) ** states.sum(axis=1).astype(int)
        counts = np.rint(600 * (1 + .4*s3 + .3*s4)).astype(int)
        matrix = np.repeat(states, counts, axis=0)
    elif kind == 'sparse':
        matrix = np.repeat(np.array([[0, 0, 0, 0], [1, 1, 1, 1]], dtype=np.uint8), 4800, axis=0)
    else:
        raise ValueError('unknown synthetic scenario')
    cells = tuple(f'synthetic:{kind}:{i}' for i in range(len(matrix)))
    population = Population(matrix, tuple('ABCD'), cells)
    batches = np.array([f'GEM{i%48:02}' for i in range(len(matrix))])
    a, b = split_nt_twofold(population, random_seed=ROOT_SEED, strata=batches)
    folds = {'A': a, 'B': b}
    modules = choose_modules(folds, output, FORMAL_CONFIG, module_size=4)
    root = Path(__file__).resolve().parents[1]
    hashes = code_hashes(root)
    versions = environment()
    lookup = {cell: name for name, fold in folds.items() for cell in fold.cell_ids}
    pd.DataFrame(dict(cell_id=cells, batch=batches, fold=[lookup[c] for c in cells])).to_csv(
        output/'nt_fold_membership.csv.gz', index=False, compression={'method': 'gzip', 'mtime': 0})
    save(output/'nt_fold_manifest.json', dict(
        dataset=f'SYNTHETIC {kind} acceptance test; not real NT', source_shape=list(matrix.shape),
        run_role='synthetic_validation', scenario=kind, nt_cells=len(matrix),
        fold_counts={name: len(pop.cell_ids) for name, pop in folds.items()},
        fold_cell_ids={name: pop.cell_ids for name, pop in folds.items()}, split_seed=ROOT_SEED,
        split_design='GEM-stratified two-fold', config=effective_config(FORMAL_CONFIG),
        module_genes=modules, module_intersection=sorted(set(modules['A']) & set(modules['B'])),
        synthetic_module_size=4, formal_real_module_size=12,
        software_versions=versions, code_hashes=hashes, nt_only=True,
        no_perturbation_analysis=True, real_expression_accessed=False,
        statistics_metadata_file='nt_reference_metadata.json'))
    save(output/'environment.json', versions)
    save(output/'code_hashes.json', hashes)
    result = fit_twofold_nt(a, b, candidate_genes_a=modules['A'], candidate_genes_b=modules['B'],
                           config=FORMAL_CONFIG, checkpoint_dir=output)
    result.write(output)
    cross = result.cross_fold_summary
    if kind == 'parity':
        for order in (3, 4):
            if not ((cross.order == order) & cross.bidirectionally_rediscovered).any():
                raise AssertionError(f'known synthetic order {order} structure did not replicate bidirectionally')
    elif len(cross):
        raise AssertionError('unestimable sparse tables should not generate locked candidates')
    if any(len(v) != 1000 for v in result.bootstrap_distributions.values()):
        raise AssertionError('formal-sized bootstrap distributions missing')
    if hashes != code_hashes(root):
        raise RuntimeError('code or protocol changed during synthetic acceptance run')
    save(output/'execution_status.json', dict(complete=True, run_role='synthetic_validation',
         scenario=kind, acceptance_passed=True, n_bootstrap=1000,
         elapsed_seconds=time.monotonic()-start, real_expression_accessed=False))
    print(f'SYNTHETIC {kind}: acceptance passed; results in {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--kind', choices=('parity', 'sparse'), default='parity')
    args = parser.parse_args()
    main(args.run_dir, args.kind)
