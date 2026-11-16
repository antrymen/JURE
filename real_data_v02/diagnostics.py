"""Locked-pattern NT diagnostics, separate from the main perturbation FDR family."""
import hashlib

import pandas as pd

from clue_discovery.bootstrap import summarize_distribution
from clue_discovery.statistics import benjamini_hochberg, pattern_shift
from clue_discovery.v02 import FrozenCatalogue, Population, ReferenceConfig
from clue_discovery.v02.reference import binary_fingerprint, canonical_json, identity, table
from clue_discovery.v02.statistics import seeded_rng
from clue_discovery.v02.testing import SHIFT_COLUMNS


DIAGNOSTIC_COLUMNS = SHIFT_COLUMNS + [
    'control_total_cells', 'perturb_total_cells', 'bootstrap_delta_median',
    'state_support_reference_test', 'state_support_perturbation', 'catalogue_sha256',
    'diagnostic_label', 'analysis_role', 'fdr_family', 'fdr_family_size',
    'control_cell_ids_sha256', 'pseudo_perturb_cell_ids_sha256',
    'control_binary_sha256', 'pseudo_perturb_binary_sha256',
    'groups_disjoint', 'reserved_test_only', 'catalogue_changed',
]


def locked_nt_diagnostic(
    catalogue: FrozenCatalogue,
    control: Population,
    pseudo_perturb: Population,
    label: str,
) -> pd.DataFrame:
    """Test an a priori NT split without changing catalogue or main-test identities.

    Both groups must be disjoint subsets of the reserved NT test cohort. Each
    invocation corrects ALL catalogue patterns as its own diagnostic family;
    these q-values do not belong to the main perturbation-wide family.
    """
    if not isinstance(catalogue, FrozenCatalogue):
        raise TypeError('a FrozenCatalogue is required')
    if not isinstance(control, Population) or not isinstance(pseudo_perturb, Population):
        raise TypeError('control and pseudo_perturb must be Population objects')
    if not isinstance(label, str) or not label:
        raise ValueError('diagnostic label must be a nonempty string')

    payload = catalogue.payload
    control_ids, pseudo_ids = set(control.cell_ids), set(pseudo_perturb.cell_ids)
    if control_ids & pseudo_ids:
        raise ValueError('cell identity overlap between diagnostic groups')
    all_ids = control_ids | pseudo_ids
    forbidden = set(payload['discovery_cell_ids']) | set(payload['validation_cell_ids'])
    if all_ids & forbidden:
        raise ValueError('discovery/validation cell identities cannot enter NT diagnostics')
    if not all_ids <= set(payload['test_cell_ids']):
        raise ValueError('diagnostic groups must contain only reserved test-cell identities')

    config = ReferenceConfig(**payload['config'])
    patterns = catalogue.patterns
    if len(patterns) > config.max_tests:
        raise ValueError('diagnostic testing budget exceeded; do not truncate its FDR family')
    audits = dict(
        diagnostic_label=label,
        analysis_role='reserved_nt_locked_pattern_diagnostic',
        catalogue_sha256=catalogue.sha256,
        fdr_family='all_frozen_patterns_within_this_diagnostic_not_main_family',
        fdr_family_size=len(patterns),
        control_cell_ids_sha256=hashlib.sha256(canonical_json(control.cell_ids).encode()).hexdigest(),
        pseudo_perturb_cell_ids_sha256=hashlib.sha256(canonical_json(pseudo_perturb.cell_ids).encode()).hexdigest(),
        groups_disjoint=True,
        reserved_test_only=True,
        catalogue_changed=False,
    )
    rows = []
    if patterns:
        genes = payload['retained_genes']
        encoded_control, _ = control.encode(genes, config)
        encoded_pseudo, _ = pseudo_perturb.encode(genes, config)
        audits.update(
            control_binary_sha256=binary_fingerprint(encoded_control, control.cell_ids),
            pseudo_perturb_binary_sha256=binary_fingerprint(encoded_pseudo, pseudo_perturb.cell_ids),
        )
        for pattern in patterns:
            row = pattern_shift(encoded_control, encoded_pseudo, pattern, config.frequency_epsilon)
            reference_id = identity(pattern)
            row.update(
                **audits, perturbation=label, reference_id=reference_id,
                pattern_string=pattern.to_string(), genes=pattern.genes,
                states=pattern.states, order=pattern.order,
                support=max(row['control_count'], row['perturb_count']),
                state_support_reference_test=row['control_count'],
                state_support_perturbation=row['perturb_count'],
                replication_status='not_available',
            )
            rng = seeded_rng(config.random_seed, 'shift:' + label, [reference_id])
            # Match v0.2 exactly, including the order in which random draws occur.
            draws = (
                rng.binomial(len(encoded_pseudo), row['perturb_frequency'], config.n_bootstrap)
                / len(encoded_pseudo)
                - rng.binomial(len(encoded_control), row['control_frequency'], config.n_bootstrap)
                / len(encoded_control)
            )
            summary = summarize_distribution(draws, row['delta_frequency'], config.ci_level)
            row.update(
                bootstrap_delta_median=summary['median'],
                bootstrap_delta_ci_low=summary['ci_low'],
                bootstrap_delta_ci_high=summary['ci_high'],
                delta_sign_stability=summary['sign_stability'],
            )
            rows.append(row)

    for row, q in zip(rows, benjamini_hochberg([r['p_value_shift'] for r in rows])):
        row['q_value_shift'] = float(q)
        if row['support'] < config.min_support:
            status = 'insufficient_support'
        elif abs(row['delta_frequency']) < config.min_delta or q > config.alpha_shift:
            status = 'screened_out'
        elif (row['delta_sign_stability'] < config.min_sign_stability
              or not (row['bootstrap_delta_ci_low'] > 0 or row['bootstrap_delta_ci_high'] < 0)):
            status = 'unstable_shift'
        else:
            status = 'candidate_shift'
        row['status'] = status

    result = table(rows, DIAGNOSTIC_COLUMNS)
    result.attrs.update(audits)
    return result
