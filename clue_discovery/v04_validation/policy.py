"""Discovery-frozen, direction-specific triplet families and validation gates.

BH's assumptions and post-filtering caveat remain explicit. Holm uses half of a
0.05 error budget per direction: union control requires valid held-out p-values,
not independence between genes or between the two directions. No state-level
error-rate or causal claim is made by this module.
"""
from dataclasses import dataclass
import math

import numpy as np

from ..statistics import benjamini_hochberg
from ..v03.artifacts import digest
from ..v03.candidate import candidate_id, canonical_genes


ARMS = (
    ('raw_05', 'none', .05),
    ('bh_05', 'bh', .05),
    ('bh_025', 'bh', .025),
    ('holm_025', 'holm', .025),
)


@dataclass(frozen=True)
class ValidationFamily:
    source_fold: str
    validation_fold: str
    members: tuple[tuple[str, tuple[str, ...]], ...]
    locked_states_hash: str

    @property
    def family_id(self):
        return f'{self.source_fold}_to_{self.validation_fold}:order3:gene_set_gain'

    def to_dict(self):
        return dict(family_id=self.family_id, source_fold=self.source_fold,
            validation_fold=self.validation_fold, order=3, unit='canonical_gene_set',
            members=[dict(candidate_id=cid, genes=genes) for cid, genes in self.members],
            member_count=len(self.members), members_sha256=digest(self.members),
            locked_states_sha256=self.locked_states_hash,
            inclusion_rule='all_unique_discovery_locked_triplets_before_any_validation',
            unevaluable_rule='retain_in_denominator_with_accounting_p1_never_reject',
            multiple_states_share_one_gain_test=True, frozen_before_validation=True)


def freeze_family(locked, *, source_fold, validation_fold):
    if {source_fold, validation_fold} != {'A', 'B'}:
        raise ValueError('families require opposite A/B directions')
    members = {}
    states_seen = set()
    for row in locked:
        if row.get('discovery_fold') != source_fold:
            raise ValueError('locked record belongs to another discovery fold')
        if row['order'] != 3:
            continue
        genes = canonical_genes(row['genes'])
        if len(genes) != 3 or tuple(row['genes']) != genes or candidate_id(genes) != row['candidate_id']:
            raise ValueError('invalid canonical triplet identity')
        if row['reference_id'] in states_seen:
            raise ValueError('duplicate locked state')
        states_seen.add(row['reference_id'])
        members[row['candidate_id']] = genes
    return ValidationFamily(source_fold, validation_fold, tuple(sorted(members.items())), digest(locked))


def adjust_pvalues(values, method):
    p = np.asarray(values, dtype=float)
    if p.ndim != 1 or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError('p-values must be finite and within [0,1]')
    if method == 'none':
        return p.copy()
    if method == 'bh':
        return benjamini_hochberg(p)
    if method != 'holm':
        raise ValueError('unsupported correction method')
    if not len(p):
        return p.copy()
    order = np.argsort(p, kind='stable')
    corrected = np.minimum(1., np.maximum.accumulate(p[order]*(len(p)-np.arange(len(p)))))
    result = np.empty_like(p)
    result[order] = corrected
    return result


def evaluate_family(family, locked, validation_sets, validation_rows):
    if digest(locked) != family.locked_states_hash:
        raise ValueError('discovery lock changed after family freeze')
    expected = dict(family.members)
    records = {}
    for row in validation_sets:
        if row['order'] != 3:
            continue
        cid = row['candidate_id']
        if cid in records or cid not in expected:
            raise ValueError('duplicate or non-family validation gene set')
        if tuple(row['genes']) != expected[cid]:
            raise ValueError('validation gene identity changed')
        role = f'{family.validation_fold}_validation_from_{family.source_fold}'
        if row.get('evaluation_role') != role:
            raise ValueError('validation result belongs to another direction')
        records[cid] = row
    ids = [cid for cid, _ in family.members]
    p_values, tested, reasons = [], [], []
    for cid in ids:
        row = records.get(cid)
        value = row.get('p_gain') if row else None
        if value is not None and (not math.isfinite(float(value)) or not 0 <= float(value) <= 1):
            raise ValueError('invalid observed validation p-value')
        allowed = (row is not None and row.get('estimability_status') != 'poor'
                   and row.get('gain_method') == 'exact_conditional_complete_lower_order_fiber'
                   and value is not None)
        p_values.append(float(value) if allowed else 1.)
        tested.append(allowed)
        reasons.append('evaluated' if allowed else 'missing_or_unevaluable_retained_in_family')
    output, manifests = [], []
    pass_by_arm = {}
    for arm, method, level in ARMS:
        adjusted = adjust_pvalues(p_values, method)
        pass_by_arm[arm] = {}
        for i, cid in enumerate(ids):
            rejected = bool(tested[i] and adjusted[i] <= level)
            pass_by_arm[arm][cid] = rejected
            output.append(dict(family_id=family.family_id, candidate_id=cid, genes=expected[cid],
                arm=arm, method=method, level_per_direction=level, family_size=len(ids),
                p_gain=records[cid].get('p_gain') if cid in records else None,
                p_for_accounting=p_values[i], adjusted_p=float(adjusted[i]),
                tested=tested[i], evaluation_status=reasons[i], family_gain_rejected=rejected,
                p_value_unit='gene_set_not_concrete_state', source_fold=family.source_fold,
                validation_fold=family.validation_fold))
        manifests.append(dict(family.to_dict(), arm=arm, method=method,
            level_per_direction=level, n_tested=sum(tested), n_unevaluable=len(ids)-sum(tested),
            rejection_count=sum(pass_by_arm[arm].values()),
            p_values_sha256=digest(p_values), adjusted_p_sha256=digest(adjusted),
            bh_dependence_assumptions_verified=False,
            post_filter_fdr_claim=False,
            formal_bound_scope=('gene_set_FWER_across_two_directions_at_0.05_if_heldout_pvalues_valid'
                                if method == 'holm' else 'no_unqualified_global_error_rate_claim')))
    state_ids = {r['reference_id']: r for r in locked if r['order'] == 3}
    seen = set()
    states = []
    for row in validation_rows:
        if row['order'] != 3:
            continue
        rid, cid = row['reference_id'], row['candidate_id']
        if rid in seen or rid not in state_ids or state_ids[rid]['candidate_id'] != cid:
            raise ValueError('duplicate or unlocked validation state')
        seen.add(rid)
        if (row.get('discovery_fold') != family.source_fold or
                row.get('validation_fold') != family.validation_fold):
            raise ValueError('state result belongs to another direction')
        if (tuple(row['genes']) != expected[cid] or
                tuple(row['states']) != tuple(state_ids[rid]['states'])):
            raise ValueError('locked genes or state changed')
        for arm, _, _ in ARMS:
            states.append(dict(reference_id=rid, candidate_id=cid, genes=expected[cid],
                states=row['states'], pattern=row['pattern'], arm=arm, family_id=family.family_id,
                raw_cross_fold_replicated=bool(row['cross_fold_replicated']),
                family_gain_rejected=pass_by_arm[arm][cid],
                qualified=bool(row['cross_fold_replicated'] and pass_by_arm[arm][cid]),
                state_level_FDR_controlled=False, eligible_for_agent_investigation=False))
    return output, states, manifests
