"""Reproduce the descriptive Day 6 landscape without external services."""
from __future__ import annotations

import os
for _name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
              'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_name] = '1'

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import platform
import time

import numpy as np
import pandas as pd
import scipy
from scipy.spatial.distance import squareform
from scipy.stats import spearmanr

from clue_discovery.v03.artifacts import digest
from .core import (adjusted_rand, cut_labels, hierarchy, matrix_views,
                   resampling_stability, silhouette_from_tree, signed_candidate_jaccard,
                   stable_group_ids)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / 'outputs/perturbation_scan_day6_v01_20260927'
DEFAULT_OUTPUT = ROOT / 'outputs/broad_screening_v01_landscape_20260927'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    def default(x):
        if isinstance(x, np.generic):
            return x.item()
        if isinstance(x, np.ndarray):
            return x.tolist()
        raise TypeError(type(x).__name__)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=default,
                                    allow_nan=False) + '\n')


def load_source(source):
    run = source / 'remote/outputs/day6_scan'
    files = [source / 'FINAL_AUDIT.json', run / 'run_status.json', run / 'PROTOCOL_FROZEN.json',
             run / 'counts_frozen.json', run / 'counts/identities.json', run / 'counts/counts.npz',
             run / 'scan/statistics.npz', run / 'scan/summary.json', run / 'scan/candidates.jsonl',
             run / 'scan/testing_family_frozen.json']
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in files}
    audit = json.loads(files[0].read_text())
    status = json.loads((run / 'run_status.json').read_text())
    summary = json.loads((run / 'scan/summary.json').read_text())
    manifest = json.loads((run / 'PROTOCOL_FROZEN.json').read_text())
    identity = json.loads((run / 'counts/identities.json').read_text())
    if audit['status'] != 'passed' or status['status'] != 'complete':
        raise ValueError('source has not completed and passed audit')
    for name, expected in json.loads((run / 'counts_frozen.json').read_text()).items():
        if sha(run / 'counts' / name) != expected:
            raise ValueError(f'count identity hash mismatch: {name}')
    if digest(identity['patterns']) != summary['catalogue_digest']:
        raise ValueError('catalogue digest mismatch')
    with np.load(run / 'scan/statistics.npz', allow_pickle=False) as z:
        stats = {k: z[k].copy() for k in z.files}
    targets = np.array(identity['targets'])
    patterns = identity['patterns']
    refs = np.array([p['reference_id'] for p in patterns])
    candidate = stats['candidate']
    if candidate.shape != (len(targets), len(refs)) or candidate.size != summary['comparisons']:
        raise ValueError('source matrix shape mismatch')
    if len(set(targets)) != len(targets) or len(set(refs)) != len(refs):
        raise ValueError('duplicate source identities')
    if len(targets) != summary['targets'] or len(refs) != summary['patterns']:
        raise ValueError('summary identity mismatch')
    if int(candidate.sum()) != summary['exploratory_candidates'] or int(candidate.any(1).sum()) != summary['candidate_targets']:
        raise ValueError('candidate count mismatch')
    if summary['confirmed_clues'] or summary['confirmatory'] or summary['biological_replication']:
        raise ValueError('unexpected upstream inference scope')
    if not np.array_equal(candidate, stats['tested'] &
                          (stats['selected_holm_exploratory'] <= summary['config']['alpha'])):
        raise ValueError('candidate mask does not match frozen scan gate')
    td, pdict = {t: i for i, t in enumerate(targets)}, {r: i for i, r in enumerate(refs)}
    seen = set()
    with (run / 'scan/candidates.jsonl').open() as f:
        for line in f:
            c = json.loads(line)
            i, j = td[c['target']], pdict[c['reference_id']]
            if (i, j) in seen or not candidate[i, j]:
                raise ValueError('duplicate or noncandidate JSONL record')
            seen.add((i, j))
            for field in ('delta', 'matched_nt_frequency'):
                if not np.isclose(c[field], stats[field][i, j], atol=1e-14, rtol=1e-12):
                    raise ValueError(f'JSONL {field} mismatch')
            if c['genes'] != patterns[j]['genes'] or c['states'] != patterns[j]['states']:
                raise ValueError('JSONL pattern identity mismatch')
            if c['eligible_as_confirmed_clue'] or c['nt_selection_adjusted'] or c['external_validation_status'] != 'not_performed':
                raise ValueError('unexpected candidate scientific status')
    if len(seen) != int(candidate.sum()) or len(seen) != audit['candidates_verified']:
        raise ValueError('incomplete JSONL or audit mismatch')
    return stats, identity, summary, manifest, hashes


def distribution(values):
    a = np.asarray(values)
    return dict(n=len(a), mean=float(a.mean()), median=float(np.median(a)),
                q25=float(np.quantile(a, .25)), q75=float(np.quantile(a, .75)),
                min=int(a.min()), max=int(a.max()))


def concentration(values, unit):
    values = np.sort(np.asarray(values))[::-1]
    cumulative = np.cumsum(values)
    total = int(cumulative[-1])
    rows = [dict(unit=unit, rank=i + 1, candidates=int(n), cumulative_candidates=int(cumulative[i]),
                 cumulative_fraction=float(cumulative[i] / total)) for i, n in enumerate(values)]
    cutoffs = {f'top_{k}': float(cumulative[min(k, len(values)) - 1] / total)
               for k in (1, 3, 5, 10, 20, 50, 100)}
    needed = {f'number_for_{int(p * 100)}pct': int(np.searchsorted(cumulative, p * total) + 1)
              for p in (.5, .7, .8, .9)}
    return rows, dict(**cutoffs, **needed)


def run(source, output):
    started = time.monotonic()
    if output.exists():
        raise FileExistsError('refusing to overwrite an existing landscape run')
    output.mkdir(parents=True)
    for d in ('matrices', 'tables', 'figures'):
        (output / d).mkdir()
    stat, identity, scan_summary, source_manifest, input_hashes = load_source(source)
    source_hashes = {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT / 'landscape_analysis').glob('*'))
                     if p.suffix in ('.py', '.md')}
    protocol = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        source=str(source.relative_to(ROOT)), source_inputs_sha256=input_hashes,
        analysis_sources_sha256=source_hashes, cutoff=.30, sensitivity_cutoffs=[.20, .30, .40, .50],
        target_distance='cosine', pattern_distance='Pearson correlation', linkage='average',
        clustering_input='continuous observed matched delta, not thresholded',
        seed=20260927, resampling_repetitions=50, model_calls=0, retrieval_calls=0,
        day8_accessed=False, biological_module_names_assigned=False,
        numpy=np.__version__, pandas=pd.__version__, scipy=scipy.__version__, python=platform.python_version())
    write_json(output / 'ANALYSIS_FROZEN.json', protocol)
    print('Inputs verified; protocol frozen.', flush=True)

    row_idx = np.flatnonzero(stat['candidate'].any(1))
    row_idx = row_idx[np.argsort(np.array(identity['targets'])[row_idx])]
    col_idx = np.argsort([p['reference_id'] for p in identity['patterns']])
    targets = np.array(identity['targets'])[row_idx]
    patterns = [identity['patterns'][j] for j in col_idx]
    refs = np.array([p['reference_id'] for p in patterns])
    names = np.array([p['pattern'] for p in patterns])
    triplets = np.array([' / '.join(sorted(p['genes'])) for p in patterns])
    triplet_sizes = Counter(triplets)
    n, m = len(targets), len(refs)
    sub = np.ix_(row_idx, col_idx)
    delta, mask, tested, reason = [stat[k][sub] for k in ('delta', 'candidate', 'tested', 'reason')]
    views = matrix_views(delta, mask, tested, reason)
    if not np.isfinite(delta).all():
        raise ValueError('main cohort has missing effects; no implicit imputation allowed')
    for name in ('observed', 'candidate_only', 'selection_encoded', 'candidate_mask', 'status'):
        pd.DataFrame(views[name], index=pd.Index(targets, name='target'), columns=refs).to_csv(
            output / 'matrices' / f'{name}.csv.gz', na_rep='NA')
    all_adequate = ((stat['target_n'] >= scan_summary['config']['min_pert_cells']) &
                    np.isfinite(stat['delta']).all(1) &
                    ~(stat['reason'] == 'insufficient_matched_NT').any(1))
    np.savez_compressed(output / 'matrices/all_targets_observed_and_masks.npz',
        targets=np.asarray(identity['targets']), reference_ids=np.array([p['reference_id'] for p in identity['patterns']]),
        delta=stat['delta'], candidate=stat['candidate'], tested=stat['tested'], reason=stat['reason'],
        target_n=stat['target_n'], adequate_target=all_adequate)
    pd.DataFrame([dict(reference_id=p['reference_id'], pattern=p['pattern'],
                      genes=json.dumps(p['genes']), states=json.dumps(p['states']), triplet=t)
                  for p, t in zip(patterns, triplets)]).to_csv(output / 'tables/pattern_identity.csv', index=False)

    enrich, deplete = mask & (delta > 0), mask & (delta < 0)
    rd, cd = mask.sum(1), mask.sum(0)
    pattern_table = pd.DataFrame(dict(reference_id=refs, pattern=names, triplet=triplets,
        candidate_targets=cd, enrichment_targets=enrich.sum(0), depletion_targets=deplete.sum(0),
        fraction_of_candidate_targets=cd / n, candidate_share=cd / mask.sum(),
        mean_delta=delta.mean(0), sd_delta=delta.std(0), maximum_abs_delta=np.abs(delta).max(0)))
    target_table = pd.DataFrame(dict(target=targets, n_cells=stat['target_n'][row_idx],
        candidates=rd, enrichment=enrich.sum(1), depletion=deplete.sum(1),
        candidate_triplets=[len(set(triplets[r])) for r in mask],
        rms_delta=np.sqrt(np.mean(delta ** 2, 1)), maximum_abs_delta=np.abs(delta).max(1),
        mean_candidate_pattern_prevalence=[float(cd[r].mean() / n) for r in mask],
        rare_patterns_le5_targets=(mask & (cd <= 5)).sum(1)))
    triplet_table = pattern_table.groupby('triplet', sort=True).agg(
        patterns=('reference_id', 'size'), candidate_patterns=('candidate_targets', lambda x: int((x > 0).sum())),
        candidates=('candidate_targets', 'sum'), enrichment=('enrichment_targets', 'sum'),
        depletion=('depletion_targets', 'sum')).reset_index()
    triplet_table['unique_candidate_targets'] = [int(mask[:, triplets == t].any(1).sum()) for t in triplet_table.triplet]
    conc_rows = []
    conc_summary = {}
    for values, unit in ((cd, 'patterns'), (rd, 'targets'), (triplet_table.candidates.values, 'triplets')):
        rows, concise = concentration(values, unit)
        conc_rows.extend(rows); conc_summary[unit] = concise
    pd.DataFrame(conc_rows).to_csv(output / 'tables/concentration.csv', index=False)

    row_tree = hierarchy(delta, 'cosine')
    col_tree = hierarchy(delta.T, 'correlation')
    if not row_tree['valid'].all() or not col_tree['valid'].all():
        raise ValueError('undefined profiles found; isolate them in the analysis contract before plotting')
    target_groups = stable_group_ids(row_tree['labels'], rd, targets, 'T')
    pattern_groups = stable_group_ids(col_tree['labels'], cd, refs, 'M')
    target_table['target_group'] = target_groups
    pattern_table['pattern_group'] = pattern_groups
    pd.DataFrame(dict(position=np.arange(n), target=targets[row_tree['order']],
                      group=target_groups[row_tree['order']])).to_csv(output / 'tables/target_heatmap_order.csv', index=False)
    pd.DataFrame(dict(position=np.arange(m), reference_id=refs[col_tree['order']],
                      pattern=names[col_tree['order']], group=pattern_groups[col_tree['order']])).to_csv(
                          output / 'tables/pattern_heatmap_order.csv', index=False)
    np.savez_compressed(output / 'matrices/linkage_and_order.npz', target_linkage=row_tree['linkage'],
        pattern_linkage=col_tree['linkage'], target_order=row_tree['order'], pattern_order=col_tree['order'])
    print(f'Clustering: {len(set(target_groups))} target groups; {len(set(pattern_groups))} pattern groups.', flush=True)

    # Candidate-count-weighted names above are display names, not an optimization of clustering.
    z = (delta - delta.mean(0)) / delta.std(0)
    group_summary = []
    module_scores = {}
    for group in sorted(set(pattern_groups)):
        ix = np.flatnonzero(pattern_groups == group)
        mass = int(cd[ix].sum())
        gene_count = Counter(g for j in ix for g in patterns[j]['genes'])
        module_scores[group] = z[:, ix].mean(1)
        best_patterns = sorted(ix, key=lambda j: (-int(cd[j]), refs[j]))[:6]
        best_targets = sorted(range(n), key=lambda i: (-int(mask[i, ix].sum()), -float(module_scores[group][i]), targets[i]))[:8]
        correlations = np.corrcoef(delta[:, ix].T) if len(ix) > 1 else None
        pair_values = correlations[np.triu_indices(len(ix), 1)] if correlations is not None else []
        cross_triplet = [correlations[a, b] for a in range(len(ix)) for b in range(a + 1, len(ix))
                         if triplets[ix[a]] != triplets[ix[b]]] if correlations is not None else []
        group_summary.append(dict(pattern_group=group, patterns=len(ix), triplets=len(set(triplets[ix])),
            candidate_patterns=int((cd[ix] > 0).sum()), candidates=mass,
            enrichment=int(enrich[:, ix].sum()), depletion=int(deplete[:, ix].sum()),
            candidate_fraction=mass / int(mask.sum()), candidate_targets=int(mask[:, ix].any(1).sum()),
            group_kind='provisional_response_module' if len(ix) >= 3 and len(set(triplets[ix])) >= 2 else 'small_or_single_triplet_group',
            mean_within_correlation=float(np.mean(pair_values)) if len(pair_values) else None,
            mean_cross_triplet_correlation=float(np.mean(cross_triplet)) if len(cross_triplet) else None,
            top_genes='; '.join(g for g, _ in gene_count.most_common(8)),
            representative_patterns='; '.join(names[j] for j in best_patterns),
            example_candidate_targets='; '.join(targets[i] for i in best_targets if mask[i, ix].any())))
    modules = pd.DataFrame(group_summary).sort_values(['candidates', 'pattern_group'], ascending=[False, True])
    module_score_table = pd.DataFrame(module_scores, index=pd.Index(targets, name='target'))
    module_score_table.to_csv(output / 'tables/module_activity_descriptive_zmean.csv')
    target_summary = []
    row_distances = squareform(row_tree['condensed'])
    for group in sorted(set(target_groups)):
        ix = np.flatnonzero(target_groups == group)
        best = sorted(ix, key=lambda i: (-int(rd[i]), targets[i]))[:8]
        subdist = row_distances[np.ix_(ix, ix)]
        medoid = ix[int(np.argmin(subdist.mean(1)))]
        target_summary.append(dict(target_group=group, targets=len(ix), candidates=int(rd[ix].sum()),
            enrichment=int(enrich[ix].sum()), depletion=int(deplete[ix].sum()), medoid=targets[medoid],
            example_targets='; '.join(targets[i] for i in best),
            mean_within_cosine=float(1 - subdist[np.triu_indices(len(ix), 1)].mean()) if len(ix) > 1 else None))
    target_group_table = pd.DataFrame(target_summary)

    # Close target pairs are descriptive, using all effects rather than p-values.
    neighbours = []
    for i in range(n):
        js = sorted((j for j in range(n) if j != i), key=lambda j: (row_distances[i, j], targets[j]))[:5]
        for rank, j in enumerate(js, 1):
            jaccard, signed_shared = signed_candidate_jaccard(mask[i], delta[i], mask[j], delta[j])
            neighbours.append(dict(target=targets[i], neighbour=targets[j], rank=rank,
                cosine_similarity=float(1 - row_distances[i, j]),
                signed_candidate_jaccard=jaccard,
                shared_same_direction_candidates=signed_shared,
                target_n=int(stat['target_n'][row_idx[i]]), neighbour_n=int(stat['target_n'][row_idx[j]])))
    pd.DataFrame(neighbours).to_csv(output / 'tables/target_nearest_neighbours.csv', index=False)
    correlation = np.corrcoef(delta.T)
    pairs = []
    for a in range(m):
        for b in range(a + 1, m):
            overlap = sorted(set(patterns[a]['genes']) & set(patterns[b]['genes']))
            pairs.append(dict(reference_a=refs[a], reference_b=refs[b], pattern_a=names[a], pattern_b=names[b],
                correlation=float(correlation[a, b]), same_triplet=bool(triplets[a] == triplets[b]),
                shared_genes='; '.join(overlap), shared_gene_count=len(overlap),
                shared_candidate_targets=int((mask[:, a] & mask[:, b]).sum())))
    pair_table = pd.DataFrame(pairs).sort_values(['correlation', 'reference_a', 'reference_b'], ascending=[False, True, True])
    pair_table.to_csv(output / 'tables/pattern_pair_correlations.csv.gz', index=False)
    pair_table.loc[(~pair_table.same_triplet) & (pair_table.shared_gene_count == 0)].head(50).to_csv(
        output / 'tables/top_correlated_disjoint_gene_patterns.csv', index=False)
    pair_table.sort_values('correlation').head(50).to_csv(output / 'tables/top_anticorrelated_patterns.csv', index=False)

    sensitivity = []
    for axis, tree, base in (('target', row_tree, row_tree['labels']), ('pattern', col_tree, col_tree['labels'])):
        for cutoff in (.2, .3, .4, .5):
            labs = cut_labels(tree, cutoff)
            sizes = Counter(labs[labs != 0])
            sensitivity.append(dict(axis=axis, input='continuous_delta', cutoff=cutoff,
                groups=len(sizes), largest_group=max(sizes.values()), singletons=sum(v == 1 for v in sizes.values()),
                adjusted_rand_vs_primary=adjusted_rand(base, labs),
                silhouette=silhouette_from_tree(tree, labs), excluded_profiles=int((labs == 0).sum())))
    weighted = delta / np.sqrt([triplet_sizes[t] for t in triplets])
    for name, data in [('selection_encoded', views['selection_encoded']), ('equal_triplet_weight', weighted)]:
        if not np.isfinite(data).all():
            raise ValueError('sensitivity matrix has unsupported values; no zero-imputation permitted')
        tree = hierarchy(data, 'cosine', optimal=False)
        sizes = Counter(tree['labels'][tree['labels'] != 0])
        sensitivity.append(dict(axis='target', input=name, cutoff=.3, groups=len(sizes),
            largest_group=max(sizes.values()), singletons=sum(v == 1 for v in sizes.values()),
            adjusted_rand_vs_primary=adjusted_rand(row_tree['labels'], tree['labels']),
            silhouette=silhouette_from_tree(tree, tree['labels']), excluded_profiles=int((tree['labels'] == 0).sum())))
    broad_delta = stat['delta'][all_adequate][:, col_idx]
    broad_tree = hierarchy(broad_delta.T, 'correlation', optimal=False)
    sizes = Counter(broad_tree['labels'][broad_tree['labels'] != 0])
    sensitivity.append(dict(axis='pattern', input=f'all_{len(broad_delta)}_adequate_targets', cutoff=.3,
        groups=len(sizes), largest_group=max(sizes.values()), singletons=sum(v == 1 for v in sizes.values()),
        adjusted_rand_vs_primary=adjusted_rand(col_tree['labels'], broad_tree['labels']),
        silhouette=silhouette_from_tree(broad_tree, broad_tree['labels']), excluded_profiles=int((broad_tree['labels'] == 0).sum())))
    pd.DataFrame(sensitivity).to_csv(output / 'tables/clustering_sensitivity.csv', index=False)

    stability = resampling_stability(delta, triplets, target_groups, pattern_groups)
    target_stability = pd.DataFrame(stability['targets']).rename(columns={'group': 'target_group'})
    pattern_stability = pd.DataFrame(stability['patterns']).rename(columns={'group': 'pattern_group'})
    target_group_table = target_group_table.merge(target_stability, on='target_group')
    modules = modules.merge(pattern_stability, on='pattern_group')
    np.savez_compressed(output / 'matrices/resampling_coassignment.npz',
        target=stability['target_coassignment'], pattern=stability['pattern_coassignment'])
    print('50 block/target resampling runs completed.', flush=True)

    centered = delta - delta.mean(0)
    u, s, vt = np.linalg.svd(centered, full_matrices=False)
    explained = s ** 2 / np.sum(s ** 2)
    raw_s = np.linalg.svd(delta, compute_uv=False)
    raw_energy = raw_s ** 2 / np.sum(raw_s ** 2)
    ws = np.linalg.svd(weighted - weighted.mean(0), compute_uv=False)
    weighted_explained = ws ** 2 / np.sum(ws ** 2)
    pd.DataFrame(dict(component=np.arange(1, len(s) + 1), explained_variance=explained,
        cumulative_variance=np.cumsum(explained), raw_effect_energy=raw_energy,
        cumulative_raw_energy=np.cumsum(raw_energy), equal_triplet_explained_variance=weighted_explained,
        cumulative_equal_triplet_variance=np.cumsum(weighted_explained))).to_csv(output / 'tables/pca_variance.csv', index=False)
    pd.DataFrame(u[:, :10] * s[:10], index=pd.Index(targets, name='target'),
                 columns=[f'PC{i}' for i in range(1, 11)]).to_csv(output / 'tables/target_pca_scores.csv')
    pd.DataFrame(vt[:10].T, index=pd.Index(refs, name='reference_id'),
                 columns=[f'PC{i}' for i in range(1, 11)]).to_csv(output / 'tables/pattern_pca_loadings.csv')
    target_table.sort_values(['candidates', 'target'], ascending=[False, True]).to_csv(output / 'tables/target_summary.csv', index=False)
    pattern_table.sort_values(['candidate_targets', 'reference_id'], ascending=[False, True]).to_csv(output / 'tables/pattern_summary.csv', index=False)
    triplet_table.sort_values(['candidates', 'triplet'], ascending=[False, True]).to_csv(output / 'tables/triplet_summary.csv', index=False)
    modules.to_csv(output / 'tables/pattern_modules.csv', index=False)
    target_group_table.to_csv(output / 'tables/target_groups.csv', index=False)

    triage = []
    for i, j in zip(*np.nonzero(mask)):
        triage.append(dict(candidate_key=f'{source.name}:C{digest([targets[i], refs[j]])[:20]}',
            target=targets[i], reference_id=refs[j], pattern=names[j], delta=float(delta[i, j]),
            direction='enrichment' if delta[i, j] > 0 else 'depletion',
            target_group=target_groups[i], pattern_group=pattern_groups[j],
            pattern_target_prevalence=float(cd[j] / n), target_candidate_count=int(rd[i]),
            target_in_pattern=bool(targets[i] in patterns[j]['genes']),
            external_validation_status='not_performed', biological_annotation_status='not_performed',
            selected_for_day8=False, selected_for_deep=False))
    pd.DataFrame(triage).to_csv(output / 'tables/structural_triage_features.csv', index=False)
    rho, _ = spearmanr(target_table['n_cells'], target_table['candidates'])
    main_status = {str(k): int(v) for k, v in zip(*np.unique(views['status'], return_counts=True))}
    module_mass = modules.sort_values('candidates', ascending=False)['candidates'].values
    summary = dict(source_candidates=int(mask.sum()), source_targets=scan_summary['targets'],
        main_targets=n, adequate_targets=int(all_adequate.sum()), reference_patterns=m,
        candidate_patterns=int((cd > 0).sum()), reference_triplets=len(set(triplets)),
        candidate_triplets=int((triplet_table.candidates > 0).sum()),
        enrichment=int(enrich.sum()), depletion=int(deplete.sum()),
        candidate_density=float(mask.mean()), target_candidate_distribution=distribution(rd),
        pattern_candidate_distribution_all=distribution(cd),
        pattern_candidate_distribution_active=distribution(cd[cd > 0]),
        concentration=conc_summary, main_matrix_status=main_status,
        main_raw_effects_missing=int((~np.isfinite(delta)).sum()),
        main_non_candidates_with_nonzero_effect=int(((~mask) & (delta != 0)).sum()),
        selection_retained_effect_energy=float(np.nansum(views['selection_encoded'] ** 2) / np.sum(delta ** 2)),
        target_groups=len(target_group_table), pattern_groups=len(modules),
        provisional_modules=int((modules.group_kind == 'provisional_response_module').sum()),
        top3_pattern_groups_candidate_fraction=float(module_mass[:3].sum() / mask.sum()),
        top4_pattern_groups_candidate_fraction=float(module_mass[:4].sum() / mask.sum()),
        top3_centered_pca_variance=float(explained[:3].sum()), top4_centered_pca_variance=float(explained[:4].sum()),
        top3_raw_effect_energy=float(raw_energy[:3].sum()),
        top3_equal_triplet_pca_variance=float(weighted_explained[:3].sum()),
        components_for_80pct_variance=int(np.searchsorted(np.cumsum(explained), .8) + 1),
        components_for_90pct_variance=int(np.searchsorted(np.cumsum(explained), .9) + 1),
        candidate_degree_vs_target_cells_spearman=float(rho),
        resampling_invalid_target_profiles=stability['invalid_row_profiles'],
        resampling_invalid_pattern_profiles=stability['invalid_column_profiles'],
        confirmed_clues=0, biological_annotation_performed=False, day8_accessed=False, model_calls=0)
    if int(rd.sum()) != len(triage) or int(cd.sum()) != len(triage) or int(modules.candidates.sum()) != len(triage):
        raise AssertionError('summary conservation failed')
    write_json(output / 'SUMMARY.json', summary)
    from .plots import make_figures
    make_figures(output, delta, mask, targets, refs, names, row_tree, col_tree, target_groups,
                 pattern_groups, target_table, pattern_table, modules, module_score_table,
                 summary, u[:, :2] * s[:2], explained, raw_energy, sensitivity)
    from .report import write_report
    write_report(output, summary, target_table, pattern_table, modules, target_group_table, sensitivity)

    # Source files and analysis sources must not change during this run.
    if any(sha(ROOT / p) != h for p, h in input_hashes.items()):
        raise RuntimeError('source inputs changed during analysis')
    if any(sha(ROOT / p) != h for p, h in source_hashes.items()):
        raise RuntimeError('analysis source changed during execution')
    artifacts = {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
    write_json(output / 'RUN_MANIFEST.json', dict(status='complete', elapsed_seconds=time.monotonic() - started,
        inputs_unchanged=True, analysis_source_unchanged=True, checks=dict(candidate_jsonl_and_matrix_agree=True,
        identity_hashes_valid=True, matrix_and_summary_counts_conserved=True), artifacts_sha256=artifacts,
        model_calls=0, day8_accessed=False, biological_annotations=False))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.source.resolve(), args.output.resolve())
