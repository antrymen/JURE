"""History-derived operational budgets and uncertainty-sensitive progress."""
from jure.casefile.models import new_id
from jure.casefile.history import count_evidence_tool_calls, agent_round_counts


def budget_state(case, config, critic_round):
    attempts = {'investigator': agent_round_counts(case, 'investigator'),
                'explorer_reframe': agent_round_counts(case, 'explorer', mode='reframe'),
                'critic': agent_round_counts(case, 'critic')}
    investigator = attempts['investigator'][config.round_budget_basis]
    reframes = attempts['explorer_reframe'][config.round_budget_basis]
    acceptance_attempts=0
    if config.protocol_v3:
        from jure.protocol.contracts import accepted_revision_count,latest_revision_state
        reframes=accepted_revision_count(case)
        request,checks=latest_revision_state(case)
        if checks and not any(x['status']=='RESOLVED' for x in checks):acceptance_attempts=len(checks)
    calls = count_evidence_tool_calls(case)
    reached = []
    for name, count, maximum in (
        ('critic_rounds', critic_round, config.max_critic_rounds),
        ('investigator_rounds', investigator, config.max_investigator_rounds),
        ('total_tool_calls', calls, config.max_total_tool_calls),
    ):
        if count >= maximum:
            reached.append(name)
    if config.protocol_v3 and acceptance_attempts>=config.max_revision_acceptance_attempts:
        reached.append('revision_acceptance_attempts')
    return {'round_budget_basis': config.round_budget_basis, 'agent_attempts': attempts,
            'critic_rounds': critic_round, 'investigator_rounds': investigator,
            'explorer_reframes': reframes, 'total_tool_calls': calls,
            'revision_budget_basis':'accepted' if config.protocol_v3 else config.round_budget_basis,
            'revision_acceptance_attempts':acceptance_attempts,
            'reached_limits': reached, 'hard_limit_reached': bool(reached),
            'explorer_reframe_limit_reached': reframes >= config.max_explorer_reframes,
            'investigator_rounds_remaining': max(0, config.max_investigator_rounds - investigator),
            'explorer_reframes_remaining': max(0, config.max_explorer_reframes - reframes),
            'tool_calls_remaining': max(0, config.max_total_tool_calls - calls)}


def progress_snapshot(before, after, critic_round, route, *, run_id=None):
    from jure.casefile.critic_models import InvestigationProgressSnapshot
    from .context import active_claims
    prior = before.critic_audits.progress_snapshots[-1] if before.critic_audits.progress_snapshots else None
    # Baseline is the last audit, not the start of this call: acquisitions happen between calls.
    last_round = prior.critic_round if prior else 0
    previous_eids = {a.evidence_id for a in before.critic_audits.evidence_audits
                     if a.critic_round <= last_round}
    useful = {a.evidence_id for a in after.critic_audits.evidence_audits
              if a.critic_round == critic_round and a.relevance == 'relevant'
              and a.directness_assessment == 'direct'
              and a.context_assessment in {'matched', 'partial'}
              and a.support_quality_assessment == 'sufficient'
              and a.provenance_check == 'complete' and not a.overclaim_detected}
    evidence = {e.evidence_id: e for e in after.evidence_records}
    def identity(eid):
        record = evidence[eid]
        return record.fingerprint or (record.provenance.source_id, record.claim_tested,
                                      record.result_summary, repr(record.provenance.parameters))
    seen = {identity(eid) for eid in previous_eids if eid in evidence}
    effective = []
    for eid in sorted(useful - previous_eids):
        key = identity(eid)
        if key not in seen:
            effective.append(eid)
            seen.add(key)
    old_claims = {c.claim_id: c.status for c in active_claims(before)}
    old_hypotheses = {h.hypothesis_id: h.current_revision.status for h in before.hypotheses}
    old_gaps = {g.gap_id: g.status for g in before.evidence_gaps}
    # Capture questions added since the previous completed audit, including Investigator follow-ups.
    last_sequence = max((e.sequence for e in before.investigation_history
                         if e.action == 'CRITIC_COMPLETED'), default=0)
    new_qids = {e.object_id for e in before.investigation_history
                if e.sequence > last_sequence and e.action == 'evidence_question.created'}
    high_questions = [q.question_id for q in after.evidence_questions if q.question_id in new_qids
                      and len(q.discriminates_between) >= 2 and q.priority != 'low'
                      and q.status not in {'cancelled', 'answered'}]
    resolved_ids = {g.gap_id for g in after.evidence_gaps if g.status == 'addressed'}
    previous_resolved = set(prior.resolved_gap_ids) if prior else {
        gid for gid, status in old_gaps.items() if status == 'addressed'}
    new_gap_ids = {e.object_id for e in after.investigation_history
                   if e.sequence > last_sequence and e.action == 'evidence_gap.created'}
    changed_contradictions = {e.object_id for e in after.investigation_history
        if e.sequence > last_sequence and e.action in {'contradiction.created', 'contradiction.status_changed'}}
    values = dict(snapshot_id=new_id('PROGRESS'), critic_round=critic_round,
        new_evidence_count=len(effective), effective_evidence_ids=tuple(effective),
        resolved_gap_count=len(resolved_ids - previous_resolved), resolved_gap_ids=tuple(sorted(resolved_ids)),
        new_gap_count=len(new_gap_ids),
        hypothesis_status_changes=sum(old_hypotheses.get(h.hypothesis_id) != h.current_revision.status
                                      for h in after.hypotheses),
        claim_status_changes=sum(old_claims.get(c.claim_id, 'insufficient') != c.status for c in active_claims(after)),
        new_discriminating_question_count=len(high_questions), discriminating_question_ids=tuple(high_questions),
        contradiction_changes=len(changed_contradictions), route=route)
    return InvestigationProgressSnapshot(**values)


def is_stalled(snapshot):
    return not any((snapshot.new_evidence_count, snapshot.resolved_gap_count,
                    snapshot.hypothesis_status_changes, snapshot.claim_status_changes,
                    snapshot.new_discriminating_question_count, snapshot.contradiction_changes))


def stall_state(case, snapshot, config):
    count = 0
    for item in reversed((*case.critic_audits.progress_snapshots, snapshot)):
        if not is_stalled(item):
            break
        count += 1
    return {'consecutive_stalled_rounds': count,
            'investigation_stalled': count >= config.max_consecutive_stalled_rounds}
