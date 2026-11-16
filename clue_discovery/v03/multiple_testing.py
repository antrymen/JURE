"""Explicit selected-candidate families; no claim of global search FDR."""
import numpy as np

from ..statistics import benjamini_hochberg
from .artifacts import digest


class MultipleTestingAudit:
    def __init__(self):
        self.families = []

    def adjust(self, role, order, kind, rows, p_key, id_key='candidate_id', q_key=None):
        q_key = q_key or 'q_' + kind
        ids = [row[id_key] for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError('testing family contains duplicate identities')
        values = [row.get(p_key) for row in rows]
        known = [v is not None and np.isfinite(v) for v in values]
        q = benjamini_hochberg([float(v) if ok else 1. for v, ok in zip(values, known)])
        for row, value, ok in zip(rows, q, known):
            row[q_key] = float(value) if ok else None
        name = f'{role}:order{order}:{kind}'
        self.families.append(dict(family_id=name, role=role, order=order, statistic=kind,
            unique_member_ids=ids, member_ids_sha256=digest(ids), n_members=len(ids),
            n_p_values_evaluated=sum(known), n_not_tested=len(ids)-sum(known),
            unevaluated_placeholder='p=1 only for BH accounting; no evidence/p-value imputed in result',
            adjustment='BH within recorded role/order family', inference_scope='exploratory_selected_universe',
            global_search_fdr_controlled=False))
        return name

    def manifest(self, *, generation_complete=True):
        return dict(families=self.families, generation_accounting_complete=generation_complete,
                    global_search_fdr_controlled=False, mfi_gain_independent_evidence=False,
                    note='Adaptive proposals, MFI prefilters and fitted nulls prevent an unqualified global FDR claim. '
                         'No per-neighborhood BH; one canonical gene-set/state member per recorded family.')
