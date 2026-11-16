"""NT-only, independently searched two-fold reference experiment.

The v0.2 statistical/search implementation is reused without changing its gates.
Each direction has its own enrichment BH families; these are not MFI FDR tests.
"""
from dataclasses import dataclass, replace
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform

import numpy as np
import pandas as pd
from scipy import sparse

from .bootstrap import summarize_distribution
from .patterns import JointPattern
from .v02.config import ReferenceConfig, config_dict
from .v02.populations import Population, assert_disjoint
from .v02.reference import (BASE_COLUMNS, LOG_COLUMNS, VALIDATION_COLUMNS, apply_null_fdr,
                            binary_fingerprint, canonical_json, discovery_search, evaluate,
                            table, write_table)
from .v02.statistics import seeded_rng, stable_reference, state_space


DEFAULT_SEED = 20260927
ROLES = ('A_discovery', 'B_discovery', 'B_validation_from_A', 'A_validation_from_B')
PATTERN_EXTRA_COLUMNS = ['evaluation_role', 'bootstrap_seed', 'bootstrap_stage',
                         'mfi_lambda', 'mfi_lambda_below_005', 'mfi_only_stable',
                         'within_fold_stable', 'bootstrap_key']
ESTIMABILITY_COLUMNS = ['evaluation_role', 'gene_set_id', 'genes', 'order', 'total_cells',
    'raw_state_counts', 'state_counts', 'min_state_count', 'max_state_count',
    'min_observed_state_count', 'zero_state_count', 'zero_state_fraction',
    'states_below_5', 'states_below_10', 'states_below_20',
    'fraction_states_below_5', 'fraction_states_below_10', 'fraction_states_below_20',
    'state_table_occupancy', 'table_quality_pass', 'mfi', 'mfi_bootstrap_median',
    'mfi_bootstrap_ci_low', 'mfi_bootstrap_ci_high', 'mfi_bootstrap_sign_stability',
    'mfi_lambda', 'mfi_lambda_below_005', 'mfi_only_stable', 'bootstrap_performed',
    'bootstrap_seed', 'bootstrap_stage', 'bootstrap_rng_entropy', 'bootstrap_key',
    'bootstrap_file', 'n_bootstrap', 'smoothing_alpha']
CROSS_COLUMNS = ['reference_id', 'genes', 'states', 'pattern_string', 'order',
    'discovered_in_A', 'discovered_in_B', 'within_fold_stable_A', 'within_fold_stable_B',
    'within_fold_stable', 'mfi_only_within_fold_stable_A', 'mfi_only_within_fold_stable_B',
    'mfi_only_within_fold_stable', 'A_to_B_replicated', 'B_to_A_replicated',
    'A_to_B_mfi_replicated', 'B_to_A_mfi_replicated',
    'cross_fold_replicated', 'bidirectionally_rediscovered']
STAT_COLUMNS = ['total_cells', 'raw_state_counts', 'table_quality_pass', 'bootstrap_performed',
    'mfi_bootstrap_median', 'mfi_bootstrap_ci_low', 'mfi_bootstrap_ci_high',
    'mfi_bootstrap_sign_stability', 'enrichment_bootstrap_median',
    'enrichment_bootstrap_ci_low', 'enrichment_bootstrap_ci_high',
    'enrichment_bootstrap_sign_stability', 'log2_enrichment', 'mfi_mode', 'smoothing_alpha']
DISCOVERY_COLUMNS = BASE_COLUMNS + PATTERN_EXTRA_COLUMNS + STAT_COLUMNS
LOCKED_VALIDATION_COLUMNS = (VALIDATION_COLUMNS + PATTERN_EXTRA_COLUMNS + STAT_COLUMNS
                             + ['mfi_only_cross_fold_replicated'])
ORDER_COLUMNS = ['order', 'A_candidates_evaluated', 'B_candidates_evaluated',
    'A_discovered', 'B_discovered', 'A_to_B_replicated', 'B_to_A_replicated',
    'within_fold_stable', 'cross_fold_replicated', 'bidirectionally_rediscovered',
    'A_discovered_gene_sets', 'B_discovered_gene_sets', 'cross_fold_replicated_gene_sets',
    'bidirectionally_rediscovered_gene_sets']


def _seed(seed, role):
    payload = canonical_json(['nt_twofold', seed, role]).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], 'big')


def _gene_id(genes):
    return 'G' + hashlib.sha256(canonical_json(list(genes)).encode()).hexdigest()[:20]


def split_nt_twofold(population, *, random_seed, strata=None):
    """Identity/stratum-only partition with exact global floor/ceil half sizes.

    Each stratum differs by at most one cell between folds. Odd-stratum extras
    are randomly allocated between folds, instead of all accruing to fold B.
    This is a cell holdout, not an independent biological replicate.
    """
    if isinstance(random_seed, bool) or not isinstance(random_seed, int) or random_seed < 0:
        raise ValueError('random_seed must be a nonnegative integer')
    n = len(population.cell_ids)
    if n < 2:
        raise ValueError('two folds require at least two cells')
    labels = np.full(n, '__all__') if strata is None else np.asarray(strata)
    if labels.shape != (n,) or pd.isna(labels).any():
        raise ValueError('strata must be nonmissing labels matching NT cells')
    labels = labels.astype(str)
    groups = [np.flatnonzero(labels == label) for label in sorted(set(labels))]
    rng = np.random.default_rng(random_seed)
    odd = [i for i, rows in enumerate(groups) if len(rows) % 2]
    extra_a = set(rng.permutation(odd)[:len(odd)//2].tolist())
    parts = [[], []]
    for i, rows in enumerate(groups):
        permuted = rng.permutation(rows)
        n_a = len(rows)//2 + (i in extra_a)
        parts[0].extend(permuted[:n_a].tolist())
        parts[1].extend(permuted[n_a:].tolist())
    result = tuple(population.subset(sorted(rows)) for rows in parts)
    assert_disjoint(*result)
    assert [len(p.cell_ids) for p in result] == [n//2, n-n//2]
    return result


def select_fano_module(population, *, module_size=12, min_detection_rate=.01,
                       max_detection_rate=.99):
    """Raw-count sample variance / mean, fit exclusively on the supplied fold."""
    if isinstance(module_size, bool) or not isinstance(module_size, int) or module_size < 1:
        raise ValueError('module_size must be a positive integer')
    if not 0 <= min_detection_rate < max_detection_rate <= 1:
        raise ValueError('invalid detection rate bounds')
    n = len(population.cell_ids)
    if n < 2:
        raise ValueError('sample variance requires at least two cells')
    matrix = population.matrix
    if sparse.issparse(matrix):
        matrix = matrix.tocsr().astype(float)
        matrix.sum_duplicates()
        values = matrix.data
    else:
        matrix = np.asarray(matrix, dtype=float)
        values = matrix
    if not np.isfinite(values).all() or (values < 0).any() or not (values == np.floor(values)).all():
        raise ValueError('Fano baseline requires finite nonnegative integer raw counts')
    mean = np.asarray(matrix.mean(axis=0)).ravel()
    second = np.asarray(matrix.power(2).mean(axis=0)).ravel() if sparse.issparse(matrix) else (matrix**2).mean(axis=0)
    variance = (second-mean**2)*n/(n-1)
    detection = np.asarray((matrix > 0).mean(axis=0)).ravel()
    qc = pd.DataFrame(dict(gene=population.gene_names, mean=mean, variance=variance,
        detection_rate=detection, fano=np.divide(variance, mean, out=np.zeros_like(mean), where=mean > 0)))
    qc['eligible'] = qc.detection_rate.between(min_detection_rate, max_detection_rate)
    ranked = qc.loc[qc.eligible].sort_values(['fano', 'gene'], ascending=[False, True])
    genes = ranked.head(module_size).gene.tolist()
    if len(genes) != module_size:
        raise ValueError(f'fewer than {module_size} eligible discovery genes')
    qc['selected'] = qc.gene.isin(genes)
    return genes, qc


def _mfi_stable(row, config):
    return bool(row['table_quality_pass'] and abs(row['mfi']) >= config.min_abs_mfi
                and row['mfi_bootstrap_sign_stability'] >= config.min_sign_stability
                and (row['mfi_bootstrap_ci_low'] > 0 or row['mfi_bootstrap_ci_high'] < 0))


def _bootstrap_replay(row, genes, config, stage):
    """Recover exactly the draws used by joint_table, without a second analysis."""
    counts = np.array(list(row['raw_state_counts'].values()), dtype=np.int64)
    n = int(counts.sum())
    states = state_space(len(genes))
    draws = seeded_rng(config.random_seed, stage, genes).multinomial(n, counts/n, size=config.n_bootstrap)
    signs = np.where((len(genes)-states.sum(axis=1).astype(int)) % 2 == 0, 1, -1)
    samples = np.log((draws+config.smoothing_alpha)/(n+len(states)*config.smoothing_alpha)) @ signs
    replay_summary = summarize_distribution(samples, row['mfi'], config.ci_level)
    for metric, value in replay_summary.items():
        if not np.isclose(value, row['mfi_bootstrap_'+metric], rtol=1e-12, atol=1e-12):
            raise RuntimeError('bootstrap replay does not match original statistical evaluation')
    return samples


def _annotate(rows, role, config, stage, distributions):
    """One estimability record / bootstrap vector per evaluated unique gene set."""
    by_genes, estimability = {}, []
    for row in rows:
        genes = row['genes']
        if genes not in by_genes:
            counts = np.array(list(row['raw_state_counts'].values()), dtype=int)
            record = {key: row.get(key) for key in ESTIMABILITY_COLUMNS if key in row}
            entropy = int.from_bytes(hashlib.sha256(
                json.dumps([config.random_seed, stage, list(genes)], separators=(',', ':')).encode()
            ).digest()[:8], 'big')
            record.update(evaluation_role=role, gene_set_id=_gene_id(genes), genes=genes,
                          state_counts=counts.tolist(), max_state_count=int(counts.max()),
                          bootstrap_seed=config.random_seed, bootstrap_stage=stage,
                          bootstrap_rng_entropy=entropy, n_bootstrap=config.n_bootstrap,
                          bootstrap_file=None, bootstrap_key=None, mfi_lambda=None,
                          mfi_lambda_below_005=None, mfi_only_stable=_mfi_stable(row, config))
            for threshold in (5, 10, 20):
                record[f'states_below_{threshold}'] = int((counts < threshold).sum())
                record[f'fraction_states_below_{threshold}'] = float((counts < threshold).mean())
            if row['bootstrap_performed']:
                key = role + '__' + record['gene_set_id']
                samples = _bootstrap_replay(row, genes, config, stage)
                distributions[key] = samples
                # Original zero has no meaningful direction: follow existing
                # summarize_distribution convention (stability 0, lambda 1).
                flip = 1.0-float(row['mfi_bootstrap_sign_stability'])
                record.update(bootstrap_file='mfi_bootstrap_distributions.npz', bootstrap_key=key,
                              mfi_lambda=flip, mfi_lambda_below_005=bool(flip < .05))
            by_genes[genes] = record
            estimability.append(record)
        record = by_genes[genes]
        row.update({key: record[key] for key in PATTERN_EXTRA_COLUMNS if key in record})
        row['within_fold_stable'] = bool(stable_reference(row, config))
    return estimability


def _discover(population, genes, config):
    encoded, qc = population.encode(sorted(genes), config)
    qc['retained'] = qc.detection_rate.between(config.min_detection_rate, config.max_detection_rate)
    retained = qc.loc[qc.retained, 'gene'].tolist()
    rows, logs, summaries, stop = discovery_search(encoded[retained], config)
    return rows, logs, summaries, stop, qc, retained, binary_fingerprint(encoded, population.cell_ids)


def _validate(population, locked, config):
    checks, cache = [], {}
    if locked:
        genes = sorted({g for row in locked for g in row['genes']})
        encoded, _ = population.encode(genes, config)
        for row in locked:
            checks.append(evaluate(encoded, JointPattern(row['genes'], row['states']), config, 'validation', cache))
        apply_null_fdr(checks)
    for source, check in zip(locked, checks):
        same = bool(source['mfi']*check['mfi'] > 0)
        passed = bool(stable_reference(check, config) and same)
        check.update(reference_mfi_direction_consistent=same,
                     mfi_only_cross_fold_replicated=bool(_mfi_stable(check, config) and same),
                     replicated_in_reference_validation=passed,
                     validation_reason='passed' if passed else 'support_occupancy_null_or_bootstrap_failed_or_mfi_reversed')
    return checks


def _cross_summary(a_rows, b_rows, b_checks, a_checks):
    discoveries = [{r['reference_id']: r for r in rows} for rows in (a_rows, b_rows)]
    locked_ids = {r['reference_id'] for rows in (a_rows, b_rows) for r in rows if r['stable_in_discovery']}
    validations = [{r['reference_id']: r for r in rows} for rows in (b_checks, a_checks)]
    output = []
    for pattern_id in sorted(locked_ids):
        a, b = (d.get(pattern_id) for d in discoveries)
        ab, ba = (v.get(pattern_id) for v in validations)
        source = a if a is not None else b
        discovered_a, discovered_b = (bool(r and r['stable_in_discovery']) for r in (a, b))
        passed_ab, passed_ba = (bool(r and r['replicated_in_reference_validation']) for r in (ab, ba))
        mfi_a, mfi_b = ((r['mfi_only_stable'] if r is not None else None) for r in (a, b))
        row = {k: source[k] for k in ('reference_id', 'genes', 'states', 'pattern_string', 'order')}
        row.update(discovered_in_A=discovered_a, discovered_in_B=discovered_b,
                   within_fold_stable_A=discovered_a, within_fold_stable_B=discovered_b,
                   within_fold_stable=discovered_a or discovered_b,
                   mfi_only_within_fold_stable_A=mfi_a, mfi_only_within_fold_stable_B=mfi_b,
                   mfi_only_within_fold_stable=bool(mfi_a or mfi_b),
                   A_to_B_replicated=passed_ab, B_to_A_replicated=passed_ba,
                   A_to_B_mfi_replicated=bool(ab and ab['mfi_only_cross_fold_replicated']),
                   B_to_A_mfi_replicated=bool(ba and ba['mfi_only_cross_fold_replicated']),
                   cross_fold_replicated=passed_ab or passed_ba,
                   bidirectionally_rediscovered=discovered_a and discovered_b and passed_ab and passed_ba)
        for label, evidence in [('A_discovery', a), ('B_discovery', b),
                                ('B_validation_from_A', ab), ('A_validation_from_B', ba)]:
            for metric in ('mfi', 'mfi_bootstrap_ci_low', 'mfi_bootstrap_ci_high',
                           'mfi_bootstrap_sign_stability', 'mfi_lambda', 'support', 'q_value_null'):
                row[label+'_'+metric] = evidence.get(metric) if evidence is not None else None
        output.append(row)
    return table(output, CROSS_COLUMNS)


@dataclass
class TwoFoldNTResult:
    fold_a_discovery: pd.DataFrame
    fold_b_validation: pd.DataFrame
    fold_b_discovery: pd.DataFrame
    fold_a_validation: pd.DataFrame
    cross_fold_summary: pd.DataFrame
    state_table_estimability: pd.DataFrame
    order_reproducibility_summary: pd.DataFrame
    fold_a_search_log: pd.DataFrame
    fold_b_search_log: pd.DataFrame
    fold_a_gene_qc: pd.DataFrame
    fold_b_gene_qc: pd.DataFrame
    metadata: dict
    bootstrap_distributions: dict

    def write(self, output_dir):
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        files = [('fold_A_discovery', self.fold_a_discovery), ('fold_B_validation', self.fold_b_validation),
                 ('fold_B_discovery', self.fold_b_discovery), ('fold_A_validation', self.fold_a_validation),
                 ('cross_fold_summary', self.cross_fold_summary), ('state_table_estimability', self.state_table_estimability),
                 ('order_reproducibility_summary', self.order_reproducibility_summary),
                 ('fold_A_search_log', self.fold_a_search_log), ('fold_B_search_log', self.fold_b_search_log),
                 ('fold_A_gene_qc', self.fold_a_gene_qc), ('fold_B_gene_qc', self.fold_b_gene_qc)]
        for name, frame in files:
            write_table(frame, folder/(name+'.csv'))
        np.savez_compressed(folder/'mfi_bootstrap_distributions.npz', **self.bootstrap_distributions)
        (folder/'nt_reference_metadata.json').write_text(canonical_json(self.metadata)+'\n')
        return folder


def fit_twofold_nt(fold_a, fold_b, *, candidate_genes_a, candidate_genes_b, config=None, checkpoint_dir=None):
    """Run both independent searches, freeze both results, then locked validation.

    The caller must select each supplied module using its own fold only. Both
    populations need the union of module genes so locked validation can evaluate
    the opposite fold's states even when the independently selected modules differ.
    """
    config = ReferenceConfig(max_order=4, n_bootstrap=1000, random_seed=DEFAULT_SEED) if config is None else config
    if not isinstance(config, ReferenceConfig):
        raise TypeError('two-fold reference experiment requires ReferenceConfig')
    assert_disjoint(fold_a, fold_b)
    modules = [list(candidate_genes_a), list(candidate_genes_b)]
    for genes in modules:
        if not genes or len(set(genes)) != len(genes):
            raise ValueError('supply nonempty unique fold-owned candidate_genes')
    if any(not set(modules[0]+modules[1]) <= set(pop.gene_names) for pop in (fold_a, fold_b)):
        raise ValueError('both populations must contain the union of candidate genes for locked validation')
    seeds = {role: _seed(config.random_seed, role) for role in ROLES}
    configs = {role: replace(config, random_seed=seeds[role]) for role in ROLES}
    a = _discover(fold_a, modules[0], configs['A_discovery'])
    b = _discover(fold_b, modules[1], configs['B_discovery'])
    # Immutable serialized candidate lists are captured before validation starts.
    frozen_a = canonical_json([r for r in a[0] if r['stable_in_discovery']])
    frozen_b = canonical_json([r for r in b[0] if r['stable_in_discovery']])
    # Fresh dicts ensure downstream annotations cannot modify the frozen records.
    locked_a = [dict(r, genes=tuple(r['genes']), states=tuple(r['states'])) for r in json.loads(frozen_a)]
    locked_b = [dict(r, genes=tuple(r['genes']), states=tuple(r['states'])) for r in json.loads(frozen_b)]
    distributions, estimates = {}, []
    for rows, role in [(a[0], 'A_discovery'), (b[0], 'B_discovery')]:
        estimates.extend(_annotate(rows, role, configs[role], 'discovery', distributions))
    if checkpoint_dir is not None:
        checkpoint = Path(checkpoint_dir)
        checkpoint.mkdir(parents=True, exist_ok=True)
        if (checkpoint/'discoveries_frozen.json').exists():
            raise FileExistsError('discovery freeze checkpoint already exists')
        for label, data in [('A', a), ('B', b)]:
            write_table(table(data[0], DISCOVERY_COLUMNS), checkpoint/f'fold_{label}_discovery.csv')
            write_table(table(data[1], LOG_COLUMNS), checkpoint/f'fold_{label}_search_log.csv')
        checkpoint_payload = dict(both_discoveries_complete=True, validation_started=False,
            stage_seeds=seeds, candidate_genes={'A': modules[0], 'B': modules[1]},
            locked_candidates={'A': json.loads(frozen_a), 'B': json.loads(frozen_b)},
            locked_candidates_sha256={'A': hashlib.sha256(frozen_a.encode()).hexdigest(),
                                      'B': hashlib.sha256(frozen_b.encode()).hexdigest()},
            files_sha256={name: hashlib.sha256((checkpoint/name).read_bytes()).hexdigest()
                          for name in ['fold_A_discovery.csv', 'fold_B_discovery.csv',
                                       'fold_A_search_log.csv', 'fold_B_search_log.csv']})
        (checkpoint/'discoveries_frozen.json').write_text(canonical_json(checkpoint_payload)+'\n')
    b_checks = _validate(fold_b, locked_a, configs['B_validation_from_A'])
    a_checks = _validate(fold_a, locked_b, configs['A_validation_from_B'])
    for rows, role in [(b_checks, 'B_validation_from_A'), (a_checks, 'A_validation_from_B')]:
        estimates.extend(_annotate(rows, role, configs[role], 'validation', distributions))
    cross = _cross_summary(a[0], b[0], b_checks, a_checks)
    summaries = []
    for order in range(2, config.max_order+1):
        subset = cross[cross.order == order]
        a_locked = [r for r in a[0] if r['order'] == order and r['stable_in_discovery']]
        b_locked = [r for r in b[0] if r['order'] == order and r['stable_in_discovery']]
        row = dict(order=order, A_candidates_evaluated=sum(r['order'] == order for r in a[0]),
                   B_candidates_evaluated=sum(r['order'] == order for r in b[0]),
                   A_discovered=len(a_locked), B_discovered=len(b_locked),
                   A_discovered_gene_sets=len({r['genes'] for r in a_locked}),
                   B_discovered_gene_sets=len({r['genes'] for r in b_locked}))
        for key in ('A_to_B_replicated', 'B_to_A_replicated', 'within_fold_stable',
                    'cross_fold_replicated', 'bidirectionally_rediscovered'):
            row[key] = int(subset[key].sum())
        for key in ('cross_fold_replicated', 'bidirectionally_rediscovered'):
            row[key+'_gene_sets'] = len(set(subset.loc[subset[key].astype(bool), 'genes']))
        summaries.append(row)
    families = {}
    for role, rows in [('A_discovery', a[0]), ('B_discovery', b[0]),
                       ('B_validation_from_A', b_checks), ('A_validation_from_B', a_checks)]:
        reference_ids = [r['reference_id'] for r in rows]
        families[role] = dict(n_tests=len(rows), reference_ids=reference_ids,
                              reference_ids_sha256=hashlib.sha256(canonical_json(reference_ids).encode()).hexdigest(),
                              adjustment='Benjamini-Hochberg', statistic='state enrichment under plug-in independence null',
                              scope='all actually evaluated states across orders' if 'discovery' in role else 'all locked opposite-fold discovery states across orders')
    versions = {name: importlib.metadata.version(name) for name in ['numpy', 'pandas', 'scipy']}
    versions['python'] = platform.python_version()
    source_files = sorted(Path(__file__).parent.rglob('*.py'))
    experiment_config = config_dict(config)
    unused = {name: experiment_config.pop(name) for name in
              ('split_fractions', 'shift_fdr_scope', 'max_tests', 'min_delta', 'alpha_shift', 'frequency_epsilon')}
    metadata = dict(experiment='nt_twofold', config=config_dict(config), experiment_config=experiment_config,
        inherited_unused_config=unused, split_design='stratified twofold, no third test population',
        n_cells={'A': len(fold_a.cell_ids), 'B': len(fold_b.cell_ids)}, cell_ids_overlap=0,
        cell_ids_sha256={label: hashlib.sha256(canonical_json(pop.cell_ids).encode()).hexdigest()
                        for label, pop in [('A', fold_a), ('B', fold_b)]},
        candidate_genes={'A': sorted(modules[0]), 'B': sorted(modules[1])},
        retained_genes={'A': a[5], 'B': b[5]}, discovery_binary_sha256={'A': a[6], 'B': b[6]},
        stop_reason={'A': a[3], 'B': b[3]}, order_search_summaries={'A': a[2], 'B': b[2]},
        base_random_seed=config.random_seed, stage_seeds=seeds,
        seed_derivation='SHA256(canonical JSON [nt_twofold, base_seed, role]) first 8 bytes big endian',
        rng_derivation='SHA256(JSON [stage_seed, discovery|validation, canonical genes]) first 8 bytes big endian; numpy default_rng',
        both_discoveries_frozen_before_validation=True, validation_search_performed=False,
        locked_candidates_sha256={'A': hashlib.sha256(frozen_a.encode()).hexdigest(),
                                  'B': hashlib.sha256(frozen_b.encode()).hexdigest()},
        locked_candidates={'A': json.loads(frozen_a), 'B': json.loads(frozen_b)},
        bh_families=families, mfi_fdr_controlled=False, union_fdr_controlled=False,
        validation_scope='disjoint NT cells, not independent biological/experimental replicates; internal development experiment',
        module_selection_scope='caller-selected separately using only own discovery fold; validation applies no detection/module reselection',
        estimability_scope='one row per evaluated unique gene set per evaluation role, including quality failures',
        within_fold_stable_definition='full unchanged v0.2 pattern gate, including MFI, support, enrichment and family q',
        mfi_only_stable_definition='quality, abs(MFI), sign stability and CI excluding zero; no enrichment/support/q gate',
        cross_fold_replicated_definition='at least one locked direction passes full pattern gate and same MFI direction',
        bidirectionally_rediscovered_definition='same exact canonical genes+states discovered independently in both folds and validated in both directions',
        lambda_definition='1 - bootstrap MFI sign stability; original zero has no direction and lambda=1; missing if quality failed',
        lambda_flag_is_additional_not_gate=True, bootstrap_file='mfi_bootstrap_distributions.npz',
        software_versions=versions,
        code_sha256={str(path.relative_to(Path(__file__).parent.parent)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files})
    return TwoFoldNTResult(table(a[0], DISCOVERY_COLUMNS),
        table(b_checks, LOCKED_VALIDATION_COLUMNS),
        table(b[0], DISCOVERY_COLUMNS),
        table(a_checks, LOCKED_VALIDATION_COLUMNS), cross,
        table(estimates, ESTIMABILITY_COLUMNS), table(summaries, ORDER_COLUMNS),
        table(a[1], LOG_COLUMNS), table(b[1], LOG_COLUMNS), a[4], b[4], metadata, distributions)
