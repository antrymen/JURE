"""Ranking consumes discovery records only, never validation or gene-name order."""
import hashlib
import math


def _number(value, default):
    return float(value) if value is not None and math.isfinite(float(value)) else default


def priority_key(row, *, seed, calibrated=True):
    quality = {'good': 0, 'sparse_boundary': 1, 'poor': 2}.get(row.get('estimability_status'), 3)
    effect = _number(row.get('set_level_gain'), abs(_number(row.get('mfi'), 0.)))
    tie = hashlib.sha256(f'{seed}:{row["candidate_id"]}:priority'.encode()).hexdigest()
    return (quality, _number(row.get('p_gain'), 1.) if calibrated else 0.,
            -effect, -_number(row.get('min_state_count'), 0.), tie)


def rank_shortlist(shortlist, *, seed, calibrated=True):
    ranked = sorted(shortlist, key=lambda item: priority_key(item[0], seed=seed, calibrated=calibrated))
    field = 'bootstrap' if calibrated else 'gain_calibration'
    for rank, (row, _) in enumerate(ranked, 1):
        row[f'{field}_priority_rank'] = rank
        row[f'{field}_priority_key'] = priority_key(row, seed=seed, calibrated=calibrated)
        row[f'{field}_priority_scope'] = 'discovery_only_no_validation_information'
    return ranked
