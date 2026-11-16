"""Explicit controller handoff migration; never rewrite Agent science or history."""
from jure.casefile import ActionState
from jure.casefile.history import verify_history
from jure.protocol.admission import latest_admission, POLICY_VERSION


def validate_migration_source(case):
    admission = latest_admission(case)
    if (admission is None or admission.metadata.get('policy_version') != 'explorer-admission-v1'
            or admission.metadata.get('mode') != 'initial'
            or admission.metadata.get('decision') != 'ADMIT_TO_C1'):
        raise ValueError('Migration requires an admitted v1 initial proposal')
    if (case.action_state.current_phase != 'critique_needed'
            or case.action_state.next_actor != 'critic'
            or not case.mechanistic_question or not case.hypotheses or not case.evidence_questions
            or case.evidence_records or case.mechanistic_claims
            or case.critic_audits.hypothesis_audits or case.critic_audits.routing_decisions
            or case.critic_audits.revision_requests
            or any(e.action.startswith('INVESTIGATOR_') for e in case.investigation_history)):
        raise ValueError('Migration only restores the uninvestigated initial handoff; no scientific audit may be committed')
    if dict(admission.metadata['hypothesis_revision_ids']) != {
            h.hypothesis_id: h.current_revision_id for h in case.hypotheses}:
        raise ValueError('Admitted hypothesis revisions changed')
    verify_history(case)
    return admission


def migrate_initial_handoff(store, case_id, *, predecessor):
    source = store.load_case(case_id)
    admission = validate_migration_source(source)
    with store.atomic(case_id, expected_revision=source.metadata.case_revision):
        current = store.set_action_state(case_id,
            ActionState(current_phase='evidence_needed', next_actor='investigator'),
            actor='controller', expected_revision=source.metadata.case_revision)
        metadata = {k: v for k, v in dict(admission.metadata).items() if k != 'explorer_event'}
        metadata.update(policy_version=POLICY_VERSION, decision='ADMIT_TO_INVESTIGATOR',
            controller_event='PROTOCOL_ADMISSION_MIGRATED',
            source_admission_event_id=admission.event_id,
            source_policy_version='explorer-admission-v1', predecessor=predecessor,
            migration='restore_investigation_first_initial_handoff',
            scientific_objects_modified=False, budgets_reset=False)
        current = store.append_history_event(case_id, actor='controller',
            summary='Restore Investigator handoff after the existing admitted Explorer proposal; preserve all history and science.',
            metadata=metadata, expected_revision=current.metadata.case_revision)
        before = source.model_dump(mode='json')
        after = current.model_dump(mode='json')
        for field in set(before) - {'metadata', 'action_state', 'investigation_history'}:
            if before[field] != after[field]:
                raise ValueError(f'Migration changed protected section {field}')
        if current.investigation_history[:len(source.investigation_history)] != source.investigation_history:
            raise ValueError('Migration rewrote historical events')
        verify_history(current)
    return current
