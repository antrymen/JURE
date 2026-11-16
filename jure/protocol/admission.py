"""Admission provenance for the Explorer → Investigator → Critic workflow."""

POLICY_VERSION = 'explorer-admission-v2'


def latest_admission(case):
    return next((e for e in reversed(case.investigation_history)
                 if (e.metadata.get('explorer_event') == 'PROPOSAL_ADMITTED'
                     or (e.actor == 'controller' and e.metadata.get('controller_event') == 'PROTOCOL_ADMISSION_MIGRATED'))
                 and e.metadata.get('policy_version') in {'explorer-admission-v1', POLICY_VERSION}), None)


def investigation_first(case):
    admission = latest_admission(case)
    return admission is not None and admission.metadata.get('policy_version') == POLICY_VERSION


def investigation_completed_after_proposal(case):
    admission = latest_admission(case)
    if admission is None:
        return True
    return any(e.sequence > admission.sequence and e.action == 'INVESTIGATOR_COMPLETED'
               for e in case.investigation_history)


def admission_context(case):
    admission = latest_admission(case)
    if admission is None:
        return None
    return {**dict(admission.metadata), 'event_id': admission.event_id}


INVESTIGATOR_ADMISSION_INSTRUCTIONS = """Explorer admission v2: You investigate before Critic performs its internal C1/C2 audit. proposal_admission.audit_flags are fallible prompts about unverified assumptions, named entities or observability; they are neither evidence nor a rejection verdict. Use them with the hypotheses and predictions to decide which supporting or challenging evidence can reduce uncertainty. You choose tools and order; no fixed evidence queue is imposed. Do not promote an unverified mediator to a known fact or change the hypotheses. Record unavailable measurements and unresolved questions without inventing evidence."""

CRITIC_ADMISSION_INSTRUCTIONS = """Explorer admission v2: The main workflow is Explorer → Investigator → Critic. You review hypotheses together with acquired evidence and limitations after investigation. Within your review, C1 audits hypothesis specificity, testability, consistency and alternatives; only a C1 pass permits C2 claim-level evidence audit. C1 failure returns hypothesis issues to Explorer within the existing budgets. Machine/completeness admission is not scientific acceptance. proposal_admission.audit_flags are fallible prompts, not evidence or established defects; never pass or fail on lexical matches or flag counts. A new named mediator may be an explicitly unverified hypothesis; assess provenance needs and the Investigator's findings. Targeted revision acceptance occurs here after investigation and does not substitute for C1. Known unavailable capabilities are limitations, never evidence."""
