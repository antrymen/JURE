"""Deterministic destination constraints; requests never select evidence tools."""
HYPOTHESIS_FAILURES = {'hypothesis_problem', 'prediction_problem', 'hypothesis_space_inadequate'}
EVIDENCE_FAILURES = {'evidence_question_problem', 'evidence_quality_problem', 'evidence_missing', 'tool_limit'}


def constrained_route(failure, proposal, *, hypothesis_passed):
    if not hypothesis_passed or failure.reason_type in HYPOTHESIS_FAILURES:
        return 'explorer'
    if failure.reason_type in EVIDENCE_FAILURES:
        return 'investigator'
    if failure.reason_type == 'evidence_conflict':
        return 'explorer' if proposal.route_to == 'explorer' else 'investigator'
    return proposal.route_to
