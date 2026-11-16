"""Candidate lifecycle and expansion decisions stay separate from effect scores."""
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class ExpansionDecision:
    candidate_id: str
    keep: bool
    expand: bool
    estimability_ok: bool
    gain_ok: bool
    bootstrap_ok: bool
    proposal_support: bool
    reason: str

    def to_record(self):
        return asdict(self)


def decide_expansion(candidate_id, *, order, max_order, keep, estimability_status,
                     gain_ok, bootstrap_ok, proposal_support, has_supported_state):
    acceptable = estimability_status != 'poor'
    if order >= max_order:
        expand, reason = False, 'configured_max_order'
    elif order == 2:
        # Pair significance must not be a prerequisite for pure three-way discovery.
        expand = acceptable and has_supported_state and proposal_support
        reason = 'support_only_pair_extension' if expand else 'pair_not_estimable_or_supported'
    else:
        expand = keep and estimability_status == 'good' and gain_ok and bootstrap_ok and proposal_support
        reason = ('qualified_incremental_extension' if expand else
                  'keep_without_extension_at_estimability_boundary' if keep else 'no_qualified_incremental_gain')
    return ExpansionDecision(candidate_id, bool(keep), bool(expand), acceptable,
                             bool(gain_ok), bool(bootstrap_ok), bool(proposal_support), reason)
