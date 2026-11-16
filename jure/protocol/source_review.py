"""Read-only source history and mechanical completeness of a Critic source review.

The software never decides which source is scientifically appropriate.
"""


def source_review_targets(case):
    hypotheses = {h.hypothesis_id: h for h in case.hypotheses
                  if h.current_revision.status not in {'rejected', 'challenged'}}
    claims = [c for c in case.mechanistic_claims if c.hypothesis_id in hypotheses
              and c.hypothesis_revision_id in (None, hypotheses[c.hypothesis_id].current_revision_id)]
    cids = {c.claim_id for c in claims}
    pids = {p.prediction_id for h in hypotheses.values() for p in h.predictions
            if p.hypothesis_revision_id == h.current_revision_id}
    targets = [dict(target_id=c.claim_id, kind='claim', description=c.statement)
               for c in claims if c.critical and c.status != 'supported']
    for gap in case.evidence_gaps:
        relevant = (bool(cids.intersection(gap.related_claim_ids)) if gap.related_claim_ids
                    else bool(pids.intersection(gap.related_predictions)) if gap.related_predictions
                    else bool(set(hypotheses).intersection(gap.related_hypotheses)))
        if gap.critical and gap.status != 'addressed' and relevant:
            targets.append(dict(target_id=gap.gap_id, kind='gap', description=gap.description))
    return targets


def source_acquisition_history(case):
    """Facts only: attempts are not source exhaustion or independent confirmation."""
    rows = []
    for event in case.investigation_history:
        if event.action not in {'TOOL_CALL_COMPLETED', 'TOOL_CALL_FAILED'}:
            continue
        m = event.metadata
        rows.append(dict(event_id=event.event_id, question_id=event.object_id,
                         tool_id=m.get('tool_id'), operation=m.get('operation'),
                         parameters=m.get('parameters'), status=m.get('status'),
                         failure_reason=m.get('failure_reason'),
                         raw_result_reference=m.get('raw_result_reference')))
    return rows


def source_review_blockers(case, evaluation):
    targets = {t['target_id'] for t in source_review_targets(case)}
    reviewed = {r.target_id for r in evaluation.source_reviews if r.target_id in targets}
    unexplored = sorted({r.target_id for r in evaluation.source_reviews
                         if r.target_id in targets and r.status == 'SOURCE_UNEXPLORED'})
    return dict(unreviewed_target_ids=sorted(targets - reviewed),
                unexplored_target_ids=unexplored)


def has_source_review_blockers(case, evaluation):
    return any(source_review_blockers(case, evaluation).values())
