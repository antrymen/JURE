"""Only prevalence testing of a frozen catalogue; no perturbation MFI screening."""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd
from ..bootstrap import summarize_distribution
from ..statistics import pattern_shift, benjamini_hochberg
from .config import ReferenceConfig
from .reference import FrozenCatalogue, canonical_json, identity, table, write_table, binary_fingerprint
from .statistics import seeded_rng


SHIFT_COLUMNS = ['perturbation', 'reference_id', 'pattern_string', 'genes', 'states', 'order',
                 'control_count', 'perturb_count', 'control_frequency', 'perturb_frequency',
                 'delta_frequency', 'p_value_shift', 'q_value_shift', 'support', 'status',
                 'replication_status', 'bootstrap_delta_ci_low', 'bootstrap_delta_ci_high',
                 'delta_sign_stability']


@dataclass
class ShiftResult:
    shifts: pd.DataFrame
    delta_matrix: pd.DataFrame
    call_matrix: pd.DataFrame
    metadata: dict

    def write(self, output_dir):
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        write_table(self.shifts, folder / 'perturbation_state_shifts.csv')
        self.delta_matrix.to_csv(folder / 'perturbation_state_delta_matrix.csv', index_label='perturbation')
        self.call_matrix.to_csv(folder / 'perturbation_state_calls.csv', index_label='perturbation')
        (folder / 'shift_metadata.json').write_text(canonical_json(self.metadata) + '\n')
        return folder


def occupancy(matrix, genes):
    values = matrix.loc[:, list(genes)].to_numpy(dtype=np.uint8)
    codes = values @ (2 ** np.arange(len(genes) - 1, -1, -1))
    counts = np.bincount(codes, minlength=2 ** len(genes))
    return dict(state_table_occupancy=float((counts > 0).mean()), zero_state_count=int((counts == 0).sum()),
                zero_state_fraction=float((counts == 0).mean()), min_state_count=int(counts.min()),
                min_observed_state_count=int(counts[counts > 0].min()))


def test_perturbations(catalogue, reference_test, perturbations):
    """BH covers every tested pattern (optionally across every supplied perturbation)."""
    if not isinstance(catalogue, FrozenCatalogue):
        raise TypeError('a FrozenCatalogue is required')
    payload = catalogue.payload
    config = ReferenceConfig(**payload['config'])
    if set(reference_test.cell_ids) != set(payload['test_cell_ids']):
        raise ValueError('reference_test must contain exactly the reserved test-cell identities')
    if any(not isinstance(k, str) or not k for k in perturbations):
        raise ValueError('perturbation identifiers must be nonempty strings')
    used = set(payload['discovery_cell_ids']) | set(payload['validation_cell_ids']) | set(payload['test_cell_ids'])
    for label in sorted(perturbations):
        pop = perturbations[label]
        if used.intersection(pop.cell_ids):
            raise ValueError('cell identity overlap in perturbation testing')
        used.update(pop.cell_ids)
    patterns = catalogue.patterns
    if len(patterns) * len(perturbations) > config.max_tests:
        raise ValueError('locked testing budget exceeded; do not silently truncate the FDR family')
    genes = payload['retained_genes']
    rows, fingerprints = [], {}
    if patterns:
        control, _ = reference_test.encode(genes, config)
        fingerprints['reference_test'] = binary_fingerprint(control, reference_test.cell_ids)
        control_occupancy = {p.genes: occupancy(control, p.genes) for p in patterns}
        for label, pop in sorted(perturbations.items()):
            perturb, _ = pop.encode(genes, config)
            fingerprints['perturbation:' + label] = binary_fingerprint(perturb, pop.cell_ids)
            perturb_occupancy = {p.genes: occupancy(perturb, p.genes) for p in patterns}
            for pattern, evidence in zip(patterns, payload['records']):
                row = pattern_shift(control, perturb, pattern, config.frequency_epsilon)
                row.update(perturbation=label, reference_id=identity(pattern), genes=pattern.genes,
                           states=pattern.states, order=pattern.order, pattern_string=pattern.to_string(),
                           support=max(row['control_count'], row['perturb_count']),
                           state_support_reference_test=row['control_count'], state_support_perturbation=row['perturb_count'],
                           replication_status='not_available', catalogue_sha256=catalogue.sha256,
                           reference_mfi=evidence['mfi'], validation_mfi=evidence['reference_validation']['mfi'])
                for prefix, values in [('reference_test', control_occupancy[pattern.genes]),
                                       ('perturbation', perturb_occupancy[pattern.genes])]:
                    row.update({f'{prefix}_{k}': v for k, v in values.items()})
                rng = seeded_rng(config.random_seed, 'shift:' + label, [identity(pattern)])
                draws = (rng.binomial(len(perturb), row['perturb_frequency'], config.n_bootstrap)/len(perturb)
                         - rng.binomial(len(control), row['control_frequency'], config.n_bootstrap)/len(control))
                summary = summarize_distribution(draws, row['delta_frequency'], config.ci_level)
                row.update(bootstrap_delta_median=summary['median'], bootstrap_delta_ci_low=summary['ci_low'],
                           bootstrap_delta_ci_high=summary['ci_high'], delta_sign_stability=summary['sign_stability'])
                rows.append(row)
    families = [rows] if config.shift_fdr_scope == 'all_perturbations' else [
        [r for r in rows if r['perturbation'] == label] for label in sorted(perturbations)]
    for family in families:
        for row, q in zip(family, benjamini_hochberg([r['p_value_shift'] for r in family])):
            row['q_value_shift'] = float(q)
            if row['support'] < config.min_support:
                status = 'insufficient_support'
            elif abs(row['delta_frequency']) < config.min_delta or q > config.alpha_shift:
                status = 'screened_out'
            elif (row['delta_sign_stability'] < config.min_sign_stability
                  or not (row['bootstrap_delta_ci_low'] > 0 or row['bootstrap_delta_ci_high'] < 0)):
                status = 'unstable_shift'
            else:
                status = 'candidate_shift'  # never claim biological replication from bootstrap
            row['status'] = status
    columns = [identity(p) for p in patterns]
    delta = pd.DataFrame(index=sorted(perturbations), columns=columns, dtype=float)
    calls = pd.DataFrame('—', index=sorted(perturbations), columns=columns)
    for row in rows:
        delta.loc[row['perturbation'], row['reference_id']] = row['delta_frequency']
        if row['status'] == 'candidate_shift':
            calls.loc[row['perturbation'], row['reference_id']] = 'up' if row['delta_frequency'] > 0 else 'down'
    metadata = dict(version='0.2.0', mode='reference_guided', catalogue_sha256=catalogue.sha256,
                    n_patterns=len(patterns), n_perturbations=len(perturbations), n_tests=len(rows),
                    fdr_scope=config.shift_fdr_scope, fdr_scope_note='all tests in this call; not future/separate calls',
                    reference_test_cell_ids=reference_test.cell_ids,
                    perturbation_cell_ids={k: v.cell_ids for k, v in sorted(perturbations.items())},
                    reference_test_in_catalogue=False, perturbation_mfi_required=False,
                    binary_input_sha256=fingerprints,
                    inference_scope='locked state prevalence shifts, not changes in interaction strength',
                    biological_replication='not evaluated',
                    control_matching='supplied reserved reference_test pool; no automatic batch adjustment')
    return ShiftResult(table(rows, SHIFT_COLUMNS), delta, calls, metadata)


# Avoid pytest collecting this public API when imported into a test module.
test_perturbations.__test__ = False
