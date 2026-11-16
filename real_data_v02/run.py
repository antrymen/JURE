"""Execute the pre-specified v0.2 real-data audit without changing algorithm thresholds."""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

import anndata as ad
import h5py
import numpy as np
import pandas as pd
from scipy import sparse

from clue_discovery.v02 import Population, ReferenceConfig, split_reference, fit_reference, test_perturbations
from clue_discovery.v02.reference import canonical_json, write_table
from clue_discovery.statistics import benjamini_hochberg
from real_data_test.prepare import SOURCE_MD5, file_hash, checked_counts
from .diagnostics import locked_nt_diagnostic


OLD_TARGETS = ['CDAN1', 'NDUFB3', 'ELP2', 'MCM10', 'SRSF11', 'TRRAP']


def save(path, value):
    Path(path).write_text(canonical_json(value) + '\n')


def event(name, **values):
    print(json.dumps(dict(stage=name, **values), ensure_ascii=False), flush=True)


def extract(data, rows, columns=None):
    """Read contiguous allowed row ranges only; never load excluded-target counts."""
    rows = np.asarray(rows, dtype=int)
    if not len(rows) or np.any(np.diff(rows) <= 0):
        raise ValueError('extraction requires sorted unique nonempty row indices')
    runs = np.split(rows, np.flatnonzero(np.diff(rows) != 1) + 1)
    matrices, totals, detected = [], [], []
    for run in runs:
        for offset in range(0, len(run), 4096):
            part = run[offset:offset+4096]
            block = checked_counts(data.X[int(part[0]):int(part[-1])+1])
            totals.extend(np.asarray(block.sum(axis=1)).ravel().tolist())
            detected.extend(block.getnnz(axis=1).tolist())
            matrices.append(block if columns is None else block[:, columns])
    return sparse.vstack(matrices, format='csr'), np.asarray(totals), np.asarray(detected)


def make_population(matrix, rows, obs, genes):
    return Population(matrix, tuple(genes), tuple(obs.index[rows].astype(str)))


def cached_counts_reader(source, data, resources):
    """Keep dense HDF5 chunks cached without changing any requested row slices."""
    # HDF5 reuses an already-open file's cache settings. Close the metadata
    # reader first; AnnData retains obs/var and can reopen a sparse X lazily.
    data.file.close()
    handle = resources.enter_context(h5py.File(source, 'r', rdcc_nbytes=128*1024**2,
                                               rdcc_nslots=100003))
    values = handle['X']
    return SimpleNamespace(X=values) if isinstance(values, h5py.Dataset) else data


def run(source, run_dir, project_root):
    with ExitStack() as resources:
        return _run(source, run_dir, project_root, resources)


def _run(source, run_dir, project_root, resources):
    start = time.monotonic()
    root, output = Path(project_root), Path(run_dir)
    output.mkdir(parents=True, exist_ok=True)
    if (output/'manifest.json').exists():
        raise FileExistsError('immutable run exists; use a new directory for a new run')
    config = ReferenceConfig(random_seed=20260927)
    hashes = {str(p.relative_to(root)): file_hash(p) for folder in ['clue_discovery', 'real_data_v02']
              for p in sorted((root/folder).rglob('*')) if p.is_file() and p.suffix in ('.py', '.md')}
    save(output/'code_hashes.json', hashes)
    if file_hash(source, 'md5') != SOURCE_MD5:
        raise ValueError('source checksum mismatch')
    event('source_checksum_verified')
    data = ad.read_h5ad(source, backed='r')
    resources.callback(data.file.close)
    count_reader = cached_counts_reader(source, data, resources)
    obs = data.obs.copy()
    if not obs.index.is_unique or not data.var_names.is_unique:
        raise ValueError('nonunique source cell/gene identities')
    if obs[['gene', 'guide_id', 'batch']].isna().any().any():
        raise ValueError('source metadata missing')
    isolation = json.loads((root/'dataset_audit/combined_audit.json').read_text())
    aliases = isolation['aliases']
    excluded = sorted({r['canonical'] for r in isolation['rows']} | set(aliases))
    labels = obs.gene.astype(str).replace(aliases).to_numpy()
    batches = obs.batch.astype(str).to_numpy()
    expected = json.loads((root/'dataset_audit/replogle_counts.json').read_text())['TabB_K562_day6_library']
    counts = pd.Series(labels).value_counts()
    assert len(obs) == expected['total'] and counts['non-targeting'] == expected['control']
    assert all(counts[aliases.get(g, g)] == n for g, n in expected['counts'].items())
    nt_rows = np.flatnonzero(labels == 'non-targeting')
    if 'nperts' in obs:
        assert (obs.iloc[nt_rows].nperts.to_numpy() == 0).all()
    targets = sorted(set(labels)-set(excluded)-{'non-targeting'})
    pd.DataFrame({'target': sorted(set(labels)-{'non-targeting'})}).assign(
        n_cells=lambda t:t.target.map(counts), excluded=lambda t:t.target.isin(excluded)
    ).to_csv(output/'all_target_counts.csv', index=False)

    # Identity-only split. No NT expression, especially validation/test, has been read.
    dummy = make_population(sparse.csr_matrix((len(nt_rows), 1)), nt_rows, obs, ['__identity_only__'])
    parts = split_reference(dummy, config, strata=batches[nt_rows])
    row_lookup = {cell: i for i, cell in enumerate(obs.index)}
    split_rows = {name: np.array(sorted(row_lookup[cell] for cell in part.cell_ids))
                  for name, part in zip(['discovery', 'validation', 'test'], parts)}
    split_table = pd.DataFrame([dict(cell_id=str(obs.index[i]), source_row=int(i), partition=name, batch=batches[i])
                               for name, rows in split_rows.items() for i in rows])
    split_table.to_csv(output/'nt_split_membership.csv.gz', index=False)
    event('split_fixed', counts={k:len(v) for k,v in split_rows.items()}, n_targets=len(targets))
    dmatrix, _, _ = extract(count_reader, split_rows['discovery'])
    n = dmatrix.shape[0]
    mean = np.asarray(dmatrix.mean(axis=0)).ravel()
    variance = (np.asarray(dmatrix.astype(float).power(2).mean(axis=0)).ravel()-mean**2)*n/(n-1)
    detection = np.asarray((dmatrix>0).mean(axis=0)).ravel()
    qc = pd.DataFrame(dict(gene=data.var_names, mean=mean, variance=variance, detection_rate=detection,
                           fano=np.divide(variance, mean, out=np.zeros_like(mean), where=mean>0)))
    qc['eligible'] = qc.detection_rate.between(config.min_detection_rate, config.max_detection_rate)
    module = qc[qc.eligible].sort_values(['fano', 'gene'], ascending=[False, True]).head(12).gene.tolist()
    if len(module) != 12:
        raise ValueError('fewer than 12 eligible discovery genes')
    qc['selected'] = qc.gene.isin(module)
    qc.to_csv(output/'discovery_feature_selection.csv', index=False)
    columns = [data.var_names.get_loc(g) for g in module]
    discovery = make_population(dmatrix[:, columns].copy(), split_rows['discovery'], obs, module)
    del dmatrix
    vmatrix, _, _ = extract(count_reader, split_rows['validation'], columns)
    validation = make_population(vmatrix, split_rows['validation'], obs, module)
    # fit_reference inspects only reserved test identities, never its expression values.
    test_placeholder = make_population(sparse.csr_matrix((len(split_rows['test']), len(module))), split_rows['test'], obs, module)
    manifest = dict(protocol='real_data_v02/PROTOCOL.md', source=str(source), source_shape=list(data.shape),
                    source_md5=SOURCE_MD5, source_sha256=file_hash(source), module_genes=module,
                    config=asdict(config), n_targets=len(targets), target_ids=targets,
                    excluded_perturbations=excluded, nt_split_counts={k:len(v) for k,v in split_rows.items()},
                    code_sha256=hashes, split_sha256=file_hash(output/'nt_split_membership.csv.gz'),
                    feature_selection='discovery only, raw count Fano top12 after detection QC',
                    cpa_expression_accessed=False, biology_replication='not_available',
                    reference_control='pooled reserved test NT, no target-specific batch matching')
    save(output/'manifest.json', manifest)
    event('module_frozen', module_genes=module)
    t0 = time.monotonic()
    reference = fit_reference(discovery, validation, test_placeholder, candidate_genes=module, config=config)
    reference.write(output/'reference')
    catalogue = reference.catalogue
    event('reference_complete', seconds=time.monotonic()-t0, n_patterns=len(catalogue.patterns),
          order_summary=reference.order_summary.to_dict('records'))
    manifest['catalogue_sha256'] = catalogue.sha256
    manifest['reference_seconds'] = time.monotonic()-t0

    # Test/perturbation values are read only after catalogue creation.
    test_matrix, test_total, test_detected = extract(count_reader, split_rows['test'], columns)
    reference_test = make_population(test_matrix, split_rows['test'], obs, module)
    manifest['nt_test_median_total_counts'] = float(np.median(test_total))
    manifest['nt_test_median_detected_genes'] = float(np.median(test_detected))
    allowed = np.flatnonzero(np.isin(labels, targets))
    matrix, totals, detected = extract(count_reader, allowed, columns)
    data.file.close()
    retained_labels = labels[allowed]
    control_batch = pd.Series(batches[split_rows['test']]).value_counts(normalize=True)
    qc_rows, perturbations = [], {}
    for target in targets:
        ix = np.flatnonzero(retained_labels == target)
        source_rows = allowed[ix]
        perturbations[target] = make_population(matrix[ix], source_rows, obs, module)
        batch = pd.Series(batches[source_rows]).value_counts(normalize=True)
        union = control_batch.index.union(batch.index)
        qc_rows.append(dict(target=target, n_cells=len(ix), median_total_counts=float(np.median(totals[ix])),
                            median_detected_genes=float(np.median(detected[ix])),
                            batch_total_variation=float((batch.reindex(union,fill_value=0)-control_batch.reindex(union,fill_value=0)).abs().sum()/2),
                            missing_control_batch_cells=int(sum(x not in control_batch.index for x in batches[source_rows]))))
    pd.DataFrame(qc_rows).to_csv(output/'target_qc.csv', index=False)
    membership = pd.DataFrame(dict(cell_id=obs.index[allowed].astype(str), source_row=allowed, target=retained_labels,
                                   batch=batches[allowed], total_counts=totals, detected_genes=detected))
    membership.to_csv(output/'perturbation_membership.csv.gz', index=False)
    event('testing_inputs_ready', n_targets=len(perturbations), n_cells=len(allowed), n_tests=len(perturbations)*len(catalogue.patterns))
    save(output/'manifest.json', manifest)
    t0 = time.monotonic()
    testing = test_perturbations(catalogue, reference_test, perturbations)
    testing.write(output/'testing')
    manifest['testing_seconds'] = time.monotonic()-t0
    event('testing_complete', seconds=manifest['testing_seconds'], n_candidates=int((testing.shifts.status=='candidate_shift').sum()))
    run_nulls(catalogue, reference_test, perturbations, output/'null_diagnostics')
    run_downsampling(catalogue, reference_test, perturbations, testing.shifts, config, output/'downsampling')
    manifest['elapsed_seconds'] = time.monotonic()-start
    save(output/'manifest.json', manifest)
    # A post-run manifest includes only reporting values; the original selections are never changed.
    for filename, digest in hashes.items():
        assert file_hash(root/filename) == digest, f'code changed during run: {filename}'
    save(output/'execution_status.json', dict(complete=True, algorithm_changed=False, n_targets=len(targets),
                                             n_patterns=len(catalogue.patterns), n_tests=len(testing.shifts)))
    event('all_stages_complete', seconds=manifest['elapsed_seconds'])


def run_nulls(catalogue, reference_test, perturbations, output):
    output.mkdir(parents=True, exist_ok=True)
    summaries, memberships = [], []
    n = len(reference_test.cell_ids)
    designs = [(f'halfsplit_s{seed}', n//2, seed) for seed in [101,202,303]]
    designs += [(f'capacity_{t}', len(perturbations[t].cell_ids), 900+i) for i,t in enumerate(OLD_TARGETS)]
    for label, size, seed in designs:
        if size >= n:
            raise ValueError('not enough test NT cells for a disjoint null')
        perm = np.random.default_rng(seed).permutation(n)
        p, c = reference_test.subset(sorted(perm[:size])), reference_test.subset(sorted(perm[size:]))
        frame = locked_nt_diagnostic(catalogue, c, p, label)
        write_table(frame, output/(label+'.csv'))
        summaries.append(dict(run_id=label, n_control=len(c.cell_ids), n_pseudo_pert=len(p.cell_ids), n_tests=len(frame),
                              n_candidates=int((frame.status=='candidate_shift').sum()),
                              n_candidates_higher=int(((frame.status=='candidate_shift')&(frame.order>=3)).sum())))
        memberships.extend(dict(run_id=label, condition=name, cell_id=cell) for name,pop in [('control',c),('pseudo_perturbation',p)] for cell in pop.cell_ids)
    pd.DataFrame(summaries).to_csv(output/'summary.csv', index=False)
    pd.DataFrame(memberships).to_csv(output/'cell_membership.csv.gz', index=False)
    save(output/'metadata.json', dict(parent_catalogue_sha256=catalogue.sha256, catalogue_changed=False,
                                      fdr_family='all frozen patterns within each diagnostic; not main family',
                                      source='reserved NT test only; within-comparison groups disjoint; comparisons reuse cells'))
    event('null_diagnostics_complete', summaries=summaries)


def reclassify(row, config):
    if row.support < config.min_support: return 'insufficient_support'
    if abs(row.delta_frequency) < config.min_delta or row.q_value_shift > config.alpha_shift: return 'screened_out'
    if row.delta_sign_stability < config.min_sign_stability or not (row.bootstrap_delta_ci_low>0 or row.bootstrap_delta_ci_high<0): return 'unstable_shift'
    return 'candidate_shift'


def run_downsampling(catalogue, reference_test, perturbations, main, config, output):
    output.mkdir(parents=True, exist_ok=True)
    summaries, memberships = [], []
    unaffected = main.loc[~main.perturbation.isin(OLD_TARGETS)].p_value_shift.to_numpy(dtype=float)
    for fraction in [.5,.25]:
        for seed in [101,202,303]:
            label = f'f{int(fraction*100)}_s{seed}'
            subset = {}
            for target in OLD_TARGETS:
                pop = perturbations[target]
                # Same seed gives nested 25%/50% cell subsets for each target.
                perm = np.random.default_rng(seed).permutation(len(pop.cell_ids))
                subset[target] = pop.subset(sorted(perm[:int(len(perm)*fraction)]))
                memberships.extend(dict(run_id=label, target=target, cell_id=c) for c in subset[target].cell_ids)
            result = test_perturbations(catalogue, reference_test, subset)
            frame = result.shifts.copy()
            frame['q_value_subset_only'] = frame.q_value_shift
            if len(frame):
                q = benjamini_hochberg(np.r_[unaffected, frame.p_value_shift.to_numpy()])
                frame['q_value_shift'] = q[len(unaffected):]
                frame['status'] = frame.apply(lambda row: reclassify(row, config), axis=1)
            write_table(frame, output/(label+'.csv'))
            for target in OLD_TARGETS:
                baseline = main[(main.perturbation==target)&(main.order>=3)&(main.status=='candidate_shift')]
                small = frame[(frame.perturbation==target)&(frame.order>=3)]
                accepted = small[small.status=='candidate_shift']
                ids = set(baseline.reference_id)
                shared = baseline[['reference_id','delta_frequency']].merge(small[['reference_id','delta_frequency']], on='reference_id',suffixes=('_full','_down'))
                recovered = len(ids & set(accepted.reference_id))
                summaries.append(dict(run_id=label,target=target,fraction=fraction,seed=seed,n_cells=len(subset[target].cell_ids),
                                      baseline_candidates=len(ids), downsample_candidates=len(accepted), recovered=recovered,
                                      recall=recovered/len(ids) if ids else None,
                                      direction_consistency=float((shared.delta_frequency_full*shared.delta_frequency_down>0).mean()) if len(shared) else None))
    pd.DataFrame(summaries).to_csv(output/'summary.csv', index=False)
    pd.DataFrame(memberships).to_csv(output/'cell_membership.csv.gz', index=False)
    save(output/'metadata.json',dict(catalogue_sha256=catalogue.sha256, reference_test_unchanged=True,
                                     fdr_family='same main target x state universe; update six downsampled targets, others keep main p-values',
                                     interpretation='sensitivity scenario, not independent replication'))
    event('downsampling_complete')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True)
    parser.add_argument('--run-dir',required=True)
    parser.add_argument('--project-root',default='.')
    args = parser.parse_args()
    run(args.source,args.run_dir,args.project_root)
